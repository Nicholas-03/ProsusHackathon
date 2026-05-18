"""Small JSONL logger for RestBench runs."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def log_dir() -> Path | None:
    if os.getenv("RESTBENCH_DISABLE_LOGS", "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    return Path(os.getenv("RESTBENCH_LOG_DIR", "logs"))


def make_log_path(team_name: str, scenario: str, seed: int, game_id: str | None = None) -> Path | None:
    directory = log_dir()
    if directory is None:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    safe_team = _safe(team_name)
    safe_scenario = _safe(scenario)
    suffix = f"-{game_id[:8]}" if game_id else ""
    return directory / f"{safe_team}-{safe_scenario}-seed{seed}{suffix}.jsonl"


def append_jsonl(path: Path | None, event: str, **payload: Any) -> None:
    if path is None:
        return
    record = {"ts": round(time.time(), 3), "event": event, **payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")


def summarize_observation(observation: dict[str, Any]) -> dict[str, Any]:
    service = observation.get("service_summary") or {}
    return {
        "day": observation.get("day"),
        "day_of_week": observation.get("day_of_week"),
        "days_remaining": observation.get("days_remaining"),
        "cash": observation.get("cash"),
        "staff_level": observation.get("staff_level"),
        "reputation_band": observation.get("reputation_band"),
        "customer_trend": observation.get("customer_trend"),
        "weather_today": observation.get("weather_today"),
        "weather_forecast": observation.get("weather_forecast"),
        "alerts": observation.get("alerts", []),
        "inventory_kg": {
            item.get("ingredient"): round(float(item.get("total_kg") or 0), 2)
            for item in observation.get("inventory", [])
        },
        "pending_orders": observation.get("pending_orders", []),
        "service_summary": {
            "total_covers": service.get("total_covers"),
            "walkout_band": service.get("walkout_band"),
            "avg_wait_minutes": service.get("avg_wait_minutes"),
            "peak_wait_minutes": service.get("peak_wait_minutes"),
            "dishes_sold": service.get("dishes_sold", {}),
            "dishes_unavailable_at": service.get("dishes_unavailable_at", {}),
            "kitchen_bottleneck_hours": service.get("kitchen_bottleneck_hours", []),
        },
    }


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)[:80]
