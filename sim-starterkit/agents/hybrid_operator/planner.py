"""High-level strategic planning with deterministic fallback."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .metrics import Metrics
from .risk import RiskAssessment
from .scenario import ScenarioSignal
from .state import GameState

try:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True), override=True)
except Exception:  # pragma: no cover - dotenv is a convenience, not a dependency at runtime
    pass

os.environ.setdefault("LITELLM_LOG", "ERROR")


@dataclass(frozen=True)
class StrategyPlan:
    mode: str
    pricing_intent: str
    staffing_intent: str
    inventory_intent: str
    supplier_intent: str
    promotion_intent: str
    menu_intent: str
    risk_tolerance: str
    rationale: str


MODES = {"survival", "recovery", "defensive", "growth", "premium", "balanced"}
PRICING = {"lower", "hold", "raise_selective", "raise_broad"}
STAFFING = {"decrease", "hold", "increase"}
INVENTORY = {"conserve", "normal", "stockpile", "emergency"}
SUPPLIER = {"cheapest", "balanced", "reliable", "diversify"}
PROMOTION = {"none", "daily_special", "happy_hour", "marketing"}
MENU = {"hold", "simplify", "diversify", "replace_shortage"}
RISK_TOLERANCE = {"low", "medium", "high"}


def deterministic_plan(
    state: GameState,
    metrics: Metrics,
    risk: RiskAssessment,
    scenario: ScenarioSignal,
) -> StrategyPlan:
    if risk.cash_risk == "critical":
        mode = "survival"
    elif risk.cash_risk == "high":
        mode = "defensive"
    elif risk.cash_risk == "medium":
        mode = "defensive"
    elif risk.reputation_risk in {"high", "critical"} or risk.service_risk in {"high", "critical"}:
        mode = "recovery"
    elif scenario.label == "supply_shock" or risk.inventory_risk in {"high", "critical"}:
        mode = "defensive"
    elif scenario.label == "demand_spike" and risk.cash_risk in {"low", "medium"}:
        mode = "growth"
    elif state.reputation_band in {"Very Good", "Excellent"} and risk.cash_risk == "low":
        mode = "premium"
    elif risk.cash_risk == "high":
        mode = "defensive"
    elif scenario.label in {"capacity_reduction", "cost_pressure", "demand_drop", "mixed_crisis"}:
        mode = "defensive"
    else:
        mode = "balanced"

    pricing_intent = "hold"
    staffing_intent = "hold"
    inventory_intent = "normal"
    supplier_intent = "balanced"
    promotion_intent = "daily_special"
    menu_intent = "hold"
    risk_tolerance = "medium"

    if mode == "survival":
        pricing_intent = "raise_selective" if risk.reputation_risk not in {"high", "critical"} else "hold"
        staffing_intent = "decrease" if risk.service_risk in {"low", "medium"} else "hold"
        inventory_intent = "emergency" if risk.inventory_risk in {"high", "critical"} else "conserve"
        supplier_intent = "cheapest"
        promotion_intent = "none"
        risk_tolerance = "low"
    elif mode == "recovery":
        pricing_intent = "lower" if risk.reputation_risk in {"high", "critical"} and risk.cash_risk == "low" else "hold"
        staffing_intent = "increase" if risk.service_risk in {"high", "critical"} else "hold"
        inventory_intent = "emergency" if risk.inventory_risk in {"high", "critical"} else "normal"
        supplier_intent = "reliable"
        promotion_intent = "daily_special"
        menu_intent = "replace_shortage" if metrics.stockout_dishes else "hold"
        risk_tolerance = "low"
    elif mode == "defensive":
        pricing_intent = "raise_selective" if scenario.label == "cost_pressure" or risk.cash_risk in {"medium", "high"} else "hold"
        staffing_intent = "decrease" if scenario.label == "capacity_reduction" and risk.service_risk == "low" else "hold"
        inventory_intent = "stockpile" if scenario.label == "supply_shock" and risk.cash_risk == "low" else "conserve"
        supplier_intent = "diversify" if scenario.label == "supply_shock" else "balanced"
        promotion_intent = "daily_special" if risk.inventory_risk not in {"high", "critical"} else "none"
        menu_intent = "replace_shortage" if metrics.stockout_dishes else "hold"
        risk_tolerance = "low"
    elif mode == "growth":
        pricing_intent = "raise_selective"
        staffing_intent = "increase"
        inventory_intent = "stockpile"
        supplier_intent = "reliable"
        promotion_intent = "daily_special"
        menu_intent = "diversify"
        risk_tolerance = "medium"
    elif mode == "premium":
        pricing_intent = "raise_selective"
        staffing_intent = "hold"
        inventory_intent = "normal"
        supplier_intent = "balanced"
        promotion_intent = "daily_special"
        menu_intent = "hold"
        risk_tolerance = "medium"

    if risk.inventory_risk in {"high", "critical"}:
        inventory_intent = "emergency"
        supplier_intent = "reliable" if mode != "survival" else supplier_intent
        promotion_intent = "none"
        menu_intent = "replace_shortage" if metrics.stockout_dishes else "hold"
    if risk.service_risk in {"high", "critical"}:
        staffing_intent = "increase"
        promotion_intent = "none" if risk.inventory_risk in {"high", "critical"} else "daily_special"
    if risk.cash_risk in {"medium", "high", "critical"}:
        promotion_intent = "none"
        risk_tolerance = "low"
        if risk.inventory_risk not in {"high", "critical"}:
            inventory_intent = "conserve"
        if risk.cash_risk == "high" and pricing_intent == "lower":
            pricing_intent = "hold"

    return StrategyPlan(
        mode=mode,
        pricing_intent=pricing_intent,
        staffing_intent=staffing_intent,
        inventory_intent=inventory_intent,
        supplier_intent=supplier_intent,
        promotion_intent=promotion_intent,
        menu_intent=menu_intent,
        risk_tolerance=risk_tolerance,
        rationale=f"{mode}:{scenario.label}:{risk.overall}:{int(metrics.predicted_covers)} covers",
    )


def _validate_plan(data: dict, fallback: StrategyPlan) -> StrategyPlan:
    try:
        return StrategyPlan(
            mode=str(data.get("mode")) if data.get("mode") in MODES else fallback.mode,
            pricing_intent=str(data.get("pricing_intent")) if data.get("pricing_intent") in PRICING else fallback.pricing_intent,
            staffing_intent=str(data.get("staffing_intent")) if data.get("staffing_intent") in STAFFING else fallback.staffing_intent,
            inventory_intent=str(data.get("inventory_intent")) if data.get("inventory_intent") in INVENTORY else fallback.inventory_intent,
            supplier_intent=str(data.get("supplier_intent")) if data.get("supplier_intent") in SUPPLIER else fallback.supplier_intent,
            promotion_intent=str(data.get("promotion_intent")) if data.get("promotion_intent") in PROMOTION else fallback.promotion_intent,
            menu_intent=str(data.get("menu_intent")) if data.get("menu_intent") in MENU else fallback.menu_intent,
            risk_tolerance=str(data.get("risk_tolerance")) if data.get("risk_tolerance") in RISK_TOLERANCE else fallback.risk_tolerance,
            rationale=str(data.get("rationale", fallback.rationale))[:240],
        )
    except Exception:
        return fallback


def optional_llm_plan(
    state: GameState,
    metrics: Metrics,
    risk: RiskAssessment,
    scenario: ScenarioSignal,
    fallback: StrategyPlan,
) -> StrategyPlan:
    if not state.menu_book or not state.suppliers or state.cash <= 0:
        return fallback
    if os.getenv("USE_LLM_PLANNER", "false").lower() != "true":
        return fallback
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LITELLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    api_base = (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("OPENAI_API_BASE")
        or os.getenv("LITELLM_PROXY_BASE_URL")
    )
    if not api_key or api_key.strip() in {"sk-your-virtual-key", "sk-..."}:
        return fallback
    try:
        from litellm import completion
    except Exception:
        return fallback

    payload = {
        "day": state.day,
        "cash": round(state.cash, 0),
        "reputation": state.reputation_band,
        "trend": state.customer_trend,
        "risk": risk.__dict__,
        "scenario": scenario.__dict__,
        "service": {
            "walkouts": state.service_summary.get("walkout_band"),
            "avg_wait": state.service_summary.get("avg_wait_minutes"),
            "stockouts": metrics.stockout_dishes,
        },
        "predicted_covers": round(metrics.predicted_covers, 1),
        "alerts": state.alerts[-4:],
        "fallback": fallback.__dict__,
    }
    system = (
        "You are the strategic planner for a restaurant simulation agent. "
        "Return only JSON matching StrategyPlan. Do not return tool calls. "
        "Prioritize survival, service quality, stockout prevention, and reputation."
    )
    try:
        kwargs = {
            "model": os.getenv("AGENT_MODEL", "openai/gpt-4.1-mini"),
            "fallback_models": [os.getenv("AGENT_MODEL_FALLBACK", "openai/gpt-4.1-nano")],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
            ],
            "temperature": 0.2,
            "max_tokens": 600,
            "timeout": float(os.getenv("LLM_TIMEOUT_SECONDS", "6")),
            "api_key": api_key,
        }
        if api_base:
            kwargs["api_base"] = api_base
        response = completion(
            **kwargs,
        )
        content = response["choices"][0]["message"]["content"]
        data = json.loads(content)
        if isinstance(data, dict):
            return _validate_plan(data, fallback)
    except Exception:
        return fallback
    return fallback


def make_plan(
    state: GameState,
    metrics: Metrics,
    risk: RiskAssessment,
    scenario: ScenarioSignal,
) -> StrategyPlan:
    fallback = deterministic_plan(state, metrics, risk, scenario)
    return optional_llm_plan(state, metrics, risk, scenario, fallback)
