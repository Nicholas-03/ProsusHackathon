"""Deterministic EOQ-based strategy for the RestBench restaurant game."""

from __future__ import annotations

from typing import Any

from agents.my_agent_config import (
    EMERGENCY_CASH_RESERVE,
    FIXED_DAILY_COST,
    MAX_ORDER_BUDGET_FRACTION,
    MIN_CASH_RESERVE,
    STAFF_COST,
)
from agents.my_agent_inventory import (
    best_supplier,
    build_supplier_options,
    dish_unit_cost,
    eoq_piecewise,
    pending_by_ingredient,
    pending_due_by_ingredient,
    recipe_ingredients,
    shelf_life_by_ingredient,
    stock_by_ingredient,
)
from agents.my_agent_optimizer import (
    choose_marketing,
    choose_menu,
    choose_special,
    choose_staff_level,
    dish_shares,
    estimate_covers,
    price_for_dish,
    service_stress,
    should_run_happy_hour,
    update_state_after_plan,
)
from agents.my_agent_utils import clamp, read_notes, round_kg, safe_float, safe_int, tool_call, write_notes


def build_rule_actions(observation: dict[str, Any], day: int) -> list[dict[str, Any]]:
    del day
    state = read_notes(observation.get("notes"))
    supplier_options = build_supplier_options(observation)
    stock = stock_by_ingredient(observation, min_expires_in_days=1)
    total_stock = stock_by_ingredient(observation, min_expires_in_days=0)
    pending = pending_by_ingredient(observation)
    shelf_life = shelf_life_by_ingredient(observation)

    menu = choose_menu(observation, state, supplier_options, stock, pending)
    expected_covers = estimate_covers(observation, state)
    shares = dish_shares(observation, menu, state)
    stress = service_stress(observation)
    ingredient_forecast = forecast_ingredients(observation, menu, shares, state)
    ingredient_daily = {ingredient: values[0] for ingredient, values in ingredient_forecast.items()}

    staff_level = choose_staff_level(observation, expected_covers)
    inventory_days = estimate_inventory_days(menu, observation, total_stock, pending, ingredient_daily)
    marketing = choose_marketing(observation, expected_covers, stress, inventory_days)
    special = choose_special(observation, menu, supplier_options, total_stock, pending)

    actions: list[dict[str, Any]] = []
    if menu and _menu_changed(menu, observation.get("active_menu", [])):
        actions.append(tool_call("set_menu", dishes=menu))

    if staff_level != safe_int(observation.get("staff_level"), staff_level):
        actions.append(tool_call("set_staff_level", level=staff_level))

    actions.extend(price_actions(observation, menu, supplier_options, stress))
    actions.extend(order_actions(observation, menu, supplier_options, total_stock, pending, shelf_life, ingredient_forecast, staff_level, marketing))

    if marketing > 0:
        actions.append(tool_call("set_marketing_spend", amount=marketing))
    elif safe_float((observation.get("cost_breakdown") or {}).get("marketing")) > 0:
        actions.append(tool_call("set_marketing_spend", amount=0.0))

    if should_run_happy_hour(observation, stress, inventory_days, marketing):
        actions.append(tool_call("run_happy_hour"))
    if special:
        actions.append(tool_call("offer_daily_special", dish=special))

    next_state = update_state_after_plan(observation, state, menu, shares, ingredient_daily, expected_covers)
    actions.append(tool_call("save_notes", text=write_notes(next_state)))
    return _dedupe_actions(actions)


def price_actions(
    observation: dict[str, Any],
    menu: list[str],
    supplier_options: dict[str, list[dict[str, Any]]],
    stress: float,
) -> list[dict[str, Any]]:
    dishes = {str(dish.get("name")): dish for dish in observation.get("menu_book", [])}
    actions: list[dict[str, Any]] = []
    for name in menu:
        dish = dishes.get(name)
        if not dish:
            continue
        unit_cost = dish_unit_cost(dish, supplier_options)
        target_price = price_for_dish(dish, unit_cost, observation, stress)
        current_price = safe_float(dish.get("current_price"), safe_float(dish.get("base_price")))
        if abs(target_price - current_price) >= 0.03:
            actions.append(tool_call("set_price", dish=name, price=target_price))
    return actions


def forecast_ingredients(
    observation: dict[str, Any],
    menu: list[str],
    shares: dict[str, float],
    state: dict[str, Any],
    *,
    horizon_days: int = 9,
) -> dict[str, list[float]]:
    dishes = {str(dish.get("name")): dish for dish in observation.get("menu_book", [])}
    previous_daily = state.get("daily_ingredient_kg") if isinstance(state.get("daily_ingredient_kg"), dict) else {}
    forecast: dict[str, list[float]] = {}

    for offset in range(horizon_days):
        covers = estimate_covers(observation, state, offset=offset)
        for dish_name in menu:
            dish = dishes.get(dish_name)
            if not dish:
                continue
            dish_covers = covers * shares.get(dish_name, 1.0 / max(1, len(menu)))
            for ingredient, qty in recipe_ingredients(dish).items():
                value = dish_covers * qty
                if offset == 0 and ingredient in previous_daily:
                    value = 0.72 * value + 0.28 * safe_float(previous_daily.get(ingredient))
                forecast.setdefault(ingredient, [0.0] * horizon_days)
                forecast[ingredient][offset] += value

    return forecast


def order_actions(
    observation: dict[str, Any],
    menu: list[str],
    supplier_options: dict[str, list[dict[str, Any]]],
    stock: dict[str, float],
    pending: dict[str, float],
    shelf_life: dict[str, int],
    forecast: dict[str, list[float]],
    staff_level: int,
    marketing: float,
) -> list[dict[str, Any]]:
    del menu
    cash = safe_float(observation.get("cash"))
    reserve = _cash_reserve(cash, staff_level, marketing)
    budget = max(0.0, min(cash - reserve, cash * MAX_ORDER_BUDGET_FRACTION))
    if budget <= 0:
        return []

    stockout_ingredients = ingredients_from_stockout_dishes(observation)
    candidates: list[dict[str, Any]] = []
    current_day = safe_int(observation.get("day"), 1)
    weekend_window = _weekend_protection_window(str(observation.get("day_of_week", "")))

    for ingredient, daily_values in forecast.items():
        supplier = best_supplier(supplier_options, ingredient)
        if supplier is None:
            continue

        eta = max(1, safe_int(supplier.get("eta_days"), 1))
        life = max(1, shelf_life.get(ingredient, 7))
        unit_price = safe_float(supplier.get("price"))
        min_order = safe_float(supplier.get("min_order_kg"), 1.0)
        demand_today = daily_values[0] if daily_values else 0.0
        if demand_today <= 0:
            continue

        upper_target_days = max(5, min(10, life))
        lower_target_days = min(5, upper_target_days)
        target_days = int(clamp(eta + 5, lower_target_days, upper_target_days))
        protection_window = max(eta, weekend_window)
        demand_until_eta = sum(daily_values[: min(len(daily_values), eta + 1)])
        demand_until_protection = sum(daily_values[: min(len(daily_values), protection_window + 1)])
        demand_until_target = sum(daily_values[: min(len(daily_values), target_days)])
        pending_due_target = pending_due_by_ingredient(observation, through_day=current_day + target_days).get(ingredient, 0.0)
        inventory_position = stock.get(ingredient, 0.0) + pending_due_target
        all_pending = pending.get(ingredient, 0.0)

        eoq = eoq_piecewise(
            daily_values[: min(len(daily_values), target_days)],
            [1.0] * min(len(daily_values), target_days),
            unit_price,
            life,
        )

        stockout_multiplier = 1.35 if ingredient in stockout_ingredients else 1.0
        target_stock = max(demand_until_target * stockout_multiplier, eoq)
        max_reasonable = sum(daily_values[: min(len(daily_values), max(3, int(life * 0.95)))])
        target_stock = min(target_stock, max_reasonable * 1.08)

        need = target_stock - inventory_position
        critical_position = stock.get(ingredient, 0.0) + pending_due_by_ingredient(observation, through_day=current_day + protection_window).get(ingredient, 0.0)
        critical_threshold = demand_until_protection * (1.08 if weekend_window else 0.96)
        critical = critical_position < critical_threshold
        if need < min_order and not critical:
            continue

        quantity = max(min_order, need)
        if critical:
            quantity = max(quantity, min_order, demand_until_protection * 1.24 - critical_position)
        quantity = min(quantity, max_reasonable - stock.get(ingredient, 0.0) - all_pending + demand_today)
        quantity = round_kg(quantity)
        if quantity < min_order:
            quantity = round_kg(min_order)
        if quantity <= 0:
            continue

        cost = quantity * unit_price
        shortage_ratio = max(0.0, demand_until_protection - critical_position) / max(1.0, demand_until_protection)
        priority = shortage_ratio * 7.0 + (1.8 if critical else 0.0) + (1.7 if ingredient in stockout_ingredients else 0.0)
        priority += min(1.5, demand_today / 8.0)
        priority -= max(0.0, quantity - max_reasonable) * 0.03

        candidates.append({
            "priority": priority,
            "supplier": supplier,
            "ingredient": ingredient,
            "quantity": quantity,
            "cost": cost,
            "critical": critical,
        })

    candidates.sort(key=lambda item: (-item["priority"], item["ingredient"]))
    actions: list[dict[str, Any]] = []
    spent = 0.0
    ordered_ingredients: set[str] = set()
    for item in candidates:
        ingredient = item["ingredient"]
        if ingredient in ordered_ingredients:
            continue
        supplier = item["supplier"]
        quantity = safe_float(item["quantity"])
        cost = quantity * safe_float(supplier.get("price"))
        remaining = budget - spent
        min_order = safe_float(supplier.get("min_order_kg"), 1.0)
        if cost > remaining:
            affordable = round_kg(remaining / max(0.01, safe_float(supplier.get("price"))))
            if item["critical"] and affordable >= min_order:
                quantity = affordable
                cost = quantity * safe_float(supplier.get("price"))
            else:
                continue
        if quantity < min_order or cost <= 0:
            continue
        actions.append(tool_call(
            "place_order",
            supplier=supplier["supplier"],
            ingredient=ingredient,
            quantity_kg=quantity,
        ))
        spent += cost
        ordered_ingredients.add(ingredient)
    return actions


def estimate_inventory_days(
    menu: list[str],
    observation: dict[str, Any],
    stock: dict[str, float],
    pending: dict[str, float],
    ingredient_daily: dict[str, float],
) -> float:
    del menu, observation
    days: list[float] = []
    for ingredient, daily in ingredient_daily.items():
        if daily <= 0.01:
            continue
        days.append((stock.get(ingredient, 0.0) + pending.get(ingredient, 0.0)) / daily)
    if not days:
        return 0.0
    days.sort()
    return days[max(0, len(days) // 4)]


def ingredients_from_stockout_dishes(observation: dict[str, Any]) -> set[str]:
    service = observation.get("service_summary") or {}
    stockout_dishes = set((service.get("dishes_unavailable_at") or {}).keys())
    if not stockout_dishes:
        return set()
    dishes = {str(dish.get("name")): dish for dish in observation.get("menu_book", [])}
    ingredients: set[str] = set()
    for dish_name in stockout_dishes:
        dish = dishes.get(str(dish_name))
        if dish:
            ingredients.update(recipe_ingredients(dish).keys())
    return ingredients


def _cash_reserve(cash: float, staff_level: int, marketing: float) -> float:
    operating_floor = FIXED_DAILY_COST * 3.0 + STAFF_COST * staff_level * 2.0 + marketing
    if cash < 3500:
        return max(EMERGENCY_CASH_RESERVE, operating_floor)
    return max(MIN_CASH_RESERVE, operating_floor)


def _weekend_protection_window(day_of_week: str) -> int:
    if day_of_week == "Thursday":
        return 3
    if day_of_week == "Friday":
        return 2
    if day_of_week == "Saturday":
        return 1
    return 0


def _menu_changed(planned: list[Any], active: list[Any]) -> bool:
    planned_names = [str(item) for item in planned]
    active_names = [str(item) for item in active]
    return set(planned_names) != set(active_names)


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    ordered_ingredients: set[str] = set()
    last_by_singleton: dict[str, int] = {}
    singleton_tools = {"set_menu", "set_staff_level", "set_marketing_spend", "save_notes"}

    for action in actions:
        tool = action.get("tool")
        args = action.get("args") or {}
        if tool == "place_order":
            ingredient = args.get("ingredient")
            if ingredient in ordered_ingredients:
                continue
            ordered_ingredients.add(str(ingredient))
            result.append(action)
            continue
        if tool in singleton_tools:
            if tool in last_by_singleton:
                result[last_by_singleton[tool]] = action
            else:
                last_by_singleton[tool] = len(result)
                result.append(action)
            continue
        if tool == "set_price":
            key = (tool, args.get("dish"))
            for index in range(len(result) - 1, -1, -1):
                existing = result[index]
                if existing.get("tool") == key[0] and (existing.get("args") or {}).get("dish") == key[1]:
                    result[index] = action
                    break
            else:
                result.append(action)
            continue
        result.append(action)
    return result
