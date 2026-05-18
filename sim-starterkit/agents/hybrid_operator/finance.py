"""Deterministic cash runway and affordability helpers."""

from __future__ import annotations

from typing import Any

from .constants import FIXED_DAILY_COST, MAX_STAFF, MIN_STAFF
from .state import GameState


MIN_OPERATING_CASH = 650.0
SURVIVAL_RESERVE = 1050.0
HIGH_RISK_RESERVE = 1650.0
MEDIUM_RISK_RESERVE = 2300.0
LOW_RISK_RESERVE = 3000.0


def _risk_level(risk: Any, name: str, default: str = "low") -> str:
    return str(getattr(risk, name, default) or default)


def estimated_revenue_floor(state: GameState, metrics: Any | None = None) -> float:
    """Conservative revenue estimate used for survival budgeting.

    This is intentionally pessimistic: it should keep the agent alive even when
    yesterday's observed covers were censored by stockouts or walkouts.
    """
    yesterday = max(0.0, float(state.yesterday_revenue or 0.0))
    if metrics is None:
        return yesterday * 0.55

    predicted = max(0.0, float(getattr(metrics, "predicted_covers", 0.0) or 0.0))
    avg_ticket = max(8.0, float(getattr(metrics, "avg_ticket", 16.0) or 16.0))
    modeled = predicted * avg_ticket

    service_pressure = max(0.0, float(getattr(metrics, "service_pressure", 0.0) or 0.0))
    stockout_count = len(getattr(metrics, "stockout_dishes", []) or [])
    quality_factor = 0.68
    quality_factor -= min(0.22, service_pressure * 0.12)
    quality_factor -= min(0.18, stockout_count * 0.035)

    if yesterday > 0:
        modeled = min(modeled, max(yesterday * 1.12, modeled * 0.72))
        floor = 0.45 * yesterday + 0.55 * modeled * quality_factor
    else:
        floor = modeled * 0.45
    return max(0.0, floor)


def daily_overhead(state: GameState, staff_level: int | None = None) -> float:
    level = state.staff_level if staff_level is None else staff_level
    return FIXED_DAILY_COST + max(MIN_STAFF, min(MAX_STAFF, int(level))) * state.staff_cost_per_person


def cash_reserve(state: GameState, risk: Any, staff_level: int | None = None) -> float:
    overhead = daily_overhead(state, staff_level)
    cash_risk = _risk_level(risk, "cash_risk")
    if cash_risk == "critical":
        return max(SURVIVAL_RESERVE, overhead * 1.05)
    if cash_risk == "high":
        return max(HIGH_RISK_RESERVE, overhead * 1.25)
    if cash_risk == "medium":
        return max(MEDIUM_RISK_RESERVE, overhead * 1.45)
    return max(LOW_RISK_RESERVE, overhead * 1.75)


def projected_cash_after_basics(
    state: GameState,
    risk: Any,
    metrics: Any | None = None,
    *,
    staff_level: int | None = None,
    committed_spend: float = 0.0,
) -> float:
    revenue_floor = estimated_revenue_floor(state, metrics)
    return state.cash + revenue_floor - daily_overhead(state, staff_level) - max(0.0, committed_spend)


def available_order_budget(
    state: GameState,
    risk: Any,
    metrics: Any | None = None,
    *,
    staff_level: int | None = None,
    non_order_spend: float = 0.0,
) -> float:
    """Cash available for ingredient orders after reserves and basic costs."""
    reserve = cash_reserve(state, risk, staff_level)
    immediate_floor = max(MIN_OPERATING_CASH, min(reserve, state.cash * 0.55))
    cash_ceiling = state.cash - immediate_floor - max(0.0, non_order_spend)

    projected_ceiling = (
        projected_cash_after_basics(
            state,
            risk,
            metrics,
            staff_level=staff_level,
            committed_spend=non_order_spend,
        )
        - reserve
    )
    budget = min(cash_ceiling, projected_ceiling)

    cash_risk = _risk_level(risk, "cash_risk")
    bankruptcy_buffer = float(getattr(risk, "bankruptcy_buffer", 9999.0) or 0.0)
    if cash_risk == "critical":
        budget = min(budget, state.cash * 0.10)
    elif cash_risk == "high":
        budget = min(budget, state.cash * 0.18)
    elif cash_risk == "medium":
        budget = min(budget, state.cash * 0.28)
    if bankruptcy_buffer < 0:
        budget = min(budget, state.cash * 0.04)
    elif bankruptcy_buffer < 500:
        budget = min(budget, state.cash * 0.08)
    return max(0.0, budget)


def affordable_staff_cap(state: GameState, risk: Any, metrics: Any | None = None) -> int:
    """Highest staff level that leaves a basic operating reserve."""
    cash_risk = _risk_level(risk, "cash_risk")
    if cash_risk == "low":
        return MAX_STAFF

    reserve = cash_reserve(state, risk, MIN_STAFF)
    revenue_floor = estimated_revenue_floor(state, metrics)
    spendable_for_staff = state.cash + revenue_floor - FIXED_DAILY_COST - reserve
    affordable = int(spendable_for_staff // max(1.0, state.staff_cost_per_person))
    cap = max(MIN_STAFF, min(MAX_STAFF, affordable))

    if cash_risk == "critical":
        return min(cap, 5)
    if cash_risk == "high":
        return min(cap, 6)
    return min(cap, 8)
