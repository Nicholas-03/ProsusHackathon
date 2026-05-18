"""Promotions and customer satisfaction actions."""

from __future__ import annotations

from .economics import dish_margin, dish_margin_ratio
from .metrics import Metrics, dish_is_stocked
from .planner import StrategyPlan
from .risk import RiskAssessment
from .scenario import ScenarioSignal
from .state import GameState


SLOW_DAYS = {"Monday", "Tuesday", "Wednesday"}


def _best_special(state: GameState, metrics: Metrics, menu: list[str]) -> str | None:
    candidates = [state.menu_book[name] for name in menu if name in state.menu_book]
    stocked = [dish for dish in candidates if dish_is_stocked(state, dish, portions=10.0)]
    if stocked:
        candidates = stocked
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda dish: (
            metrics.dish_sales.get(dish.name, 1.0),
            dish_margin_ratio(state, dish),
            dish_margin(state, dish),
        ),
    ).name


def make_satisfaction_actions(
    state: GameState,
    metrics: Metrics,
    risk: RiskAssessment,
    scenario: ScenarioSignal,
    plan: StrategyPlan,
    menu: list[str],
) -> list[dict]:
    actions: list[dict] = []
    inventory_safe = risk.inventory_risk not in {"high", "critical"}
    service_safe = risk.service_risk not in {"high", "critical"}
    cash_safe = risk.cash_risk == "low"

    special = _best_special(state, metrics, menu)
    if special and plan.promotion_intent in {"daily_special", "happy_hour", "marketing"} and risk.cash_risk != "critical":
        actions.append({"tool": "offer_daily_special", "args": {"dish": special}})
    elif special and risk.reputation_risk in {"medium", "high", "critical"} and inventory_safe and risk.cash_risk != "critical":
        actions.append({"tool": "offer_daily_special", "args": {"dish": special}})

    if not inventory_safe or not service_safe:
        return actions

    if plan.promotion_intent == "happy_hour" and cash_safe:
        actions.append({"tool": "run_happy_hour", "args": {}})
    elif (
        state.day_of_week in SLOW_DAYS
        and state.customer_trend != "Growing"
        and risk.cash_risk == "low"
        and state.cash > 18000
        and scenario.label not in {"demand_spike", "capacity_reduction"}
        and metrics.predicted_covers < 105
        and risk.reputation_risk not in {"high", "critical"}
    ):
        actions.append({"tool": "run_happy_hour", "args": {}})

    if plan.promotion_intent == "marketing" and cash_safe:
        amount = 120 if state.customer_trend == "Declining" else 80
        actions.append({"tool": "set_marketing_spend", "args": {"amount": amount}})
    elif (
        state.customer_trend == "Declining"
        and risk.reputation_risk not in {"high", "critical"}
        and inventory_safe
        and service_safe
        and state.cash > 7000
    ):
        actions.append({"tool": "set_marketing_spend", "args": {"amount": 80}})
    return actions
