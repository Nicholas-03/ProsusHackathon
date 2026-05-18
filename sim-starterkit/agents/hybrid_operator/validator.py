"""Validate and repair tool calls before returning them to the runner."""

from __future__ import annotations

from typing import Any

from .constants import ALLOWED_TOOLS, MAX_MARKETING, MAX_STAFF, MIN_MENU_DISHES, MIN_STAFF, NOTES_LIMIT
from .finance import available_order_budget, cash_reserve
from .risk import RiskAssessment
from .state import GameState


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _order_cost(state: GameState, action: dict[str, Any]) -> float:
    args = action.get("args", {})
    supplier = state.suppliers.get(str(args.get("supplier", "")))
    ingredient = str(args.get("ingredient", ""))
    if not supplier or ingredient not in supplier.ingredients:
        return 0.0
    return float(args.get("quantity_kg", 0.0) or 0.0) * supplier.ingredients[ingredient]


def _shortage_ingredients(state: GameState) -> set[str]:
    shortage: set[str] = set()
    unavailable = state.service_summary.get("dishes_unavailable_at") or {}
    if isinstance(unavailable, dict):
        for dish_name in unavailable:
            dish = state.menu_book.get(str(dish_name))
            if dish:
                shortage.update(ing.ingredient for ing in dish.ingredients)
    return shortage


def _cheapest_valid_supplier(state: GameState, ingredient: str) -> tuple[str, float, float] | None:
    best = None
    for supplier in state.suppliers.values():
        if ingredient not in supplier.ingredients:
            continue
        price = supplier.ingredients[ingredient]
        candidate = (supplier.name, price, supplier.min_order_kg)
        if best is None or price < best[1]:
            best = candidate
    return best


def _repair_menu(state: GameState, dishes: list[Any]) -> list[str]:
    repaired: list[str] = []
    for dish in dishes:
        name = str(dish)
        if name in state.menu_book and name not in repaired:
            repaired.append(name)
    for name in state.active_menu:
        if name in state.menu_book and name not in repaired:
            repaired.append(name)
        if len(repaired) >= MIN_MENU_DISHES:
            break
    for name in state.menu_book:
        if name not in repaired:
            repaired.append(name)
        if len(repaired) >= MIN_MENU_DISHES:
            break
    return repaired


def _validate_single(action: dict[str, Any], state: GameState) -> dict[str, Any] | None:
    tool = action.get("tool")
    if tool not in ALLOWED_TOOLS:
        return None
    args = action.get("args") if isinstance(action.get("args"), dict) else {}

    if tool == "set_staff_level":
        level = int(round(float(args.get("level", state.staff_level))))
        return {"tool": tool, "args": {"level": int(_clamp(level, MIN_STAFF, MAX_STAFF))}}

    if tool == "set_marketing_spend":
        amount = round(_clamp(float(args.get("amount", 0.0) or 0.0), 0.0, MAX_MARKETING), 2)
        return {"tool": tool, "args": {"amount": amount}}

    if tool == "run_happy_hour":
        return {"tool": tool, "args": {}}

    if tool == "save_notes":
        text = str(args.get("text", ""))[:NOTES_LIMIT]
        return {"tool": tool, "args": {"text": text}}

    if tool == "set_price":
        dish_name = str(args.get("dish", ""))
        dish = state.menu_book.get(dish_name)
        if not dish or dish.base_price <= 0:
            return None
        price = float(args.get("price", dish.current_price) or dish.current_price)
        price = round(_clamp(price, dish.base_price * 0.8, dish.base_price * 1.2), 2)
        return {"tool": tool, "args": {"dish": dish_name, "price": price}}

    if tool == "set_menu":
        dishes = _repair_menu(state, list(args.get("dishes", [])))
        if len(dishes) < MIN_MENU_DISHES:
            return None
        return {"tool": tool, "args": {"dishes": dishes}}

    if tool == "offer_daily_special":
        dish_name = str(args.get("dish", ""))
        if dish_name not in state.menu_book or dish_name not in state.active_menu:
            active = [name for name in state.active_menu if name in state.menu_book]
            if not active:
                return None
            dish_name = active[0]
        return {"tool": tool, "args": {"dish": dish_name}}

    if tool == "place_order":
        supplier_name = str(args.get("supplier", ""))
        ingredient = str(args.get("ingredient", ""))
        supplier = state.suppliers.get(supplier_name)
        if not supplier or ingredient not in supplier.ingredients:
            replacement = _cheapest_valid_supplier(state, ingredient)
            if not replacement:
                return None
            supplier_name = replacement[0]
            supplier = state.suppliers[supplier_name]
        qty = float(args.get("quantity_kg", 0.0) or 0.0)
        qty = max(qty, supplier.min_order_kg)
        qty = round(qty * 2.0) / 2.0
        if qty <= 0:
            return None
        return {
            "tool": tool,
            "args": {
                "supplier": supplier_name,
                "ingredient": ingredient,
                "quantity_kg": round(qty, 1),
            },
        }
    return None


def _dedupe(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    singleton_tools = {"set_staff_level", "set_menu", "set_marketing_spend", "run_happy_hour", "offer_daily_special", "save_notes"}
    latest_singletons: dict[str, dict[str, Any]] = {}
    price_actions: dict[str, dict[str, Any]] = {}
    order_actions: dict[tuple[str, str], dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []
    for action in actions:
        tool = action["tool"]
        args = action["args"]
        if tool in singleton_tools:
            latest_singletons[tool] = action
        elif tool == "set_price":
            price_actions[str(args.get("dish"))] = action
        elif tool == "place_order":
            key = (str(args.get("supplier")), str(args.get("ingredient")))
            existing = order_actions.get(key)
            if not existing or float(args.get("quantity_kg", 0.0)) > float(existing["args"].get("quantity_kg", 0.0)):
                order_actions[key] = action
        else:
            ordered.append(action)
    ordered.extend(order_actions.values())
    ordered.extend(price_actions.values())
    for tool in ["set_menu", "set_staff_level", "set_marketing_spend", "run_happy_hour", "offer_daily_special", "save_notes"]:
        if tool in latest_singletons:
            ordered.append(latest_singletons[tool])
    return ordered


def _planned_staff_level(actions: list[dict[str, Any]], state: GameState) -> int:
    for action in reversed(actions):
        if action["tool"] == "set_staff_level":
            return int(action["args"].get("level", state.staff_level))
    return state.staff_level


def _cash_repair(
    actions: list[dict[str, Any]],
    state: GameState,
    risk: RiskAssessment,
    metrics: Any | None = None,
) -> list[dict[str, Any]]:
    shortage = _shortage_ingredients(state)
    planned_staff = _planned_staff_level(actions, state)

    non_order_spend = 0.0
    for action in actions:
        if action["tool"] == "set_marketing_spend":
            non_order_spend += float(action["args"].get("amount", 0.0) or 0.0)

    budget = available_order_budget(
        state,
        risk,
        metrics,
        staff_level=planned_staff,
        non_order_spend=non_order_spend,
    )
    if metrics is None:
        budget = min(budget, max(0.0, state.cash - cash_reserve(state, risk, planned_staff)))

    if non_order_spend > budget and risk.cash_risk in {"high", "critical"}:
        actions = [action for action in actions if action["tool"] != "set_marketing_spend"]
        non_order_spend = 0.0
        budget = available_order_budget(state, risk, metrics, staff_level=planned_staff)

    remaining = max(0.0, budget - non_order_spend)
    orders = [action for action in actions if action["tool"] == "place_order"]
    others = [action for action in actions if action["tool"] != "place_order"]
    orders.sort(
        key=lambda action: (
            str(action["args"].get("ingredient")) in shortage,
            -_order_cost(state, action),
        ),
        reverse=True,
    )

    kept_orders: list[dict[str, Any]] = []
    spent = 0.0
    for order in orders:
        cost = _order_cost(state, order)
        ingredient = str(order["args"].get("ingredient"))
        if spent + cost <= remaining:
            kept_orders.append(order)
            spent += cost
            continue
        if ingredient in shortage and remaining - spent > 0:
            supplier = state.suppliers.get(str(order["args"].get("supplier")))
            if not supplier:
                continue
            min_cost = supplier.min_order_kg * supplier.ingredients[ingredient]
            if spent + min_cost <= remaining:
                repaired = {
                    "tool": "place_order",
                    "args": {
                        **order["args"],
                        "quantity_kg": round(supplier.min_order_kg, 1),
                    },
                }
                kept_orders.append(repaired)
                spent += min_cost
    return kept_orders + others


def validate_actions(
    actions: list[dict[str, Any]],
    state: GameState,
    risk: RiskAssessment,
    metrics: Any | None = None,
) -> list[dict[str, Any]]:
    repaired = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        valid = _validate_single(action, state)
        if valid:
            repaired.append(valid)
    repaired = _dedupe(repaired)
    repaired = _cash_repair(repaired, state, risk, metrics)
    return _dedupe(repaired)
