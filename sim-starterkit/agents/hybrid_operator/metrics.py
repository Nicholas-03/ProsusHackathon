"""Derived metrics used by decision modules."""

from __future__ import annotations

from dataclasses import dataclass, field

from .constants import DOW_FACTOR, WEATHER_FACTOR
from .memory import Memory
from .state import GameState, MenuDish


@dataclass
class Metrics:
    yesterday_covers: float = 0.0
    predicted_covers: float = 90.0
    lost_demand_estimate: float = 0.0
    avg_ticket: float = 18.0
    dish_sales: dict[str, float] = field(default_factory=dict)
    ingredient_daily_need: dict[str, float] = field(default_factory=dict)
    ingredient_days_cover: dict[str, float] = field(default_factory=dict)
    stockout_dishes: list[str] = field(default_factory=list)
    service_pressure: float = 0.0
    waste_cost: float = 0.0


def _sold_or_even_weights(state: GameState, menu: list[str] | None = None) -> dict[str, float]:
    active = menu or state.active_menu
    sold_raw = state.service_summary.get("dishes_sold") or {}
    sold = {str(k): float(v or 0.0) for k, v in sold_raw.items() if str(k) in state.menu_book}
    if sold:
        for dish in active:
            sold.setdefault(dish, 1.0)
        return sold
    if not active:
        return {}
    return {dish: 1.0 for dish in active if dish in state.menu_book}


def estimate_lost_demand(state: GameState) -> float:
    summary = state.service_summary
    covers = float(summary.get("total_covers") or sum(summary.get("hourly_covers", []) or []) or 0.0)
    walkout = str(summary.get("walkout_band", "None"))
    lost = {
        "None": 0.0,
        "Few": 3.0,
        "Some": 12.0,
        "Many": 28.0,
    }.get(walkout, 0.0)

    unavailable = summary.get("dishes_unavailable_at") or {}
    if isinstance(unavailable, dict) and unavailable:
        lost += len(unavailable) * max(3.0, covers * 0.025)

    substitutions = float(summary.get("substitution_count") or 0.0)
    lost += min(8.0, substitutions * 0.35)

    peak_wait = float(summary.get("peak_wait_minutes") or 0.0)
    avg_wait = float(summary.get("avg_wait_minutes") or 0.0)
    if peak_wait >= 45 or avg_wait >= 18:
        lost += max(4.0, covers * 0.06)
    elif peak_wait >= 25 or avg_wait >= 10:
        lost += max(2.0, covers * 0.03)

    return max(0.0, min(55.0, lost))


def forecast_covers(state: GameState, memory: Memory) -> float:
    summary = state.service_summary
    covers = float(summary.get("total_covers") or sum(summary.get("hourly_covers", []) or []) or 0.0)
    lost_demand = estimate_lost_demand(state)
    observed_demand = covers + lost_demand
    base = observed_demand if observed_demand > 0 else memory.covers_ema
    dow_memory = memory.demand_by_dow.get(state.day_of_week)
    if dow_memory:
        base = 0.65 * base + 0.35 * dow_memory

    factor = DOW_FACTOR.get(state.day_of_week, 1.0)
    factor *= WEATHER_FACTOR.get(state.weather_today.lower(), 1.0)
    trend = state.customer_trend.lower()
    if "grow" in trend:
        factor *= 1.10
    elif "declin" in trend:
        factor *= 0.88

    alert_text = " ".join(state.alerts).lower()
    if any(token in alert_text for token in ("tourist", "festival", "surge", "busy", "demand spike")):
        factor *= 1.18
    if any(token in alert_text for token in ("renovation", "capacity", "construction", "tables reduced")):
        factor *= 0.82
    if any(token in alert_text for token in ("health scare", "food safety", "bad press")):
        factor *= 0.86

    forecast = base * (0.55 + 0.45 * factor)
    if covers > 0 and lost_demand > 0:
        forecast = max(forecast, covers + lost_demand * 0.45)
    if state.day <= 2:
        forecast = max(forecast, 85.0)
    return max(30.0, min(230.0, forecast))


def estimate_ingredient_need(
    state: GameState,
    predicted_covers: float,
    menu: list[str] | None = None,
) -> dict[str, float]:
    weights = _sold_or_even_weights(state, menu)
    total_weight = sum(max(0.0, v) for v in weights.values())
    if total_weight <= 0:
        return {}

    needs: dict[str, float] = {}
    for dish_name, weight in weights.items():
        dish = state.menu_book.get(dish_name)
        if not dish:
            continue
        estimated_sold = predicted_covers * max(0.0, weight) / total_weight
        for ingredient in dish.ingredients:
            needs[ingredient.ingredient] = (
                needs.get(ingredient.ingredient, 0.0)
                + ingredient.quantity_kg * estimated_sold
            )
    return needs


def dish_is_stocked(state: GameState, dish: MenuDish, portions: float = 8.0) -> bool:
    for ingredient in dish.ingredients:
        stock = state.inventory.get(ingredient.ingredient)
        total = stock.fresh_kg if stock else 0.0
        if total < ingredient.quantity_kg * portions:
            return False
    return True


def calculate_metrics(state: GameState, memory: Memory, menu: list[str] | None = None) -> Metrics:
    summary = state.service_summary
    covers = float(summary.get("total_covers") or sum(summary.get("hourly_covers", []) or []) or 0.0)
    lost_demand = estimate_lost_demand(state)
    revenue = float(summary.get("total_revenue") or state.yesterday_revenue or 0.0)
    predicted = forecast_covers(state, memory)
    avg_ticket = revenue / covers if covers > 0 and revenue > 0 else max(12.0, memory.revenue_ema / max(memory.covers_ema, 1.0))
    sold = {
        str(k): float(v or 0.0)
        for k, v in (summary.get("dishes_sold") or {}).items()
        if str(k) in state.menu_book
    }
    ingredient_need = estimate_ingredient_need(state, predicted, menu)
    pending = state.pending_by_ingredient()
    days_cover: dict[str, float] = {}
    for ingredient, daily_need in ingredient_need.items():
        if daily_need <= 0:
            days_cover[ingredient] = 99.0
            continue
        stock = state.inventory.get(ingredient)
        fresh = stock.fresh_kg if stock else 0.0
        days_cover[ingredient] = (fresh + pending.get(ingredient, 0.0)) / daily_need

    unavailable = summary.get("dishes_unavailable_at") or {}
    stockout_dishes = list(unavailable.keys()) if isinstance(unavailable, dict) else []
    walkout = str(summary.get("walkout_band", "None"))
    pressure = 0.0
    if walkout == "Few":
        pressure += 0.25
    elif walkout == "Some":
        pressure += 0.7
    elif walkout == "Many":
        pressure += 1.0
    pressure += min(1.0, float(summary.get("avg_wait_minutes") or 0.0) / 20.0) * 0.5
    pressure += min(1.0, float(summary.get("peak_wait_minutes") or 0.0) / 45.0) * 0.35
    pressure += min(1.0, len(summary.get("kitchen_bottleneck_hours") or []) / 4.0) * 0.4

    return Metrics(
        yesterday_covers=covers,
        predicted_covers=predicted,
        lost_demand_estimate=lost_demand,
        avg_ticket=avg_ticket,
        dish_sales=sold,
        ingredient_daily_need=ingredient_need,
        ingredient_days_cover=days_cover,
        stockout_dishes=stockout_dishes,
        service_pressure=pressure,
        waste_cost=float(state.cost_breakdown.get("waste") or 0.0),
    )
