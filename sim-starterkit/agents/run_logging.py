"""Small JSONL logger for RestBench runs."""

from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def log_dir() -> Path | None:
    if os.getenv("RESTBENCH_DISABLE_LOGS", "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    return Path(os.getenv("RESTBENCH_LOG_DIR", "logs"))


def make_log_path(team_name: str, scenario: str, seed: int, game_id: str | None = None) -> Path | None:
    directory = log_dir()
    if directory is None:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    safe_team = _safe(team_name)
    safe_scenario = _safe(scenario)
    suffix = f"-{game_id[:8]}" if game_id else ""
    return directory / f"{safe_team}-{safe_scenario}-seed{seed}{suffix}.jsonl"


def append_jsonl(path: Path | None, event: str, **payload: Any) -> None:
    if path is None:
        return
    record = {"ts": round(time.time(), 3), "event": event, **payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")


def summarize_observation(observation: dict[str, Any]) -> dict[str, Any]:
    service = observation.get("service_summary") or {}
    active_menu = observation.get("active_menu", [])
    return {
        "day": observation.get("day"),
        "day_of_week": observation.get("day_of_week"),
        "days_remaining": observation.get("days_remaining"),
        "cash": observation.get("cash"),
        "staff_level": observation.get("staff_level"),
        "reputation_band": observation.get("reputation_band"),
        "customer_trend": observation.get("customer_trend"),
        "weather_today": observation.get("weather_today"),
        "weather_forecast": observation.get("weather_forecast"),
        "alerts": observation.get("alerts", []),
        "notes": observation.get("notes", ""),
        "active_menu": active_menu,
        "inventory_kg": {
            item.get("ingredient"): round(float(item.get("total_kg") or 0), 2)
            for item in observation.get("inventory", [])
        },
        "fresh_inventory_kg": _stock_by_ingredient(observation, min_expires_in_days=1),
        "pending_by_ingredient": _pending_by_ingredient(observation),
        "pending_orders": observation.get("pending_orders", []),
        "dish_servings_with_pending": _dish_servings_with_pending(observation, active_menu),
        "supplier_catalog": [
            {
                "name": supplier.get("name"),
                "lead_time_days": supplier.get("lead_time_days"),
                "delivery_days": supplier.get("delivery_days", []),
                "ingredients": supplier.get("ingredients", {}),
            }
            for supplier in observation.get("supplier_catalog", [])
        ],
        "service_summary": {
            "total_covers": service.get("total_covers"),
            "walkout_band": service.get("walkout_band"),
            "avg_wait_minutes": service.get("avg_wait_minutes"),
            "peak_wait_minutes": service.get("peak_wait_minutes"),
            "dishes_sold": service.get("dishes_sold", {}),
            "dishes_unavailable_at": service.get("dishes_unavailable_at", {}),
            "kitchen_bottleneck_hours": service.get("kitchen_bottleneck_hours", []),
        },
    }


def summarize_actions(observation: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    pending = _pending_by_ingredient(observation)
    suppliers = {supplier.get("name"): supplier for supplier in observation.get("supplier_catalog", [])}
    order_actions = [action for action in actions if action.get("tool") == "place_order"]
    ordered_ingredients = [
        (action.get("args") or {}).get("ingredient")
        for action in order_actions
    ]
    counts = Counter(ingredient for ingredient in ordered_ingredients if ingredient)

    return {
        "tool_counts": dict(Counter(action.get("tool") for action in actions)),
        "staff_level": _last_arg(actions, "set_staff_level", "level", observation.get("staff_level")),
        "marketing_spend": _last_arg(actions, "set_marketing_spend", "amount", 0),
        "menu_size": len(_last_arg(actions, "set_menu", "dishes", observation.get("active_menu", [])) or []),
        "happy_hour": any(action.get("tool") == "run_happy_hour" for action in actions),
        "daily_special": _last_arg(actions, "offer_daily_special", "dish", None),
        "save_notes": any(action.get("tool") == "save_notes" for action in actions),
        "duplicate_order_ingredients_same_day": [
            ingredient for ingredient, count in counts.items() if count > 1
        ],
        "ordered_while_pending": [
            ingredient for ingredient in ordered_ingredients if ingredient in pending
        ],
        "orders": [
            _summarize_order(observation, suppliers, pending, action)
            for action in order_actions
        ],
    }


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)[:80]


def _summarize_order(
    observation: dict[str, Any],
    suppliers: dict[str, dict[str, Any]],
    pending: dict[str, float],
    action: dict[str, Any],
) -> dict[str, Any]:
    args = action.get("args") or {}
    supplier = suppliers.get(args.get("supplier")) or {}
    ingredient = args.get("ingredient")
    qty = float(args.get("quantity_kg") or 0)
    price = float((supplier.get("ingredients") or {}).get(ingredient) or 0)
    return {
        "supplier": args.get("supplier"),
        "ingredient": ingredient,
        "quantity_kg": round(qty, 2),
        "pending_before_kg": round(float(pending.get(ingredient, 0)), 2),
        "eta_days": _days_until_delivery(supplier, observation.get("day_of_week", "Monday")),
        "delivery_days": supplier.get("delivery_days", []),
        "lead_time_days": supplier.get("lead_time_days"),
        "estimated_cost": round(qty * price, 2),
    }


def _last_arg(actions: list[dict[str, Any]], tool: str, arg: str, default: Any) -> Any:
    value = default
    for action in actions:
        if action.get("tool") == tool:
            value = (action.get("args") or {}).get(arg, value)
    return value


def _stock_by_ingredient(observation: dict[str, Any], min_expires_in_days: int = 0) -> dict[str, float]:
    stock: dict[str, float] = {}
    for item in observation.get("inventory", []):
        ingredient = item.get("ingredient")
        batches = item.get("batches") or []
        if batches:
            qty = sum(
                float(batch.get("quantity_kg") or 0)
                for batch in batches
                if int(batch.get("expires_in_days") or 0) >= min_expires_in_days
            )
        else:
            qty = float(item.get("total_kg") or 0)
        stock[ingredient] = round(qty, 3)
    return stock


def _pending_by_ingredient(observation: dict[str, Any]) -> dict[str, float]:
    pending: dict[str, float] = defaultdict(float)
    for order in observation.get("pending_orders", []):
        pending[order.get("ingredient")] += float(order.get("quantity_kg") or 0)
    return {ingredient: round(qty, 3) for ingredient, qty in pending.items()}


def _dish_servings_with_pending(observation: dict[str, Any], active_menu: list[str]) -> dict[str, float]:
    stock = _stock_by_ingredient(observation, min_expires_in_days=1)
    pending = _pending_by_ingredient(observation)
    menu_book = {dish.get("name"): dish for dish in observation.get("menu_book", [])}
    servings: dict[str, float] = {}
    for dish_name in active_menu:
        dish = menu_book.get(dish_name)
        if not dish:
            continue
        dish_servings = float("inf")
        for ingredient in dish.get("ingredients", []):
            name = ingredient.get("ingredient")
            qty = float(ingredient.get("quantity_kg") or 0)
            available = stock.get(name, 0.0) + pending.get(name, 0.0)
            if qty:
                dish_servings = min(dish_servings, available / qty)
        servings[dish_name] = round(0.0 if dish_servings == float("inf") else dish_servings, 1)
    return servings


def _days_until_delivery(supplier: dict[str, Any], current_day_of_week: str) -> int | None:
    if not supplier:
        return None
    delivery_days = set(supplier.get("delivery_days") or [])
    lead_time = int(supplier.get("lead_time_days") or 1)
    current_idx = WEEKDAYS.index(current_day_of_week) if current_day_of_week in WEEKDAYS else 0

    for offset in range(max(1, lead_time), 15):
        candidate_day = WEEKDAYS[(current_idx + offset) % 7]
        if candidate_day in delivery_days:
            return offset
    return lead_time + 7
