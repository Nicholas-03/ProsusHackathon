"""Hybrid deterministic restaurant operator.

The public entry point is strategy(observation, day). The implementation keeps
LLM planning optional and uses deterministic, validated actions by default.
"""

from __future__ import annotations

from typing import Any

from agents.runner import run_game

from .logging_utils import log_decision
from .memory import build_notes, parse_notes, update_memory_from_state
from .metrics import calculate_metrics
from .planner import deterministic_plan
from .risk import assess_risk
from .scenario import detect_scenario
from .state import GameState
from .survival import make_cash_first_actions
from .suppliers import update_supplier_reliability
from .validator import validate_actions


def strategy(observation: dict[str, Any], day: int) -> list[dict[str, Any]]:
    """Return validated tool calls for one simulated day."""
    try:
        state = GameState.from_observation(observation, day)
        memory = parse_notes(state.notes)
        memory = update_memory_from_state(memory, state)
        memory = update_supplier_reliability(memory, state)

        metrics = calculate_metrics(state, memory)
        risk = assess_risk(state, metrics)
        scenario = detect_scenario(state, metrics, risk)
        plan = deterministic_plan(state, metrics, risk, scenario)

        raw_actions = make_cash_first_actions(state, metrics, risk, scenario)
        validated = validate_actions(raw_actions, state, risk, metrics)
        notes = build_notes(
            memory,
            state,
            mode=plan.mode,
            scenario=scenario.label,
            actions=validated,
            menu_changed=False,
        )
        final_actions = validate_actions(
            [*validated, {"tool": "save_notes", "args": {"text": notes}}],
            state,
            risk,
            metrics,
        )
        log_decision(state, metrics, risk, scenario, plan, final_actions)
        return final_actions
    except Exception:
        # Last-resort survival behavior. The contract prefers a safe empty-ish
        # list over crashing the evaluator.
        fallback_state = GameState.from_observation(observation or {}, day)
        fallback_risk = assess_risk(fallback_state, calculate_metrics(fallback_state, parse_notes(fallback_state.notes)))
        return validate_actions(
            [
                {"tool": "set_staff_level", "args": {"level": max(5, min(8, fallback_state.staff_level))}},
                {"tool": "save_notes", "args": {"text": '{"v":1,"m":"fallback"}'}},
            ],
            fallback_state,
            fallback_risk,
            calculate_metrics(fallback_state, parse_notes(fallback_state.notes)),
        )


if __name__ == "__main__":
    result = run_game(strategy, team_name="hybrid_operator", seed=42)
    print(result)
