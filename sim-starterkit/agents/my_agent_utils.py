"""Small deterministic helper functions for the RestBench agent."""

from __future__ import annotations

import json
from typing import Any

from agents.my_agent_config import NOTES_LIMIT, NOTES_PREFIX


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def round_kg(value: float) -> float:
    if value < 20:
        return round(max(0.0, value) * 2.0) / 2.0
    return round(max(0.0, value))


def tool_call(tool: str, **args: Any) -> dict[str, Any]:
    return {"tool": tool, "args": args}


def read_notes(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    raw = text.strip()
    if raw.startswith(NOTES_PREFIX):
        raw = raw[len(NOTES_PREFIX):]
    else:
        start = raw.find("{")
        if start < 0:
            return {}
        raw = raw[start:]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_notes(state: dict[str, Any]) -> str:
    compact = _compact_state(state)
    payload = json.dumps(compact, sort_keys=True, separators=(",", ":"))
    text = f"{NOTES_PREFIX}{payload}"
    if len(text) <= NOTES_LIMIT:
        return text

    # Keep the strategic memory first, then trim the noisiest telemetry.
    compact.pop("daily_ingredient_kg", None)
    compact.pop("dish_share", None)
    payload = json.dumps(compact, sort_keys=True, separators=(",", ":"))
    text = f"{NOTES_PREFIX}{payload}"
    return text[:NOTES_LIMIT]


def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in state.items():
        if isinstance(value, float):
            compact[key] = round(value, 4)
        elif isinstance(value, dict):
            child: dict[str, Any] = {}
            for child_key, child_value in value.items():
                if isinstance(child_value, float):
                    child[child_key] = round(child_value, 4)
                else:
                    child[child_key] = child_value
            compact[key] = child
        else:
            compact[key] = value
    return compact
