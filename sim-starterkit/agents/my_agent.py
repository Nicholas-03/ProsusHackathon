"""First testable RestBench agent.

This is intentionally rule-based: it is cheap to run, deterministic, and easy to
debug before adding any LLM loop. The strategy focuses on survival first:
reasonable staffing, broad menu variety, no obvious stockouts, and controlled
promotions.
"""

from __future__ import annotations

import os
from collections import defaultdict
from math import ceil
from typing import Any

from agents.runner import run_game


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

BASE_COVERS_BY_DAY = {
    "Monday": 84,
    "Tuesday": 88,
    "Wednesday": 94,
    "Thursday": 108,
    "Friday": 130,
    "Saturday": 142,
    "Sunday": 116,
}

WEATHER_DEMAND = {
    "sunny": 1.06,
    "cloudy": 1.00,
    "rainy": 0.92,
    "stormy": 0.78,
}

TREND_DEMAND = {
    "Declining": 0.88,
    "Stable": 1.00,
    "Growing": 1.12,
}

REPUTATION_PRICE_MULTIPLIER = {
    "Poor": 0.92,
    "Fair": 0.96,
    "Good": 1.00,
    "Very Good": 1.05,
    "Excellent": 1.08,
}

WALKOUT_PRESSURE = {
    "None": 0,
    "Few": 1,
    "Some": 2,
    "Many": 3,
}

SLOW_DAYS = {"Monday", "Tuesday", "Wednesday"}
BUSY_DAYS = {"Friday", "Saturday"}


def strategy(observation: dict[str, Any], day: int) -> list[dict[str, Any]]:
    """Return today's tool calls."""
    actions: list[dict[str, Any]] = []

    menu_book = {dish["name"]: dish for dish in observation.get("menu_book", [])}
    active_menu = list(observation.get("active_menu") or _active_from_book(menu_book))
    active_menu = _choose_safe_menu(observation, menu_book, active_menu)

    if _same_items(active_menu, observation.get("active_menu", [])) is False and len(active_menu) >= 5:
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

    actions.append({"tool": "save_notes", "args": {"text": _make_notes(observation, staff_level, marketing_spend)}})

    return actions


def _active_from_book(menu_book: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name, dish in menu_book.items() if dish.get("is_active")]


def _same_items(left: list[str], right: list[str]) -> bool:
    return set(left) == set(right) and len(left) == len(right)


def _choose_staff_level(observation: dict[str, Any]) -> int:
    dow = observation.get("day_of_week", "")
    weather = observation.get("weather_today", "cloudy")
    trend = observation.get("customer_trend", "Stable")
    reputation = observation.get("reputation_band", "Very Good")
    service = observation.get("service_summary") or {}

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

    multiplier = REPUTATION_PRICE_MULTIPLIER.get(reputation, 1.0)
    if walkouts >= 2 or stockouts:
        multiplier = min(multiplier, 1.00)

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
    cheapest = _cheapest_supplier_by_ingredient(observation)
    stock = _stock_by_ingredient(observation, min_expires_in_days=1)
    pending = _pending_by_ingredient(observation)

    best_name = None
    best_score = float("-inf")
    for dish_name in active_menu:
        dish = menu_book.get(dish_name)
        if not dish:
            continue

        servings_available = _servings_available(dish, stock, pending)
        if servings_available < 12:
            continue

        margin = _estimated_margin(dish, cheapest)
        score = margin + min(servings_available, 50) * 0.05
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

    stock = _stock_by_ingredient(observation, min_expires_in_days=1)
    pending = _pending_by_ingredient(observation)

    safe: list[str] = []
    for dish_name in active_menu:
        dish = menu_book.get(dish_name)
        if not dish:
            continue
        servings_available = _servings_available(dish, stock, pending)
        if dish_name not in stockout_dishes or servings_available >= 10:
            safe.append(dish_name)

    if len(safe) >= 5:
        return safe
    return active_menu


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

    inventory_fresh = _stock_by_ingredient(observation, min_expires_in_days=1)
    pending = _pending_by_ingredient(observation)
    suppliers = observation.get("supplier_catalog", [])
    shelf_life = {
        item["ingredient"]: float(item.get("shelf_life_days") or 4)
        for item in observation.get("inventory", [])
    }
    stockout_ingredients = _stockout_ingredients(observation, menu_book)

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
    for ingredient, need_per_day in daily_need.items():
        if need_per_day <= 0:
            continue

        supplier = _best_supplier_for_ingredient(observation, suppliers, ingredient)
        if not supplier:
            continue

        eta_days = _days_until_delivery(supplier, observation.get("day_of_week", "Monday"))
        current = inventory_fresh.get(ingredient, 0.0)
        incoming = pending.get(ingredient, 0.0)
        effective = current + incoming
        coverage_days = effective / need_per_day if need_per_day else 99

        freshness_cap = max(2.0, min(float(shelf_life.get(ingredient, 4)), 5.0))
        target_days = min(max(eta_days + 2.0, 3.0), freshness_cap)
        if ingredient in stockout_ingredients:
            target_days += 1.0

        target_kg = need_per_day * target_days
        if effective >= target_kg:
            continue

        min_order = float(supplier.get("min_order_kg") or 1.0)
        qty = max(min_order, target_kg - effective)
        qty = _round_order_qty(qty)

        price = float(supplier["ingredients"][ingredient])
        cost = qty * price
        urgent = ingredient in stockout_ingredients or coverage_days < max(1.5, eta_days)
        order_candidates.append({
            "ingredient": ingredient,
            "supplier": supplier["name"],
            "qty": qty,
            "cost": cost,
            "coverage_days": coverage_days,
            "urgent": urgent,
        })

    order_candidates.sort(key=lambda item: (not item["urgent"], item["coverage_days"], item["cost"]))

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
    expected_covers = _expected_covers(observation)

    if sold_total >= 10:
        smoothed_total = sold_total + len(active_menu)
        return {
            dish: max(4.0, expected_covers * ((sold.get(dish, 0.0) + 1.0) / smoothed_total))
            for dish in active_menu
        }

    even_share = expected_covers / len(active_menu)
    return {dish: max(6.0, even_share) for dish in active_menu}


def _expected_covers(observation: dict[str, Any]) -> float:
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

    return max(55.0, min(170.0, estimate))


def _best_supplier_for_ingredient(
    observation: dict[str, Any],
    suppliers: list[dict[str, Any]],
    ingredient: str,
) -> dict[str, Any] | None:
    candidates = [supplier for supplier in suppliers if ingredient in supplier.get("ingredients", {})]
    if not candidates:
        return None

    current_dow = observation.get("day_of_week", "Monday")
    reliability = _supplier_reliability(observation)
    blocked_suppliers = _suppliers_in_alerts(observation)

    def score(supplier: dict[str, Any]) -> tuple[float, float]:
        name = supplier["name"]
        price = float(supplier["ingredients"][ingredient])
        eta = _days_until_delivery(supplier, current_dow)
        reliability_penalty = 1.0 + (1.0 - reliability.get(name, 1.0)) * 0.35
        alert_penalty = 25.0 if name in blocked_suppliers else 0.0
        return (price * reliability_penalty + eta * 0.12 + alert_penalty, eta)

    return min(candidates, key=score)


def _supplier_reliability(observation: dict[str, Any]) -> dict[str, float]:
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


def _suppliers_in_alerts(observation: dict[str, Any]) -> set[str]:
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


def _days_until_delivery(supplier: dict[str, Any], current_day_of_week: str) -> int:
    delivery_days = set(supplier.get("delivery_days") or [])
    lead_time = int(supplier.get("lead_time_days") or 1)
    current_idx = WEEKDAYS.index(current_day_of_week) if current_day_of_week in WEEKDAYS else 0

    for offset in range(max(1, lead_time), 15):
        candidate_day = WEEKDAYS[(current_idx + offset) % 7]
        if candidate_day in delivery_days:
            return offset
    return lead_time + 7


def _stock_by_ingredient(observation: dict[str, Any], min_expires_in_days: int = 0) -> dict[str, float]:
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


def _pending_by_ingredient(observation: dict[str, Any]) -> dict[str, float]:
    pending: dict[str, float] = defaultdict(float)
    for order in observation.get("pending_orders", []):
        pending[order["ingredient"]] += float(order.get("quantity_kg") or 0)
    return dict(pending)


def _cheapest_supplier_by_ingredient(observation: dict[str, Any]) -> dict[str, float]:
    cheapest: dict[str, float] = {}
    for supplier in observation.get("supplier_catalog", []):
        for ingredient, price in supplier.get("ingredients", {}).items():
            if ingredient not in cheapest or float(price) < cheapest[ingredient]:
                cheapest[ingredient] = float(price)
    return cheapest


def _servings_available(
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


def _estimated_margin(dish: dict[str, Any], ingredient_prices: dict[str, float]) -> float:
    ingredient_cost = 0.0
    for ingredient in dish.get("ingredients", []):
        name = ingredient["ingredient"]
        ingredient_cost += ingredient_prices.get(name, 0.0) * float(ingredient["quantity_kg"])
    return float(dish.get("base_price") or 0) - ingredient_cost


def _stockout_ingredients(
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


def _round_order_qty(qty: float) -> float:
    return round(ceil(qty * 2) / 2, 1)


def _make_notes(observation: dict[str, Any], staff_level: int, marketing_spend: int) -> str:
    service = observation.get("service_summary") or {}
    stockouts = service.get("dishes_unavailable_at") or {}
    return (
        f"Day {observation.get('day')}: cash={float(observation.get('cash', 0)):.0f}; "
        f"staff={staff_level}; marketing={marketing_spend}; "
        f"covers_yday={service.get('total_covers', 0)}; "
        f"walkouts={service.get('walkout_band', 'n/a')}; "
        f"stockouts={','.join(stockouts.keys()) if stockouts else 'none'}"
    )


if __name__ == "__main__":
    run_game(strategy, team_name=os.getenv("RESTBENCH_TEAM_NAME", "la-forchetta-intelligente"), seed=42)
