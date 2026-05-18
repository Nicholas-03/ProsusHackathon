"""Deterministic RestBench agent."""

from __future__ import annotations

from typing import Any

from agents.runner import run_game
from agents.my_agent_config import TEAM_NAME
from agents.my_agent_rules import build_rule_actions


def strategy(observation: dict[str, Any], day: int) -> list[dict[str, Any]]:
    return build_rule_actions(observation, day)


if __name__ == "__main__":
    run_game(strategy, team_name=TEAM_NAME, seed=42)
