"""Compact persistent memory stored through the save_notes tool."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .constants import NOTES_LIMIT, TARGET_NOTES_LIMIT
from .state import GameState

try:
    import orjson
except Exception:  # pragma: no cover - optional dependency fallback
    orjson = None


@dataclass
class Memory:
    version: int = 1
    last_day: int = 0
    covers_ema: float = 90.0
    revenue_ema: float = 1800.0
    demand_by_dow: dict[str, float] = field(default_factory=dict)
    supplier_reliability: dict[str, float] = field(default_factory=dict)
    supplier_seen_deliveries: dict[str, int] = field(default_factory=dict)
    stockouts: dict[str, int] = field(default_factory=dict)
    last_mode: str = "balanced"
    last_scenario: str = "baseline"
    last_menu_day: int = 0
    recent_cash: list[float] = field(default_factory=list)


def _loads(text: str) -> dict[str, Any]:
    if orjson is not None:
        return orjson.loads(text)
    return json.loads(text)


def _dumps(data: dict[str, Any]) -> str:
    if orjson is not None:
        return orjson.dumps(data).decode("utf-8")
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def parse_notes(notes: str | None) -> Memory:
    if not notes:
        return Memory()
    text = notes.strip()
    if not text:
        return Memory()
    try:
        data = _loads(text)
    except Exception:
        return Memory()
    if not isinstance(data, dict):
        return Memory()
    return Memory(
        version=int(data.get("v", data.get("version", 1)) or 1),
        last_day=int(data.get("d", data.get("last_day", 0)) or 0),
        covers_ema=float(data.get("ce", data.get("covers_ema", 90.0)) or 90.0),
        revenue_ema=float(data.get("re", data.get("revenue_ema", 1800.0)) or 1800.0),
        demand_by_dow={str(k): float(v) for k, v in dict(data.get("dow", {})).items()},
        supplier_reliability={str(k): float(v) for k, v in dict(data.get("sr", {})).items()},
        supplier_seen_deliveries={str(k): int(v) for k, v in dict(data.get("sd", {})).items()},
        stockouts={str(k): int(v) for k, v in dict(data.get("so", {})).items()},
        last_mode=str(data.get("m", "balanced")),
        last_scenario=str(data.get("sc", "baseline")),
        last_menu_day=int(data.get("md", 0) or 0),
        recent_cash=[float(v) for v in list(data.get("cash", []))[-7:]],
    )


def update_memory_from_state(memory: Memory, state: GameState) -> Memory:
    summary = state.service_summary
    covers = float(summary.get("total_covers") or sum(summary.get("hourly_covers", []) or []) or 0.0)
    if covers > 0:
        memory.covers_ema = 0.35 * covers + 0.65 * memory.covers_ema
        previous = memory.demand_by_dow.get(state.day_of_week, covers)
        memory.demand_by_dow[state.day_of_week] = 0.45 * covers + 0.55 * previous
    revenue = float(summary.get("total_revenue") or state.yesterday_revenue or 0.0)
    if revenue > 0:
        memory.revenue_ema = 0.35 * revenue + 0.65 * memory.revenue_ema
    unavailable = summary.get("dishes_unavailable_at") or {}
    if isinstance(unavailable, dict):
        for dish in unavailable:
            memory.stockouts[str(dish)] = memory.stockouts.get(str(dish), 0) + 1
    memory.recent_cash = [*memory.recent_cash, float(state.cash)][-7:]
    memory.last_day = state.day
    return memory


def build_notes(
    memory: Memory,
    state: GameState,
    *,
    mode: str,
    scenario: str,
    actions: list[dict[str, Any]],
    menu_changed: bool = False,
) -> str:
    memory.last_mode = mode
    memory.last_scenario = scenario
    if menu_changed:
        memory.last_menu_day = state.day

    order_notes = []
    for action in actions:
        if action.get("tool") == "place_order":
            args = action.get("args", {})
            order_notes.append(
                [
                    str(args.get("ingredient", ""))[:18],
                    str(args.get("supplier", ""))[:18],
                    round(float(args.get("quantity_kg", 0.0) or 0.0), 1),
                ],
            )

    data = {
        "v": memory.version,
        "d": state.day,
        "ce": round(memory.covers_ema, 1),
        "re": round(memory.revenue_ema, 1),
        "dow": {k: round(v, 1) for k, v in sorted(memory.demand_by_dow.items())[-7:]},
        "sr": {k: round(v, 3) for k, v in sorted(memory.supplier_reliability.items())},
        "sd": memory.supplier_seen_deliveries,
        "so": dict(sorted(memory.stockouts.items(), key=lambda item: item[1], reverse=True)[:12]),
        "m": memory.last_mode,
        "sc": memory.last_scenario,
        "md": memory.last_menu_day,
        "cash": [round(c, 0) for c in memory.recent_cash[-7:]],
        "ord": order_notes[:8],
    }
    text = _dumps(data)
    if len(text) <= TARGET_NOTES_LIMIT:
        return text

    compact = asdict(memory)
    compact["supplier_reliability"] = dict(
        sorted(memory.supplier_reliability.items(), key=lambda item: item[1])[:12],
    )
    compact["stockouts"] = dict(sorted(memory.stockouts.items(), key=lambda item: item[1], reverse=True)[:8])
    text = _dumps({"v": 1, "d": state.day, "m": mode, "sc": scenario, "mem": compact})
    return text[:NOTES_LIMIT]
