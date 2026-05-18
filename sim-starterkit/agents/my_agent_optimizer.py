"""Deterministic menu, price, staff, and promotion choices."""

from __future__ import annotations

from typing import Any

from agents.my_agent_config import (
    DEFAULT_COVERS,
    MAX_EXPECTED_COVERS,
    MENU_MIN_SIZE,
    MENU_TARGET_SIZE,
    MIN_EXPECTED_COVERS,
    PRICE_MAX_MULTIPLIER,
    PRICE_MIN_MULTIPLIER,
    STAFF_MAX,
    STAFF_MIN,
    WEEKDAYS,
)
from agents.my_agent_inventory import dish_unit_cost, recipe_ingredients, servings_for_dish
from agents.my_agent_utils import clamp, safe_float, safe_int


DAY_MULTIPLIER = {
    "Monday": 0.88,
    "Tuesday": 0.92,
    "Wednesday": 0.96,
    "Thursday": 1.08,
    "Friday": 1.26,
    "Saturday": 1.58,
    "Sunday": 1.24,
}
WEATHER_MULTIPLIER = {
    "sunny": 1.06,
    "cloudy": 1.00,
    "rainy": 0.91,
    "stormy": 0.78,
}
TREND_MULTIPLIER = {
    "Declining": 0.90,
    "Stable": 1.00,
    "Growing": 1.09,
}
REPUTATION_MULTIPLIER = {
    "Poor": 0.72,
    "Fair": 0.84,
    "Good": 0.94,
    "Very Good": 1.00,
    "Excellent": 1.08,
}


def choose_menu(
    observation: dict[str, Any],
    state: dict[str, Any],
    supplier_options: dict[str, list[dict[str, Any]]],
    stock: dict[str, float],
    pending: dict[str, float],
) -> list[str]:
    menu_book = observation.get("menu_book", [])
    previous_menu = [name for name in state.get("menu", []) if isinstance(name, str)]
    current_active = [name for name in observation.get("active_menu", []) if isinstance(name, str)]
    alerts_text = " ".join(str(alert) for alert in observation.get("alerts", [])).lower()
    score_rows: list[tuple[float, str, str]] = []

    for dish in menu_book:
        name = str(dish.get("name", ""))
        if not name:
            continue
        unit_cost = dish_unit_cost(dish, supplier_options)
        score = dish_score(dish, unit_cost, stock, pending, previous_menu, current_active, alerts_text)
        category = str(dish.get("category", "Other"))
        score_rows.append((score, name, category))

    score_rows.sort(key=lambda row: (-row[0], row[1]))
    if not score_rows:
        return current_active[:]

    target_size = min(max(MENU_MIN_SIZE, MENU_TARGET_SIZE), len(score_rows))
    selected: list[str] = []
    used_categories: set[str] = set()

    for score, name, category in score_rows:
        if len(selected) >= min(target_size, 5):
            break
        if category in used_categories and len(used_categories) < 5:
            continue
        selected.append(name)
        used_categories.add(category)

    for score, name, category in score_rows:
        if len(selected) >= target_size:
            break
        if name not in selected:
            selected.append(name)

    if len(selected) < MENU_MIN_SIZE:
        for _, name, _ in score_rows:
            if name not in selected:
                selected.append(name)
            if len(selected) >= MENU_MIN_SIZE:
                break

    selected = selected[:target_size]
    selected_set = set(selected)

    # Menu changes are expensive in the simulation because the kitchen has a
    # learning curve. Preserve the current order when the chosen dish set is
    # unchanged, and prefer the persisted order if the API already drifted.
    if len(current_active) >= MENU_MIN_SIZE and set(current_active) == selected_set:
        return current_active
    if len(previous_menu) >= MENU_MIN_SIZE and set(previous_menu) == selected_set:
        return previous_menu
    return selected


def dish_score(
    dish: dict[str, Any],
    unit_cost: float,
    stock: dict[str, float],
    pending: dict[str, float],
    previous_menu: list[str],
    current_active: list[str],
    alerts_text: str,
) -> float:
    name = str(dish.get("name", ""))
    base_price = safe_float(dish.get("base_price"))
    if unit_cost == float("inf") or base_price <= 0:
        return -10_000.0

    ingredients = recipe_ingredients(dish)
    gross_margin = base_price - unit_cost
    margin_ratio = gross_margin / base_price
    servings = servings_for_dish(dish, stock, pending)
    complexity_penalty = 0.22 * max(0, len(ingredients) - 3)
    supply_penalty = sum(0.45 for ingredient in ingredients if stock.get(ingredient, 0.0) + pending.get(ingredient, 0.0) <= 0.01)
    stock_bonus = min(1.6, servings / 70.0)
    stability_bonus = 1.05 if name in previous_menu else 0.0
    active_bonus = 0.55 if name in current_active else 0.0
    alert_penalty = _dish_alert_penalty(name, ingredients, alerts_text)

    return gross_margin * 0.42 + margin_ratio * 8.0 + stock_bonus + stability_bonus + active_bonus - complexity_penalty - supply_penalty - alert_penalty


def estimate_covers(observation: dict[str, Any], state: dict[str, Any], *, offset: int = 0) -> float:
    service = observation.get("service_summary") or {}
    yesterday_covers = safe_float(service.get("total_covers"))
    previous_ema = safe_float(state.get("covers_ema"), DEFAULT_COVERS)
    if yesterday_covers > 0:
        base = 0.62 * yesterday_covers + 0.38 * previous_ema
    else:
        base = previous_ema or DEFAULT_COVERS

    weekday = _weekday_at(observation.get("day_of_week", "Monday"), offset)
    weather = _weather_at(observation, offset)
    multiplier = DAY_MULTIPLIER.get(weekday, 1.0)
    multiplier *= WEATHER_MULTIPLIER.get(str(weather).lower(), 1.0)
    multiplier *= TREND_MULTIPLIER.get(str(observation.get("customer_trend", "Stable")), 1.0)
    multiplier *= REPUTATION_MULTIPLIER.get(str(observation.get("reputation_band", "Very Good")), 1.0)
    multiplier *= _scenario_multiplier(observation)

    walkout = str(service.get("walkout_band", "None"))
    if walkout == "Some":
        multiplier *= 1.08
    elif walkout == "Many":
        multiplier *= 1.18
    if service.get("dishes_unavailable_at"):
        multiplier *= 1.06

    return clamp(base * multiplier, MIN_EXPECTED_COVERS, MAX_EXPECTED_COVERS)


def dish_shares(observation: dict[str, Any], menu: list[str], state: dict[str, Any]) -> dict[str, float]:
    if not menu:
        return {}
    service = observation.get("service_summary") or {}
    sold = service.get("dishes_sold") or {}
    stockouts = service.get("dishes_unavailable_at") or {}
    previous = state.get("dish_share") if isinstance(state.get("dish_share"), dict) else {}
    raw: dict[str, float] = {}

    for dish in menu:
        prior = safe_float(previous.get(dish), 1.0 / len(menu))
        count = safe_float(sold.get(dish))
        stockout_boost = 4.0 if dish in stockouts else 0.0
        raw[dish] = 1.0 + 0.55 * count + 18.0 * prior + stockout_boost

    total = sum(raw.values())
    if total <= 0:
        return {dish: 1.0 / len(menu) for dish in menu}
    return {dish: value / total for dish, value in raw.items()}


def choose_staff_level(observation: dict[str, Any], expected_covers: float) -> int:
    service = observation.get("service_summary") or {}
    walkout = str(service.get("walkout_band", "None"))
    avg_wait = safe_float(service.get("avg_wait_minutes"))
    peak_wait = safe_float(service.get("peak_wait_minutes"))
    bottlenecks = service.get("kitchen_bottleneck_hours") or []
    cash = safe_float(observation.get("cash"))

    target = round(expected_covers / 13.5 + 1.0)
    if walkout == "Few":
        target += 1
    elif walkout == "Some":
        target += 2
    elif walkout == "Many":
        target += 3
    if avg_wait > 8 or peak_wait > 22:
        target += 1
    if bottlenecks:
        target += 1
    if str(observation.get("day_of_week")) in {"Friday", "Saturday"}:
        target += 1
    if cash < 3500 and walkout in {"None", "Few"}:
        target -= 1
    if cash < 2200:
        target = min(target, 7)
    return int(clamp(target, STAFF_MIN, STAFF_MAX))


def price_for_dish(
    dish: dict[str, Any],
    unit_cost: float,
    observation: dict[str, Any],
    service_stress: float,
) -> float:
    base_price = safe_float(dish.get("base_price"))
    if base_price <= 0:
        return 0.0

    margin_ratio = (base_price - unit_cost) / base_price if unit_cost != float("inf") else 0.0
    multiplier = 1.04
    if margin_ratio < 0.42:
        multiplier += 0.06
    elif margin_ratio > 0.68:
        multiplier += 0.02

    reputation = str(observation.get("reputation_band", "Very Good"))
    trend = str(observation.get("customer_trend", "Stable"))
    if reputation in {"Poor", "Fair"}:
        multiplier -= 0.06
    elif reputation == "Excellent" and trend == "Growing":
        multiplier += 0.04
    if service_stress >= 2.0:
        multiplier -= 0.03
    if safe_float(observation.get("cash")) < 2500:
        multiplier += 0.03
    lower = base_price * PRICE_MIN_MULTIPLIER
    upper = base_price * PRICE_MAX_MULTIPLIER
    return round(clamp(base_price * multiplier, lower, upper), 2)


def choose_marketing(observation: dict[str, Any], expected_covers: float, service_stress: float, inventory_days: float) -> float:
    cash = safe_float(observation.get("cash"))
    day = safe_int(observation.get("day"), 1)
    if day <= 6:
        return 0.0
    if cash < 4200 or inventory_days < 3.0 or service_stress >= 1.6:
        return 0.0
    weekday = str(observation.get("day_of_week", ""))
    trend = str(observation.get("customer_trend", "Stable"))
    reputation = str(observation.get("reputation_band", "Very Good"))

    amount = 0.0
    if trend == "Declining" or reputation in {"Fair", "Poor"}:
        amount = 90.0
    elif weekday in {"Thursday", "Friday", "Saturday"} and expected_covers < 145:
        amount = 70.0
    elif cash > 10_000 and expected_covers < 125:
        amount = 45.0

    if _alerts_contain(observation, ("tourist", "festival", "surge", "convention")) and inventory_days >= 2.5:
        amount = max(amount, 140.0)
    if _alerts_contain(observation, ("health", "renovation", "storm", "supply")):
        amount *= 0.55
    return round(clamp(amount, 0.0, 500.0), 2)


def should_run_happy_hour(observation: dict[str, Any], service_stress: float, inventory_days: float, marketing: float) -> bool:
    if safe_int(observation.get("day"), 1) <= 10:
        return False
    if inventory_days < 4.0 or service_stress >= 1.2:
        return False
    if safe_float(observation.get("cash")) < 9000:
        return False
    weekday = str(observation.get("day_of_week", ""))
    if weekday in {"Monday", "Tuesday", "Wednesday"} and marketing > 0:
        return True
    return str(observation.get("customer_trend")) == "Declining" and weekday != "Saturday"


def choose_special(
    observation: dict[str, Any],
    menu: list[str],
    supplier_options: dict[str, list[dict[str, Any]]],
    stock: dict[str, float],
    pending: dict[str, float],
) -> str | None:
    dishes = {str(dish.get("name")): dish for dish in observation.get("menu_book", [])}
    rows: list[tuple[float, str]] = []
    for name in menu:
        dish = dishes.get(name)
        if not dish:
            continue
        unit_cost = dish_unit_cost(dish, supplier_options)
        base_price = safe_float(dish.get("base_price"))
        if unit_cost == float("inf") or base_price <= 0:
            continue
        servings = servings_for_dish(dish, stock, pending)
        ingredients = recipe_ingredients(dish)
        max_eta = 1
        for ingredient in ingredients:
            options = supplier_options.get(ingredient) or []
            if options:
                max_eta = max(max_eta, safe_int(options[0].get("eta_days"), 1))
        coverage_score = min(9.0, servings / 24.0)
        margin_score = (base_price - unit_cost) * 0.16
        cost_penalty = unit_cost * 0.18
        slow_supply_penalty = max_eta * 0.35
        score = coverage_score + margin_score - cost_penalty - slow_supply_penalty
        rows.append((score, name))
    rows.sort(key=lambda row: (-row[0], row[1]))
    return rows[0][1] if rows else None


def service_stress(observation: dict[str, Any]) -> float:
    service = observation.get("service_summary") or {}
    stress = 0.0
    walkout = str(service.get("walkout_band", "None"))
    stress += {"None": 0.0, "Few": 0.7, "Some": 1.8, "Many": 3.0}.get(walkout, 0.0)
    if safe_float(service.get("avg_wait_minutes")) > 7:
        stress += 0.6
    if safe_float(service.get("peak_wait_minutes")) > 20:
        stress += 0.7
    if service.get("kitchen_bottleneck_hours"):
        stress += 0.8
    if service.get("dishes_unavailable_at"):
        stress += 0.9
    return stress


def update_state_after_plan(
    observation: dict[str, Any],
    state: dict[str, Any],
    menu: list[str],
    shares: dict[str, float],
    ingredient_daily: dict[str, float],
    expected_covers: float,
) -> dict[str, Any]:
    previous_ema = safe_float(state.get("covers_ema"), DEFAULT_COVERS)
    service = observation.get("service_summary") or {}
    yesterday = safe_float(service.get("total_covers"))
    covers_ema = 0.55 * yesterday + 0.45 * previous_ema if yesterday > 0 else expected_covers
    return {
        "day": safe_int(observation.get("day")),
        "menu": menu,
        "covers_ema": round(covers_ema, 3),
        "dish_share": {name: round(value, 5) for name, value in shares.items()},
        "daily_ingredient_kg": {name: round(value, 4) for name, value in ingredient_daily.items()},
        "last_walkout_band": (observation.get("service_summary") or {}).get("walkout_band", "None"),
        "last_reputation_band": observation.get("reputation_band", "Very Good"),
    }


def _weekday_at(current: Any, offset: int) -> str:
    try:
        index = WEEKDAYS.index(str(current))
    except ValueError:
        index = 0
    return WEEKDAYS[(index + offset) % len(WEEKDAYS)]


def _weather_at(observation: dict[str, Any], offset: int) -> str:
    if offset <= 0:
        return str(observation.get("weather_today", "cloudy"))
    forecast = observation.get("weather_forecast") or []
    if offset - 1 < len(forecast):
        return str(forecast[offset - 1])
    return str(forecast[-1]) if forecast else str(observation.get("weather_today", "cloudy"))


def _scenario_multiplier(observation: dict[str, Any]) -> float:
    alerts = " ".join(str(alert) for alert in observation.get("alerts", [])).lower()
    multiplier = 1.0
    if any(token in alerts for token in ("tourist", "festival", "surge", "convention")):
        multiplier *= 1.18
    if any(token in alerts for token in ("renovation", "reduced capacity")):
        multiplier *= 0.80
    if any(token in alerts for token in ("health", "scare", "inspection")):
        multiplier *= 0.86
    if any(token in alerts for token in ("storm", "extreme weather")):
        multiplier *= 0.85
    return multiplier


def _dish_alert_penalty(name: str, ingredients: dict[str, float], alerts_text: str) -> float:
    if not alerts_text:
        return 0.0
    penalty = 0.0
    severe_tokens = ("recall", "health", "contamination", "scare", "avoid")
    for token in [name, *ingredients.keys()]:
        key = token.lower()
        if key in alerts_text and any(severe in alerts_text for severe in severe_tokens):
            penalty += 4.0
    return penalty


def _alerts_contain(observation: dict[str, Any], tokens: tuple[str, ...]) -> bool:
    text = " ".join(str(alert) for alert in observation.get("alerts", [])).lower()
    return any(token in text for token in tokens)
