"""Hybrid RestBench agent.

The rule layer creates a full deterministic plan. The LLM layer, when enabled
and configured, can add conservative adjustments through the OpenAI API.
"""

from __future__ import annotations

from typing import Any

from agents.runner import run_game
from agents.my_agent_config import TEAM_NAME
from agents.my_agent_llm import refine_actions_with_llm
from agents.my_agent_rules import build_rule_actions


def strategy(observation: dict[str, Any], day: int) -> list[dict[str, Any]]:
    rule_actions = build_rule_actions(observation, day)
    return refine_actions_with_llm(observation, day, rule_actions)


if __name__ == "__main__":
    run_game(strategy, team_name=TEAM_NAME, seed=42)
