"""Risk assessment for survival, service, reputation, and inventory."""

from __future__ import annotations

from dataclasses import dataclass

from .finance import cash_reserve, projected_cash_after_basics
from .constants import REPUTATION_SCORE, WALKOUT_SCORE
from .metrics import Metrics
from .state import GameState


@dataclass(frozen=True)
class RiskAssessment:
    cash_risk: str = "low"
    service_risk: str = "low"
    inventory_risk: str = "low"
    reputation_risk: str = "low"
    demand_risk: str = "low"
    waste_risk: str = "low"
    overall: str = "low"
    bankruptcy_buffer: float = 0.0
    projected_min_cash: float = 0.0


def _max_risk(*levels: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return max(levels, key=lambda level: order.get(level, 0))


def assess_risk(state: GameState, metrics: Metrics) -> RiskAssessment:
    daily_overhead = 300.0 + state.staff_level * state.staff_cost_per_person
    pnl = state.yesterday_revenue - state.yesterday_total_costs
    runway = state.cash / max(daily_overhead, 1.0)
    projected_min_cash = projected_cash_after_basics(state, None, metrics)
    reserve = cash_reserve(state, None)
    bankruptcy_buffer = projected_min_cash - reserve
    if state.cash < 1400 or runway < 1.0 or projected_min_cash < 900:
        cash_risk = "critical"
    elif state.cash < 4200 or bankruptcy_buffer < 700 or (pnl < -500 and state.cash < 6500):
        cash_risk = "high"
    elif state.cash < 7500 or bankruptcy_buffer < 1800 or pnl < -250:
        cash_risk = "medium"
    else:
        cash_risk = "low"

    walkout = str(state.service_summary.get("walkout_band", "None"))
    wait = float(state.service_summary.get("avg_wait_minutes") or 0.0)
    peak = float(state.service_summary.get("peak_wait_minutes") or 0.0)
    bottlenecks = len(state.service_summary.get("kitchen_bottleneck_hours") or [])
    if WALKOUT_SCORE.get(walkout, 0) >= 3 or wait >= 20 or peak >= 50:
        service_risk = "critical"
    elif WALKOUT_SCORE.get(walkout, 0) >= 2 or wait >= 12 or bottlenecks >= 3:
        service_risk = "high"
    elif WALKOUT_SCORE.get(walkout, 0) >= 1 or wait >= 7 or bottlenecks:
        service_risk = "medium"
    else:
        service_risk = "low"

    low_cover_values = [v for v in metrics.ingredient_days_cover.values() if v < 1.0]
    if metrics.stockout_dishes or any(v < 0.45 for v in metrics.ingredient_days_cover.values()):
        inventory_risk = "critical"
    elif len(low_cover_values) >= 3 or any(v < 0.8 for v in metrics.ingredient_days_cover.values()):
        inventory_risk = "high"
    elif any(v < 1.25 for v in metrics.ingredient_days_cover.values()):
        inventory_risk = "medium"
    else:
        inventory_risk = "low"

    rep_score = REPUTATION_SCORE.get(state.reputation_band, 3)
    review_stars = [
        float(review.get("stars", 5.0) or 5.0)
        for review in state.recent_reviews[-8:]
        if isinstance(review, dict)
    ]
    avg_review = sum(review_stars) / len(review_stars) if review_stars else 4.2
    if rep_score <= 1 or avg_review < 2.8:
        reputation_risk = "critical"
    elif rep_score <= 2 or avg_review < 3.4:
        reputation_risk = "high"
    elif rep_score <= 3 or avg_review < 3.9:
        reputation_risk = "medium"
    else:
        reputation_risk = "low"

    if "Declining" in state.customer_trend and metrics.yesterday_covers < metrics.predicted_covers * 0.75:
        demand_risk = "high"
    elif "Declining" in state.customer_trend:
        demand_risk = "medium"
    else:
        demand_risk = "low"

    if metrics.waste_cost > max(80.0, state.yesterday_revenue * 0.08):
        waste_risk = "high"
    elif metrics.waste_cost > max(35.0, state.yesterday_revenue * 0.04):
        waste_risk = "medium"
    else:
        waste_risk = "low"

    return RiskAssessment(
        cash_risk=cash_risk,
        service_risk=service_risk,
        inventory_risk=inventory_risk,
        reputation_risk=reputation_risk,
        demand_risk=demand_risk,
        waste_risk=waste_risk,
        overall=_max_risk(cash_risk, service_risk, inventory_risk, reputation_risk),
        bankruptcy_buffer=round(bankruptcy_buffer, 2),
        projected_min_cash=round(projected_min_cash, 2),
    )
