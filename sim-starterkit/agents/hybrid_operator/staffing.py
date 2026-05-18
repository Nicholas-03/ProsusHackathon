"""Staffing decisions."""

from __future__ import annotations

from .constants import MAX_STAFF, MIN_STAFF
from .finance import affordable_staff_cap
from .metrics import Metrics
from .planner import StrategyPlan
from .risk import RiskAssessment
from .scenario import ScenarioSignal
from .state import GameState


def _base_staff_for_covers(covers: float) -> int:
    if covers < 65:
        return 5
    if covers < 90:
        return 7
    if covers < 120:
        return 10
    if covers < 155:
        return 11
    if covers < 195:
        return 12
    return 13


def target_staff_level(
    state: GameState,
    metrics: Metrics,
    risk: RiskAssessment,
    scenario: ScenarioSignal,
    plan: StrategyPlan,
) -> int:
    target = _base_staff_for_covers(metrics.predicted_covers)
    if plan.staffing_intent == "increase":
        target += 1
    elif plan.staffing_intent == "decrease":
        target -= 1

    if risk.service_risk == "critical":
        target += 2
    elif risk.service_risk == "high":
        target += 1
    if scenario.label == "demand_spike":
        target += 1
    if scenario.label == "capacity_reduction" and risk.service_risk == "low":
        target -= 1

    if risk.cash_risk == "critical" and risk.service_risk not in {"high", "critical"}:
        target -= 2
    elif risk.cash_risk == "high" and risk.service_risk == "low":
        target -= 1
    elif risk.cash_risk == "high" and risk.service_risk == "medium":
        target -= 1

    floor = 5
    if risk.service_risk in {"high", "critical"}:
        floor = 7
    elif scenario.label == "demand_spike":
        floor = 7
    if risk.cash_risk == "critical" and risk.service_risk == "low":
        floor = 4

    target = max(floor, min(MAX_STAFF, target))
    if risk.cash_risk in {"medium", "high", "critical"}:
        cap = affordable_staff_cap(state, risk, metrics)
        if risk.service_risk in {"high", "critical"} and metrics.predicted_covers >= 145 and risk.cash_risk == "high":
            cap = min(MAX_STAFF, cap + 1)
        target = min(target, cap)
        if risk.cash_risk == "critical":
            target = min(target, 5 if metrics.predicted_covers < 130 else 6)
        target = max(MIN_STAFF, target)
    delta = target - state.staff_level
    if risk.cash_risk == "critical":
        max_change = 5
    else:
        max_change = 3 if risk.service_risk == "critical" else 2
    if abs(delta) > max_change:
        target = state.staff_level + max_change * (1 if delta > 0 else -1)
    return max(MIN_STAFF, min(MAX_STAFF, int(target)))


def make_staffing_actions(
    state: GameState,
    metrics: Metrics,
    risk: RiskAssessment,
    scenario: ScenarioSignal,
    plan: StrategyPlan,
) -> list[dict]:
    target = target_staff_level(state, metrics, risk, scenario, plan)
    if target == state.staff_level:
        return []
    return [{"tool": "set_staff_level", "args": {"level": target}}]
