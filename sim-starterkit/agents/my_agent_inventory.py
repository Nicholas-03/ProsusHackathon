"""Deterministic inventory calculations inspired by EOQ models.

The formulas mirror the deterministic-demand models in the referenced paper:
constant-demand EOQ and the piecewise-demand EOQ variant for non-constant
demand within a cycle. The game has no explicit order setup fee, so the agent
uses a fixed operational friction cost to keep order frequency finite.
"""

from __future__ import annotations

from math import sqrt
from typing import Any

from agents.my_agent_config import (
    DAILY_CAPITAL_RATE,
    DAY_INDEX,
    ORDER_SETUP_COST,
    WASTE_HOLDING_FACTOR,
    WEEKDAYS,
)
from agents.my_agent_utils import safe_float, safe_int


def stock_by_ingredient(observation: dict[str, Any], *, min_expires_in_days: int = 0) -> dict[str, float]:
    stock: dict[str, float] = {}
    for item in observation.get("inventory", []):
        ingredient = item.get("ingredient")
        if not ingredient:
            continue
        batches = item.get("batches") or []
        if batches:
            qty = sum(
                safe_float(batch.get("quantity_kg"))
                for batch in batches
                if safe_int(batch.get("expires_in_days")) >= min_expires_in_days
            )
        else:
            qty = safe_float(item.get("total_kg"))
        stock[str(ingredient)] = qty
    return stock


def shelf_life_by_ingredient(observation: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in observation.get("inventory", []):
        ingredient = item.get("ingredient")
        if ingredient:
            result[str(ingredient)] = max(1, safe_int(item.get("shelf_life_days"), 7))
    return result


def pending_by_ingredient(observation: dict[str, Any]) -> dict[str, float]:
    pending: dict[str, float] = {}
    for order in observation.get("pending_orders", []):
        ingredient = order.get("ingredient")
        if ingredient:
            pending[str(ingredient)] = pending.get(str(ingredient), 0.0) + safe_float(order.get("quantity_kg"))
    return pending


def pending_due_by_ingredient(observation: dict[str, Any], *, through_day: int) -> dict[str, float]:
    pending: dict[str, float] = {}
    for order in observation.get("pending_orders", []):
        ingredient = order.get("ingredient")
        if not ingredient:
            continue
        delivery_day = safe_int(order.get("delivery_day"), 10_000)
        if delivery_day <= through_day:
            pending[str(ingredient)] = pending.get(str(ingredient), 0.0) + safe_float(order.get("quantity_kg"))
    return pending


def recipe_ingredients(dish: dict[str, Any]) -> dict[str, float]:
    ingredients: dict[str, float] = {}
    for item in dish.get("ingredients", []):
        name = item.get("ingredient")
        qty = safe_float(item.get("quantity_kg"))
        if name and qty > 0:
            ingredients[str(name)] = qty
    return ingredients


def build_supplier_options(observation: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    alerts_text = " ".join(str(alert) for alert in observation.get("alerts", [])).lower()
    history = observation.get("delivery_history", [])
    current_weekday = str(observation.get("day_of_week", "Monday"))
    options: dict[str, list[dict[str, Any]]] = {}

    for supplier in observation.get("supplier_catalog", []):
        supplier_name = str(supplier.get("name", ""))
        if not supplier_name:
            continue
        eta = days_until_delivery(supplier, current_weekday)
        min_order = safe_float(supplier.get("min_order_kg"), 1.0)
        supplier_alert = _alert_penalty(supplier_name, alerts_text)

        for ingredient, raw_price in (supplier.get("ingredients") or {}).items():
            price = safe_float(raw_price)
            if price <= 0:
                continue
            reliability = _reliability_penalty(history, supplier_name, str(ingredient))
            effective_price = price * (1.0 + reliability + supplier_alert) + price * 0.22 * max(0, eta - 1)
            option = {
                "supplier": supplier_name,
                "ingredient": str(ingredient),
                "price": price,
                "effective_price": effective_price,
                "eta_days": eta,
                "min_order_kg": max(0.1, min_order),
                "delivery_days": supplier.get("delivery_days", []),
                "lead_time_days": safe_int(supplier.get("lead_time_days"), 1),
                "alert_penalty": supplier_alert,
                "reliability_penalty": reliability,
            }
            options.setdefault(str(ingredient), []).append(option)

    for ingredient_options in options.values():
        ingredient_options.sort(key=lambda item: (item["effective_price"], item["eta_days"], item["supplier"]))
    return options


def best_supplier(options: dict[str, list[dict[str, Any]]], ingredient: str) -> dict[str, Any] | None:
    ingredient_options = options.get(ingredient) or []
    return ingredient_options[0] if ingredient_options else None


def days_until_delivery(supplier: dict[str, Any], current_weekday: str) -> int:
    delivery_days = set(supplier.get("delivery_days") or [])
    lead_time = max(1, safe_int(supplier.get("lead_time_days"), 1))
    current_index = DAY_INDEX.get(current_weekday, 0)
    if not delivery_days:
        return lead_time
    for offset in range(lead_time, 15):
        candidate = WEEKDAYS[(current_index + offset) % len(WEEKDAYS)]
        if candidate in delivery_days:
            return offset
    return lead_time + 7


def dish_unit_cost(dish: dict[str, Any], supplier_options: dict[str, list[dict[str, Any]]]) -> float:
    cost = 0.0
    for ingredient, qty in recipe_ingredients(dish).items():
        supplier = best_supplier(supplier_options, ingredient)
        if supplier is None:
            return float("inf")
        cost += qty * safe_float(supplier.get("price"))
    return cost


def servings_for_dish(dish: dict[str, Any], stock: dict[str, float], pending: dict[str, float] | None = None) -> float:
    pending = pending or {}
    servings = float("inf")
    for ingredient, qty in recipe_ingredients(dish).items():
        available = stock.get(ingredient, 0.0) + pending.get(ingredient, 0.0)
        servings = min(servings, available / qty if qty > 0 else float("inf"))
    return 0.0 if servings == float("inf") else servings


def eoq_constant(
    demand_rate_kg: float,
    unit_cost: float,
    shelf_life_days: int,
    *,
    order_cost: float = ORDER_SETUP_COST,
) -> float:
    demand_rate_kg = max(0.0, demand_rate_kg)
    if demand_rate_kg <= 0 or unit_cost <= 0:
        return 0.0
    holding_cost = deterministic_holding_cost(unit_cost, shelf_life_days)
    return sqrt((2.0 * order_cost * demand_rate_kg) / holding_cost)


def eoq_piecewise(
    demand_rates_kg: list[float],
    portions: list[float],
    unit_cost: float,
    shelf_life_days: int,
    *,
    order_cost: float = ORDER_SETUP_COST,
) -> float:
    if not demand_rates_kg:
        return 0.0
    if len(demand_rates_kg) != len(portions):
        raise ValueError("demand_rates_kg and portions must have the same length")
    total_portion = sum(max(0.0, item) for item in portions)
    if total_portion <= 0:
        return eoq_constant(sum(demand_rates_kg) / len(demand_rates_kg), unit_cost, shelf_life_days, order_cost=order_cost)

    normalized = [max(0.0, item) / total_portion for item in portions]
    weighted_demand = sum(portion * max(0.0, demand) for portion, demand in zip(normalized, demand_rates_kg))
    if weighted_demand <= 0 or unit_cost <= 0:
        return 0.0

    shape = 0.0
    elapsed = 0.0
    for portion, demand in zip(normalized, demand_rates_kg):
        demand = max(0.0, demand)
        shape += (portion * portion * demand) / 2.0
        shape += portion * demand * elapsed
        elapsed += portion

    if shape <= 0:
        return eoq_constant(weighted_demand, unit_cost, shelf_life_days, order_cost=order_cost)

    holding_cost = deterministic_holding_cost(unit_cost, shelf_life_days)
    return sqrt((order_cost * weighted_demand * weighted_demand) / (holding_cost * shape))


def deterministic_holding_cost(unit_cost: float, shelf_life_days: int) -> float:
    shelf_life = max(1, shelf_life_days)
    spoilage_pressure = unit_cost / shelf_life * WASTE_HOLDING_FACTOR
    capital_pressure = unit_cost * DAILY_CAPITAL_RATE
    return max(0.03, spoilage_pressure + capital_pressure)


def _alert_penalty(supplier_name: str, alerts_text: str) -> float:
    if not alerts_text:
        return 0.0
    supplier_key = supplier_name.lower()
    if supplier_key not in alerts_text:
        return 0.0
    severe = ("halt", "outage", "closed", "strike", "suspend", "unavailable", "recall")
    return 8.0 if any(token in alerts_text for token in severe) else 0.35


def _reliability_penalty(history: list[dict[str, Any]], supplier: str, ingredient: str) -> float:
    relevant = [
        item for item in history
        if item.get("supplier") == supplier and item.get("ingredient") == ingredient
    ][-8:]
    if not relevant:
        relevant = [item for item in history if item.get("supplier") == supplier][-8:]
    if not relevant:
        return 0.0

    ordered = sum(max(0.0, safe_float(item.get("ordered_kg"))) for item in relevant)
    delivered = sum(max(0.0, safe_float(item.get("delivered_kg"))) for item in relevant)
    fill_rate = delivered / ordered if ordered > 0 else 1.0
    late_count = sum(1 for item in relevant if item.get("on_time") is False)
    late_rate = late_count / len(relevant)
    return max(0.0, 1.0 - fill_rate) * 0.9 + late_rate * 0.18
