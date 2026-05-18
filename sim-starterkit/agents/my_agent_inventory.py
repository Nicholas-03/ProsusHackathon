"""Inventory formulas adapted from deterministic-demand EOQ models."""

from __future__ import annotations

from math import sqrt


def eoq_constant_demand(demand_rate: float, setup_cost: float, holding_cost: float) -> float:
    """Classic EOQ: Q* = sqrt(2Klambda / h)."""
    if demand_rate <= 0 or setup_cost <= 0 or holding_cost <= 0:
        return 0.0
    return sqrt((2.0 * setup_cost * demand_rate) / holding_cost)


def eoq_nonconstant_demand(
    demand_rates: list[float],
    portions: list[float],
    setup_cost: float,
    holding_cost: float,
) -> float:
    """EOQ for a cycle split across known deterministic demand rates."""
    if setup_cost <= 0 or holding_cost <= 0 or not demand_rates:
        return 0.0
    if len(demand_rates) != len(portions):
        return 0.0

    total_rate = sum(portion * max(rate, 0.0) for rate, portion in zip(demand_rates, portions))
    if total_rate <= 0:
        return 0.0

    inventory_area_factor = 0.0
    elapsed_portion = 0.0
    for rate, portion in zip(demand_rates, portions):
        rate = max(rate, 0.0)
        inventory_area_factor += (portion * portion * rate) / 2.0
        inventory_area_factor += portion * rate * elapsed_portion
        elapsed_portion += portion

    if inventory_area_factor <= 0:
        return eoq_constant_demand(total_rate, setup_cost, holding_cost)
    return sqrt((setup_cost * total_rate * total_rate) / (holding_cost * inventory_area_factor))


def holding_cost_per_day(unit_cost: float, shelf_life_days: float) -> float:
    """Heuristic daily holding cost: capital tied up plus perishability risk."""
    shelf_life_days = max(1.0, shelf_life_days)
    return max(0.01, unit_cost * (0.035 + 0.18 / shelf_life_days))


def setup_cost_for_order(unit_cost: float, demand_rate: float, eta_days: float) -> float:
    """Virtual setup cost used to balance order frequency against stockout risk."""
    stockout_risk = 1.0 + min(max(eta_days - 1.0, 0.0), 6.0) * 0.18
    volume_risk = 1.0 + min(demand_rate, 25.0) / 80.0
    return max(12.0, min(65.0, unit_cost * 3.0 * stockout_risk * volume_risk))
