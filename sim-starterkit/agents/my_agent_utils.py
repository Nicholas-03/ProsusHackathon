"""Shared helpers for the restaurant agent."""

from __future__ import annotations

from collections import defaultdict
from math import ceil
from typing import Any

from agents.my_agent_config import WEEKDAYS


def active_from_book(menu_book: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name, dish in menu_book.items() if dish.get("is_active")]


def same_items(left: list[str], right: list[str]) -> bool:
    return set(left) == set(right) and len(left) == len(right)


def stock_by_ingredient(observation: dict[str, Any], min_expires_in_days: int = 0) -> dict[str, float]:
    stock: dict[str, float] = {}
    for item in observation.get("inventory", []):
        ingredient = item["ingredient"]
        batches = item.get("batches") or []
        if batches:
            qty = sum(
                float(batch.get("quantity_kg") or 0)
                for batch in batches
                if int(batch.get("expires_in_days") or 0) >= min_expires_in_days
            )
        else:
            qty = float(item.get("total_kg") or 0)
        stock[ingredient] = qty
    return stock


def pending_by_ingredient(observation: dict[str, Any]) -> dict[str, float]:
    pending: dict[str, float] = defaultdict(float)
    for order in observation.get("pending_orders", []):
        pending[order["ingredient"]] += float(order.get("quantity_kg") or 0)
    return dict(pending)


def cheapest_supplier_by_ingredient(observation: dict[str, Any]) -> dict[str, float]:
    cheapest: dict[str, float] = {}
    for supplier in observation.get("supplier_catalog", []):
        for ingredient, price in supplier.get("ingredients", {}).items():
            if ingredient not in cheapest or float(price) < cheapest[ingredient]:
                cheapest[ingredient] = float(price)
    return cheapest


def servings_available(
    dish: dict[str, Any],
    stock: dict[str, float],
    pending: dict[str, float],
) -> float:
    servings = float("inf")
    for ingredient in dish.get("ingredients", []):
        name = ingredient["ingredient"]
        qty = float(ingredient["quantity_kg"])
        available = stock.get(name, 0.0) + pending.get(name, 0.0)
        servings = min(servings, available / qty if qty else float("inf"))
    return 0.0 if servings == float("inf") else servings


def estimated_margin(dish: dict[str, Any], ingredient_prices: dict[str, float]) -> float:
    ingredient_cost = 0.0
    for ingredient in dish.get("ingredients", []):
        name = ingredient["ingredient"]
        ingredient_cost += ingredient_prices.get(name, 0.0) * float(ingredient["quantity_kg"])
    return float(dish.get("base_price") or 0) - ingredient_cost


def stockout_ingredients(
    observation: dict[str, Any],
    menu_book: dict[str, dict[str, Any]],
) -> set[str]:
    service = observation.get("service_summary") or {}
    stockout_dishes = (service.get("dishes_unavailable_at") or {}).keys()
    ingredients = set()
    for dish_name in stockout_dishes:
        dish = menu_book.get(dish_name)
        if not dish:
            continue
        for ingredient in dish.get("ingredients", []):
            ingredients.add(ingredient["ingredient"])
    return ingredients


def days_until_delivery(supplier: dict[str, Any], current_day_of_week: str) -> int:
    delivery_days = set(supplier.get("delivery_days") or [])
    lead_time = int(supplier.get("lead_time_days") or 1)
    current_idx = WEEKDAYS.index(current_day_of_week) if current_day_of_week in WEEKDAYS else 0

    for offset in range(max(1, lead_time), 15):
        candidate_day = WEEKDAYS[(current_idx + offset) % 7]
        if candidate_day in delivery_days:
            return offset
    return lead_time + 7


def supplier_reliability(observation: dict[str, Any]) -> dict[str, float]:
    ordered: dict[str, float] = defaultdict(float)
    delivered: dict[str, float] = defaultdict(float)

    for entry in observation.get("delivery_history", []):
        supplier = entry.get("supplier")
        if not supplier:
            continue
        ordered[supplier] += float(entry.get("ordered_kg") or 0)
        delivered[supplier] += float(entry.get("delivered_kg") or 0)

    return {
        supplier: max(0.4, min(1.0, delivered[supplier] / qty))
        for supplier, qty in ordered.items()
        if qty > 0
    }


def suppliers_in_alerts(observation: dict[str, Any]) -> set[str]:
    alerts = " ".join(str(alert) for alert in observation.get("alerts", [])).lower()
    if not alerts:
        return set()

    bad_words = ("halt", "outage", "disrupt", "strike", "closed", "unavailable", "delay")
    if not any(word in alerts for word in bad_words):
        return set()

    blocked = set()
    for supplier in observation.get("supplier_catalog", []):
        name = supplier.get("name", "")
        if name and name.lower() in alerts:
            blocked.add(name)
    return blocked


def best_supplier_for_ingredient(
    observation: dict[str, Any],
    suppliers: list[dict[str, Any]],
    ingredient: str,
) -> dict[str, Any] | None:
    candidates = [supplier for supplier in suppliers if ingredient in supplier.get("ingredients", {})]
    if not candidates:
        return None

    current_dow = observation.get("day_of_week", "Monday")
    reliability = supplier_reliability(observation)
    blocked_suppliers = suppliers_in_alerts(observation)

    def score(supplier: dict[str, Any]) -> tuple[float, float]:
        name = supplier["name"]
        price = float(supplier["ingredients"][ingredient])
        eta = days_until_delivery(supplier, current_dow)
        reliability_penalty = 1.0 + (1.0 - reliability.get(name, 1.0)) * 0.35
        alert_penalty = 25.0 if name in blocked_suppliers else 0.0
        return (price * reliability_penalty + eta * 0.12 + alert_penalty, eta)

    return min(candidates, key=score)


def round_order_qty(qty: float) -> float:
    return round(ceil(qty * 2) / 2, 1)


def make_notes(observation: dict[str, Any], staff_level: int, marketing_spend: int, llm_used: bool = False) -> str:
    service = observation.get("service_summary") or {}
    stockouts = service.get("dishes_unavailable_at") or {}
    llm_note = "; llm=used" if llm_used else ""
    scenario_note = _scenario_note(observation)
    return (
        f"Day {observation.get('day')}: cash={float(observation.get('cash', 0)):.0f}; "
        f"staff={staff_level}; marketing={marketing_spend}; "
        f"covers_yday={service.get('total_covers', 0)}; "
        f"walkouts={service.get('walkout_band', 'n/a')}; "
        f"stockouts={','.join(stockouts.keys()) if stockouts else 'none'}; "
        f"pending={len(observation.get('pending_orders', []))}; "
        f"alerts={len(observation.get('alerts', []))}"
        f"{scenario_note}"
        f"{llm_note}"
    )


def has_scenario_flag(observation: dict[str, Any], flag: str) -> bool:
    text = " ".join(str(alert) for alert in observation.get("alerts", []))
    text += " " + str(observation.get("notes", ""))
    return flag.lower() in text.lower()


def _scenario_note(observation: dict[str, Any]) -> str:
    text = " ".join(str(alert) for alert in observation.get("alerts", []))
    text += " " + str(observation.get("notes", ""))
    lowered = text.lower()
    if "renovation" in lowered:
        return "; scenario=renovation"
    if (
        "supply" in lowered
        or "supplier" in lowered
        or "outage" in lowered
        or "disruption" in lowered
        or "shipping lane" in lowered
        or "mediterranean" in lowered
    ):
        return "; scenario=supply"
    if "tourist" in lowered or "festival" in lowered:
        return "; scenario=tourist"
    return ""
