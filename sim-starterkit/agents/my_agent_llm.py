"""Compatibility shim: this agent is intentionally deterministic.

The previous public entry point accepted an optional LLM refinement step.
This module preserves that import surface while guaranteeing that no external
model call, random sampling, or non-deterministic adjustment can change the
planned actions.
"""

from __future__ import annotations

from typing import Any


def refine_actions_with_llm(
    observation: dict[str, Any],
    day: int,
    planned_actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    del observation, day
    return planned_actions
