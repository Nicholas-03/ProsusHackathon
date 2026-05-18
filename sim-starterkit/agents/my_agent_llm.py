"""Bounded LLM advisory layer for the restaurant agent.

The model is not the primary driver. It is consulted on high-uncertainty days
such as alerts, reputation trouble, walkouts, or early setup, then its proposed
actions are validated and merged conservatively with the rule plan.
"""

from __future__ import annotations

import json
import os
from typing import Any

from agents.my_agent_config import (
    LLM_ALLOW_CHAT_FALLBACK,
    LLM_AUDIT_EVERY_DAYS,
    LLM_BASE_URL,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_REASONING_EFFORT,
    LLM_TIMEOUT_SECONDS,
    USE_LLM,
    WALKOUT_PRESSURE,
)
from agents.my_agent_utils import (
    make_notes,
    pending_by_ingredient,
    pending_by_ingredient_within,
    stock_by_ingredient,
)

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - handled as a runtime fallback.
    OpenAI = None  # type: ignore[assignment]


SYSTEM_PROMPT = """\
You are helping manage a 30-day Italian restaurant simulation.

Use the supplied rule plan as the safe default. Return ONLY a JSON array of
small adjustments when the rule plan is missing something important.

Allowed tools for your adjustments:
- place_order: {"supplier": str, "ingredient": str, "quantity_kg": number}
- set_staff_level: {"level": int}
- set_marketing_spend: {"amount": number}
- run_happy_hour: {}
- offer_daily_special: {"dish": str}

Do not use set_menu or set_price. Do not add speculative orders for ingredients
that already have a rule order today or a pending delivery soon. Prioritize:
1. avoid stockouts and unavailable dishes,
2. respect delivery schedules and supplier alerts,
3. protect reputation and walkouts,
4. only then chase profit.

The deterministic rule plan already uses EOQ-style inventory sizing. Adjust it
only for obvious gaps, late pending orders, fresh alerts, or severe service risk.
Use exact names from the observation. Return [] if the rule plan is good enough.
"""


def refine_actions_with_llm(
    observation: dict[str, Any],
    day: int,
    rule_actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a conservative hybrid plan.

    Any LLM failure falls back to the rule actions unchanged.
    """
    if not _should_consult_llm(observation, day):
        return rule_actions

    api_key = _openai_api_key()
    if not api_key or OpenAI is None:
        return rule_actions

    try:
        proposed = _call_llm(observation, day, rule_actions, api_key)
        accepted = _validate_llm_actions(observation, rule_actions, proposed)
        if not accepted:
            return _merge_actions(observation, rule_actions, [], llm_status="checked")
        return _merge_actions(observation, rule_actions, accepted, llm_status="used")
    except Exception as exc:
        print(f"  LLM advisory skipped on day {day}: {exc}")
        return _merge_actions(observation, rule_actions, [], llm_status="error")


def _should_consult_llm(observation: dict[str, Any], day: int) -> bool:
    if not USE_LLM:
        return False

    service = observation.get("service_summary") or {}
    walkouts = WALKOUT_PRESSURE.get(service.get("walkout_band", "None"), 0)
    avg_wait = float(service.get("avg_wait_minutes") or 0)
    peak_wait = float(service.get("peak_wait_minutes") or 0)
    scenario_text = " ".join(str(alert) for alert in observation.get("alerts", []))
    scenario_text += " " + str(observation.get("notes", ""))
    stress_scenario = any(token in scenario_text.lower() for token in ("supply", "renovation", "tourist"))
    periodic_audit = LLM_AUDIT_EVERY_DAYS > 0 and day % LLM_AUDIT_EVERY_DAYS == 0

    return any([
        day == 1,
        bool(observation.get("alerts")),
        observation.get("reputation_band") == "Poor",
        observation.get("customer_trend") == "Declining",
        bool(service.get("dishes_unavailable_at")),
        stress_scenario and periodic_audit,
        walkouts >= 3 and (avg_wait > 8 or peak_wait > 20),
        float(observation.get("cash", 0)) < 4_000,
    ])


def _openai_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY") or os.getenv("API KEY")


def _call_llm(
    observation: dict[str, Any],
    day: int,
    rule_actions: list[dict[str, Any]],
    api_key: str,
) -> list[dict[str, Any]]:
    assert OpenAI is not None
    client = OpenAI(api_key=api_key, base_url=LLM_BASE_URL, timeout=LLM_TIMEOUT_SECONDS)
    payload = json.dumps(_llm_payload(observation, day, rule_actions), separators=(",", ":"))
    try:
        response = client.responses.create(
            model=LLM_MODEL,
            instructions=SYSTEM_PROMPT,
            input=payload,
            max_output_tokens=LLM_MAX_TOKENS,
            reasoning={"effort": LLM_REASONING_EFFORT},
        )
        content = _response_text(response) or "[]"
    except Exception:
        if not LLM_ALLOW_CHAT_FALLBACK:
            raise
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": payload},
            ],
            max_completion_tokens=LLM_MAX_TOKENS,
        )
        content = response.choices[0].message.content or "[]"
    return _parse_json_array(content)


def _response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text

    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks)


def _llm_payload(
    observation: dict[str, Any],
    day: int,
    rule_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    menu_book = observation.get("menu_book", [])
    service = observation.get("service_summary") or {}
    inventory = observation.get("inventory", [])
    stock = stock_by_ingredient(observation)
    pending = pending_by_ingredient(observation)
    pending_soon = pending_by_ingredient_within(observation, 2.5)
    rule_orders = [
        action.get("args", {})
        for action in rule_actions
        if action.get("tool") == "place_order"
    ]

    low_inventory = [
        {
            "ingredient": item.get("ingredient"),
            "kg": round(float(item.get("total_kg") or 0), 2),
            "shelf_life_days": item.get("shelf_life_days"),
        }
        for item in inventory
        if float(item.get("total_kg") or 0) < 8
    ]

    recipes = [
        {
            "name": dish.get("name"),
            "active": dish.get("name") in observation.get("active_menu", []),
            "base_price": dish.get("base_price"),
            "ingredients": dish.get("ingredients", []),
        }
        for dish in menu_book
    ]

    return {
        "day": day,
        "day_of_week": observation.get("day_of_week"),
        "days_remaining": observation.get("days_remaining"),
        "cash": observation.get("cash"),
        "reputation_band": observation.get("reputation_band"),
        "customer_trend": observation.get("customer_trend"),
        "weather_today": observation.get("weather_today"),
        "weather_forecast": observation.get("weather_forecast"),
        "alerts": observation.get("alerts", []),
        "staff_level": observation.get("staff_level"),
        "active_menu": observation.get("active_menu", []),
        "service_summary": {
            "covers": service.get("total_covers"),
            "walkout_band": service.get("walkout_band"),
            "avg_wait_minutes": service.get("avg_wait_minutes"),
            "peak_wait_minutes": service.get("peak_wait_minutes"),
            "dishes_sold": service.get("dishes_sold", {}),
            "dishes_unavailable_at": service.get("dishes_unavailable_at", {}),
            "kitchen_bottleneck_hours": service.get("kitchen_bottleneck_hours", []),
        },
        "low_inventory": low_inventory,
        "stock_kg": stock,
        "pending_kg": pending,
        "pending_soon_kg": pending_soon,
        "pending_orders": observation.get("pending_orders", []),
        "suppliers": observation.get("supplier_catalog", []),
        "recipes": recipes,
        "rule_orders": rule_orders,
        "decision_rules": [
            "Check dishes_unavailable_at before proposing any action.",
            "Do not double-order if an ingredient is already pending soon.",
            "Prefer preventing one stockout over marginal profit gains.",
            "Treat supplier halt/outage/delay alerts as immediate routing changes.",
        ],
        "rule_actions": [action for action in rule_actions if action.get("tool") != "save_notes"],
    }


def _parse_json_array(content: str) -> list[dict[str, Any]]:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    if not text.startswith("[") and "[" in text and "]" in text:
        text = text[text.find("["): text.rfind("]") + 1]

    data = json.loads(text)
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _validate_llm_actions(
    observation: dict[str, Any],
    rule_actions: list[dict[str, Any]],
    proposed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    menu_names = {dish["name"] for dish in observation.get("menu_book", [])}
    menu_book = {dish["name"]: dish for dish in observation.get("menu_book", [])}
    active_menu = set(observation.get("active_menu", []))
    suppliers = {supplier["name"]: supplier for supplier in observation.get("supplier_catalog", [])}
    service = observation.get("service_summary") or {}
    stockout_dishes = set((service.get("dishes_unavailable_at") or {}).keys())
    stockout_ingredient_names = {
        ingredient["ingredient"]
        for dish_name in stockout_dishes
        for ingredient in menu_book.get(dish_name, {}).get("ingredients", [])
    }
    already_pending = pending_by_ingredient_within(observation, 4.0)
    fresh_stock = stock_by_ingredient(observation, min_expires_in_days=1)
    rule_staff = _effective_staff_level(observation, rule_actions)
    rule_special = next(
        (
            action.get("args", {}).get("dish")
            for action in rule_actions
            if action.get("tool") == "offer_daily_special"
        ),
        None,
    )
    walkouts = WALKOUT_PRESSURE.get(service.get("walkout_band", "None"), 0)
    already_ordered = {
        action.get("args", {}).get("ingredient")
        for action in rule_actions
        if action.get("tool") == "place_order"
    }

    accepted: list[dict[str, Any]] = []
    order_budget = max(0.0, float(observation.get("cash", 0)) - 2_000) * 0.35
    order_spend = 0.0

    for action in proposed[:6]:
        tool = action.get("tool")
        args = action.get("args") or {}
        if not isinstance(args, dict):
            continue

        if tool == "set_staff_level":
            level = _as_int(args.get("level"))
            if level is not None and 5 <= level <= 12:
                if level < rule_staff:
                    continue
                if level > rule_staff + 1 and walkouts < 3:
                    continue
                if rule_staff <= 5 and level > 6:
                    continue
                accepted.append({"tool": tool, "args": {"level": level}})

        elif tool == "set_marketing_spend":
            amount = _as_float(args.get("amount"))
            if amount is not None and 0 <= amount <= 250:
                if stockout_dishes and amount > 0:
                    continue
                accepted.append({"tool": tool, "args": {"amount": round(amount, 2)}})

        elif tool == "run_happy_hour":
            if not (observation.get("service_summary") or {}).get("dishes_unavailable_at"):
                accepted.append({"tool": tool, "args": {}})

        elif tool == "offer_daily_special":
            dish = args.get("dish")
            if rule_special:
                continue
            if dish in menu_names and (not active_menu or dish in active_menu):
                accepted.append({"tool": tool, "args": {"dish": dish}})

        elif tool == "place_order":
            supplier_name = args.get("supplier")
            ingredient = args.get("ingredient")
            qty = _as_float(args.get("quantity_kg"))
            supplier = suppliers.get(supplier_name)
            if not supplier or ingredient not in supplier.get("ingredients", {}) or qty is None:
                continue
            if ingredient in already_ordered:
                continue
            if ingredient not in stockout_ingredient_names and fresh_stock.get(ingredient, 0.0) > 1.0:
                continue
            if ingredient in already_pending and ingredient not in stockout_ingredient_names:
                continue
            min_order = float(supplier.get("min_order_kg") or 0)
            if qty < min_order:
                continue
            if qty > 45 and ingredient not in stockout_ingredient_names:
                continue
            cost = qty * float(supplier["ingredients"][ingredient])
            if order_spend + cost > order_budget:
                continue
            order_spend += cost
            already_ordered.add(ingredient)
            accepted.append({
                "tool": tool,
                "args": {
                    "supplier": supplier_name,
                    "ingredient": ingredient,
                    "quantity_kg": round(qty, 1),
                },
            })

    return accepted


def _merge_actions(
    observation: dict[str, Any],
    rule_actions: list[dict[str, Any]],
    llm_actions: list[dict[str, Any]],
    *,
    llm_status: str,
) -> list[dict[str, Any]]:
    actions = [action for action in rule_actions if action.get("tool") != "save_notes"]

    for action in llm_actions:
        tool = action["tool"]
        if tool in {"set_staff_level", "set_marketing_spend", "offer_daily_special"}:
            actions = [existing for existing in actions if existing.get("tool") != tool]
        elif tool == "run_happy_hour" and any(existing.get("tool") == "run_happy_hour" for existing in actions):
            continue
        actions.append(action)

    staff_level = _effective_staff_level(observation, actions)
    marketing_spend = _effective_marketing_spend(actions)
    actions.append({
        "tool": "save_notes",
        "args": {"text": make_notes(observation, staff_level, marketing_spend, llm_status=llm_status)},
    })
    return actions


def _effective_staff_level(observation: dict[str, Any], actions: list[dict[str, Any]]) -> int:
    level = int(observation.get("staff_level") or 8)
    for action in actions:
        if action.get("tool") == "set_staff_level":
            level = int(action.get("args", {}).get("level", level))
    return level


def _effective_marketing_spend(actions: list[dict[str, Any]]) -> int:
    amount = 0
    for action in actions:
        if action.get("tool") == "set_marketing_spend":
            amount = int(float(action.get("args", {}).get("amount", amount)))
    return amount


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
