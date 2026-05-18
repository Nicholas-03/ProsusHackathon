"""Best-effort JSONL decision logging."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .metrics import Metrics
from .planner import StrategyPlan
from .risk import RiskAssessment
from .scenario import ScenarioSignal
from .state import GameState

logger = logging.getLogger(__name__)


def log_decision(
    state: GameState,
    metrics: Metrics,
    risk: RiskAssessment,
    scenario: ScenarioSignal,
    plan: StrategyPlan,
    actions: list[dict[str, Any]],
) -> None:
    try:
        root = Path("logs") / "hybrid_operator"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
        row = {
            "day": state.day,
            "cash": round(state.cash, 2),
            "mode": plan.mode,
            "scenario": scenario.label,
            "risk": risk.__dict__,
            "metrics": {
                "predicted_covers": round(metrics.predicted_covers, 1),
                "lost_demand_estimate": round(metrics.lost_demand_estimate, 1),
                "stockouts": metrics.stockout_dishes,
                "service_pressure": round(metrics.service_pressure, 3),
            },
            "scenario_signals": scenario.signals,
            "symptoms": scenario.symptoms,
            "actions": actions,
            "alerts": state.alerts,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    except Exception as exc:  # pragma: no cover - logging must never fail strategy
        logger.debug("decision logging failed: %s", exc)
