"""Scenario detection from alerts and drift signals."""

from __future__ import annotations

from dataclasses import dataclass, field

from .metrics import Metrics
from .risk import RiskAssessment
from .state import GameState


@dataclass(frozen=True)
class ScenarioSignal:
    label: str = "baseline"
    confidence: float = 0.35
    signals: list[str] = field(default_factory=list)
    symptoms: list[str] = field(default_factory=list)


def detect_scenario(state: GameState, metrics: Metrics, risk: RiskAssessment) -> ScenarioSignal:
    text = " ".join(state.alerts).lower()
    scores: dict[str, float] = {
        "supply_shock": 0.0,
        "demand_spike": 0.0,
        "demand_drop": 0.0,
        "capacity_reduction": 0.0,
        "cost_pressure": 0.0,
        "reputation_shock": 0.0,
    }
    reasons: dict[str, list[str]] = {label: [] for label in scores}

    keyword_map = {
        "supply_shock": ("supplier", "outage", "delivery", "shortage", "strike", "delayed", "disruption"),
        "demand_spike": ("tourist", "festival", "surge", "rush", "peak demand", "busy"),
        "demand_drop": ("demand drop", "decline", "quiet", "slowdown", "fewer customers"),
        "capacity_reduction": ("renovation", "capacity", "construction", "tables", "limited seating"),
        "cost_pressure": ("inflation", "cost", "price increase", "expensive", "margin"),
        "reputation_shock": ("health", "safety", "bad press", "review", "reputation", "complaint"),
    }
    for label, keywords in keyword_map.items():
        hits = [kw for kw in keywords if kw in text]
        if hits:
            scores[label] += 0.55 + min(0.3, 0.08 * len(hits))
            reasons[label].extend(hits[:3])

    if metrics.stockout_dishes or risk.inventory_risk in {"high", "critical"}:
        scores["supply_shock"] += 0.2
        reasons["supply_shock"].append("stockout")
    if state.customer_trend == "Growing" or metrics.predicted_covers > max(120.0, metrics.yesterday_covers * 1.18):
        scores["demand_spike"] += 0.25
        reasons["demand_spike"].append("growing demand")
    if state.customer_trend == "Declining":
        scores["demand_drop"] += 0.25
        reasons["demand_drop"].append("declining trend")
    if risk.reputation_risk in {"high", "critical"} and any(
        word in text for word in ("health", "safety", "bad press", "review", "reputation", "complaint")
    ):
        scores["reputation_shock"] += 0.25
        reasons["reputation_shock"].append("reputation alert")
    if state.yesterday_total_costs > state.yesterday_revenue * 0.85 and state.yesterday_revenue > 0:
        scores["cost_pressure"] += 0.15
        reasons["cost_pressure"].append("cost ratio")

    symptoms = []
    if risk.reputation_risk in {"high", "critical"}:
        symptoms.append("reputation_risk")
    if risk.service_risk in {"high", "critical"}:
        symptoms.append("service_risk")
    if risk.inventory_risk in {"high", "critical"}:
        symptoms.append("inventory_risk")
    if risk.cash_risk in {"high", "critical"}:
        symptoms.append("cash_risk")

    label, confidence = max(scores.items(), key=lambda item: item[1])
    if confidence < 0.25:
        return ScenarioSignal(symptoms=symptoms)
    strong = [name for name, score in scores.items() if score >= 0.45]
    if len(strong) >= 2 and confidence < 0.7:
        return ScenarioSignal("mixed_crisis", min(0.9, confidence + 0.1), strong, symptoms)
    return ScenarioSignal(label, min(0.95, confidence), reasons[label], symptoms)
