"""Deterministic rule layer for the RestBench agent.

The rules are the reliable fallback: they make complete daily decisions without
needing a model call. The LLM layer can add bounded adjustments on top.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from agents.my_agent_config import (
    BASE_COVERS_BY_DAY,
    BUSY_DAYS,
    REPUTATION_PRICE_MULTIPLIER,
    SLOW_DAYS,
    TREND_DEMAND,
    WALKOUT_PRESSURE,
    WEATHER_DEMAND,
)
from agents.my_agent_optimizer import optimize_order_candidates
from agents.my_agent_utils import (
    active_from_book,
    best_supplier_for_ingredient,
    cheapest_supplier_by_ingredient,
    days_until_delivery,
    estimated_margin,
    has_scenario_flag,
    make_notes,
    pending_by_ingredient,
    round_order_qty,
    same_items,
    servings_available,
    stock_by_ingredient,
    stockout_ingredients,
)


def strategy(observation: dict[str, Any], day: int) -> list[dict[str, Any]]:
    """Compatibility entrypoint used by the evaluator if imported directly."""
    return build_rule_actions(observation, day)


def build_rule_actions(
    observation: dict[str, Any],
    day: int,
    *,
    include_notes: bool = True,
    llm_used: bool = False,
) -> list[dict[str, Any]]:
    """Return the deterministic baseline actions for today."""
    actions: list[dict[str, Any]] = []

    menu_book = {dish["name"]: dish for dish in observation.get("menu_book", [])}
    active_menu = _choose_planned_menu(observation, menu_book)
    active_menu = _choose_safe_menu(observation, menu_book, active_menu)

    if not same_items(active_menu, observation.get("active_menu", [])) and len(active_menu) >= 5:
        actions.append({"tool": "set_menu", "args": {"dishes": active_menu}})

    staff_level = _choose_staff_level(observation)
    if staff_level != observation.get("staff_level"):
        actions.append({"tool": "set_staff_level", "args": {"level": staff_level}})

    marketing_spend = _choose_marketing_spend(observation, staff_level)
    actions.append({"tool": "set_marketing_spend", "args": {"amount": marketing_spend}})

    actions.extend(_price_actions(observation, menu_book, active_menu))

    if _should_run_happy_hour(observation):
        actions.append({"tool": "run_happy_hour", "args": {}})

    special = _choose_daily_special(observation, menu_book, active_menu)
    if special:
        actions.append({"tool": "offer_daily_special", "args": {"dish": special}})

    actions.extend(_order_actions(observation, menu_book, active_menu, staff_level, marketing_spend))

    if include_notes:
        actions.append({
            "tool": "save_notes",
            "args": {"text": make_notes(observation, staff_level, marketing_spend, llm_used=llm_used)},
        })

    return actions


def _choose_staff_level(observation: dict[str, Any]) -> int:
    dow = observation.get("day_of_week", "")
    weather = observation.get("weather_today", "cloudy")
    trend = observation.get("customer_trend", "Stable")
    reputation = observation.get("reputation_band", "Very Good")
    service = observation.get("service_summary") or {}

    if _is_renovation_capacity_limited(observation):
        if dow in {"Friday", "Saturday", "Sunday"}:
            return 6
        return 5
    if has_scenario_flag(observation, "renovation"):
        if dow == "Saturday":
            return 8
        if dow in {"Friday", "Sunday"}:
            return 7
        return 6

    if dow == "Saturday":
        level = 9
    elif dow == "Friday":
        level = 8
    elif dow == "Sunday":
        level = 7
    else:
        level = 6

    if weather == "sunny" and dow in BUSY_DAYS:
        level += 1
    if trend == "Growing":
        level += 1
    if reputation in {"Poor", "Fair"}:
        level += 1

    walkouts = WALKOUT_PRESSURE.get(service.get("walkout_band", "None"), 0)
    avg_wait = float(service.get("avg_wait_minutes") or 0)
    peak_wait = float(service.get("peak_wait_minutes") or 0)
    bottlenecks = len(service.get("kitchen_bottleneck_hours") or [])

    if walkouts >= 2 or avg_wait > 8 or peak_wait > 20 or bottlenecks >= 2:
        level += 1
    if walkouts >= 3 or avg_wait > 12:
        level += 1

    covers = int(service.get("total_covers") or 0)
    if covers and covers < 65 and walkouts == 0 and trend != "Growing":
        level -= 1

    cash = float(observation.get("cash", 0))
    if cash < 4_000 and walkouts <= 1:
        level -= 1
    if cash < 2_500:
        level -= 1

    return max(5, min(11, level))


def _choose_marketing_spend(observation: dict[str, Any], staff_level: int) -> int:
    cash = float(observation.get("cash", 0))
    if cash < 3_000:
        return 0
    if has_scenario_flag(observation, "renovation"):
        return 0

    dow = observation.get("day_of_week", "")
    trend = observation.get("customer_trend", "Stable")
    reputation = observation.get("reputation_band", "Very Good")
    service = observation.get("service_summary") or {}
    walkouts = WALKOUT_PRESSURE.get(service.get("walkout_band", "None"), 0)

    if walkouts >= 2 or staff_level <= 5:
        return 0
    if reputation in {"Poor", "Fair"}:
        return 60
    if trend == "Declining":
        return 100
    if dow in BUSY_DAYS and cash > 6_000:
        return 120
    if dow == "Sunday" and cash > 6_000:
        return 80
    return 0


def _price_actions(
    observation: dict[str, Any],
    menu_book: dict[str, dict[str, Any]],
    active_menu: list[str],
) -> list[dict[str, Any]]:
    reputation = observation.get("reputation_band", "Very Good")
    service = observation.get("service_summary") or {}
    walkouts = WALKOUT_PRESSURE.get(service.get("walkout_band", "None"), 0)
    stockouts = bool(service.get("dishes_unavailable_at") or {})

    if _is_renovation_capacity_limited(observation):
        multiplier = 1.20
    else:
        multiplier = REPUTATION_PRICE_MULTIPLIER.get(reputation, 1.0)
    if walkouts >= 2 or stockouts:
        multiplier = min(multiplier, 1.00) if not _is_renovation_capacity_limited(observation) else multiplier

    actions: list[dict[str, Any]] = []
    for dish_name in active_menu:
        dish = menu_book.get(dish_name)
        if not dish:
            continue
        base_price = float(dish.get("base_price", 0))
        current_price = float(dish.get("current_price", base_price))
        target_price = round(base_price * multiplier, 2)
        target_price = max(round(base_price * 0.8, 2), min(round(base_price * 1.2, 2), target_price))

        if abs(target_price - current_price) >= 0.05:
            actions.append({"tool": "set_price", "args": {"dish": dish_name, "price": target_price}})

    return actions


def _should_run_happy_hour(observation: dict[str, Any]) -> bool:
    cash = float(observation.get("cash", 0))
    if cash < 3_500:
        return False
    if has_scenario_flag(observation, "renovation"):
        return False

    dow = observation.get("day_of_week", "")
    trend = observation.get("customer_trend", "Stable")
    service = observation.get("service_summary") or {}

    if service.get("dishes_unavailable_at"):
        return False
    if WALKOUT_PRESSURE.get(service.get("walkout_band", "None"), 0) >= 2:
        return False
    if dow in SLOW_DAYS:
        return True
    return trend == "Declining" and dow not in BUSY_DAYS


def _choose_daily_special(
    observation: dict[str, Any],
    menu_book: dict[str, dict[str, Any]],
    active_menu: list[str],
) -> str | None:
    cheapest = cheapest_supplier_by_ingredient(observation)
    stock = stock_by_ingredient(observation, min_expires_in_days=1)
    pending = pending_by_ingredient(observation)

    best_name = None
    best_score = float("-inf")
    for dish_name in active_menu:
        dish = menu_book.get(dish_name)
        if not dish:
            continue

        available = servings_available(dish, stock, pending)
        if available < 12:
            continue

        margin = estimated_margin(dish, cheapest)
        score = margin + min(available, 50) * 0.05
        if score > best_score:
            best_name = dish_name
            best_score = score

    return best_name or (active_menu[0] if active_menu else None)


def _choose_safe_menu(
    observation: dict[str, Any],
    menu_book: dict[str, dict[str, Any]],
    active_menu: list[str],
) -> list[str]:
    if len(active_menu) < 5:
        return active_menu

    service = observation.get("service_summary") or {}
    stockout_dishes = set((service.get("dishes_unavailable_at") or {}).keys())
    if not stockout_dishes:
        return active_menu

    stock = stock_by_ingredient(observation, min_expires_in_days=1)
    pending = pending_by_ingredient(observation)

    safe: list[str] = []
    for dish_name in active_menu:
        dish = menu_book.get(dish_name)
        if not dish:
            continue
        available = servings_available(dish, stock, pending)
        if dish_name not in stockout_dishes or available >= 10:
            safe.append(dish_name)

    if len(safe) >= 5:
        return safe
    return active_menu


def _choose_planned_menu(
    observation: dict[str, Any],
    menu_book: dict[str, dict[str, Any]],
) -> list[str]:
    if has_scenario_flag(observation, "renovation"):
        preferred = [
            "Pizza Margherita",
            "Chicken Parmesan",
            "Chicken Caesar Salad",
            "Mushroom Risotto",
            "Spaghetti Carbonara",
        ]
        return [dish for dish in preferred if dish in menu_book]

    return list(observation.get("active_menu") or active_from_book(menu_book))


def _is_renovation_capacity_limited(observation: dict[str, Any]) -> bool:
    day = int(observation.get("day") or 1)
    return day <= 14 and has_scenario_flag(observation, "renovation")


def _order_actions(
    observation: dict[str, Any],
    menu_book: dict[str, dict[str, Any]],
    active_menu: list[str],
    staff_level: int,
    marketing_spend: int,
) -> list[dict[str, Any]]:
    daily_need = _project_daily_ingredient_need(observation, menu_book, active_menu)
    if not daily_need:
        return []

    inventory_fresh = stock_by_ingredient(observation, min_expires_in_days=1)
    pending = pending_by_ingredient(observation)
    suppliers = observation.get("supplier_catalog", [])
    shelf_life = {
        item["ingredient"]: float(item.get("shelf_life_days") or 4)
        for item in observation.get("inventory", [])
    }
    stockout_names = stockout_ingredients(observation, menu_book)

    cash = float(observation.get("cash", 0))
    staff_cost = float(observation.get("staff_cost_per_person") or 120)
    daily_overhead = 300 + staff_level * staff_cost + marketing_spend
    reserve = max(2_000, daily_overhead * 2.5)
    if cash < 5_000:
        reserve = max(reserve, daily_overhead * 3.5)

    budget = max(0.0, cash - reserve)
    if budget <= 0:
        return []

    order_candidates = []
    fallback_candidates = []
    for ingredient, need_per_day in daily_need.items():
        if need_per_day <= 0:
            continue

        current = inventory_fresh.get(ingredient, 0.0)
        incoming = pending.get(ingredient, 0.0)
        effective = current + incoming
        coverage_days = effective / need_per_day if need_per_day else 99

        freshness_cap = max(2.0, min(float(shelf_life.get(ingredient, 4)), 5.0))
        preferred_supplier = best_supplier_for_ingredient(observation, suppliers, ingredient)
        if not preferred_supplier:
            continue

        preferred = _build_order_candidate(
            observation,
            ingredient,
            preferred_supplier,
            need_per_day,
            effective,
            coverage_days,
            freshness_cap,
            stockout_names,
        )
        if preferred is None:
            continue

        fallback_candidates.append(preferred)
        order_candidates.append(preferred)

        if preferred["urgent"] or preferred["coverage_days"] < 2.5:
            for supplier in suppliers:
                if supplier["name"] == preferred_supplier["name"]:
                    continue
                if ingredient not in supplier.get("ingredients", {}):
                    continue
                alternate = _build_order_candidate(
                    observation,
                    ingredient,
                    supplier,
                    need_per_day,
                    effective,
                    coverage_days,
                    freshness_cap,
                    stockout_names,
                )
                if alternate is None:
                    continue
                if alternate["eta_days"] <= preferred["eta_days"] or alternate["cost"] <= preferred["cost"] * 0.9:
                    order_candidates.append(alternate)

    order_candidates.sort(key=lambda item: (not item["urgent"], item["coverage_days"], item["cost"]))
    optimized = None
    if not has_scenario_flag(observation, "supply"):
        optimized = optimize_order_candidates(order_candidates, budget)
    if optimized is not None:
        order_candidates = optimized
    else:
        order_candidates = sorted(
            fallback_candidates,
            key=lambda item: (not item["urgent"], item["coverage_days"], item["cost"]),
        )

    actions: list[dict[str, Any]] = []
    spent = 0.0
    for item in order_candidates:
        if spent + item["cost"] > budget:
            continue
        actions.append({
            "tool": "place_order",
            "args": {
                "supplier": item["supplier"],
                "ingredient": item["ingredient"],
                "quantity_kg": item["qty"],
            },
        })
        spent += item["cost"]

    return actions


def _build_order_candidate(
    observation: dict[str, Any],
    ingredient: str,
    supplier: dict[str, Any],
    need_per_day: float,
    effective_kg: float,
    coverage_days: float,
    freshness_cap: float,
    stockout_names: set[str],
) -> dict[str, Any] | None:
    eta_days = days_until_delivery(supplier, observation.get("day_of_week", "Monday"))
    target_days = min(max(eta_days + 2.0, 3.0), freshness_cap)
    if ingredient in stockout_names:
        target_days += 1.0

    target_kg = need_per_day * target_days
    if effective_kg >= target_kg:
        return None

    min_order = float(supplier.get("min_order_kg") or 1.0)
    qty = round_order_qty(max(min_order, target_kg - effective_kg))
    price = float(supplier["ingredients"][ingredient])
    urgent = ingredient in stockout_names or coverage_days < max(1.5, eta_days)
    return {
        "ingredient": ingredient,
        "supplier": supplier["name"],
        "qty": qty,
        "cost": qty * price,
        "coverage_days": coverage_days,
        "target_days": target_days,
        "eta_days": eta_days,
        "need_per_day": need_per_day,
        "urgent": urgent,
        "stockout": ingredient in stockout_names,
    }


def _project_daily_ingredient_need(
    observation: dict[str, Any],
    menu_book: dict[str, dict[str, Any]],
    active_menu: list[str],
) -> dict[str, float]:
    portions = _project_daily_portions(observation, active_menu)
    need: dict[str, float] = defaultdict(float)

    for dish_name, projected_portions in portions.items():
        dish = menu_book.get(dish_name)
        if not dish:
            continue
        for ingredient in dish.get("ingredients", []):
            need[ingredient["ingredient"]] += projected_portions * float(ingredient["quantity_kg"])

    if has_scenario_flag(observation, "renovation"):
        return {ingredient: qty * 1.35 for ingredient, qty in need.items()}
    return dict(need)


def _project_daily_portions(observation: dict[str, Any], active_menu: list[str]) -> dict[str, float]:
    if not active_menu:
        return {}

    service = observation.get("service_summary") or {}
    sold = {
        dish: float(qty)
        for dish, qty in (service.get("dishes_sold") or {}).items()
        if dish in active_menu
    }
    stockouts = set((service.get("dishes_unavailable_at") or {}).keys())
    for dish in stockouts:
        if dish in active_menu:
            sold[dish] = sold.get(dish, 0.0) + 6.0

    sold_total = sum(sold.values())
    expected_covers = expected_covers_for_day(observation)

    if sold_total >= 10:
        smoothed_total = sold_total + len(active_menu)
        return {
            dish: max(4.0, expected_covers * ((sold.get(dish, 0.0) + 1.0) / smoothed_total))
            for dish in active_menu
        }

    even_share = expected_covers / len(active_menu)
    return {dish: max(6.0, even_share) for dish in active_menu}


def expected_covers_for_day(observation: dict[str, Any]) -> float:
    dow = observation.get("day_of_week", "Monday")
    base = BASE_COVERS_BY_DAY.get(dow, 100)
    weather = WEATHER_DEMAND.get(observation.get("weather_today", "cloudy"), 1.0)
    trend = TREND_DEMAND.get(observation.get("customer_trend", "Stable"), 1.0)
    reputation = observation.get("reputation_band", "Very Good")

    reputation_factor = {
        "Poor": 0.70,
        "Fair": 0.84,
        "Good": 0.95,
        "Very Good": 1.00,
        "Excellent": 1.08,
    }.get(reputation, 1.0)

    service = observation.get("service_summary") or {}
    yesterday = float(service.get("total_covers") or 0)
    estimate = base * weather * trend * reputation_factor

    if yesterday >= 20:
        estimate = max(estimate, yesterday * 0.85)
        estimate = min(estimate, yesterday * 1.35)

    if has_scenario_flag(observation, "renovation"):
        estimate = max(estimate, 115.0)

    return max(55.0, min(170.0, estimate))
