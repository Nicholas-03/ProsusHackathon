"""Summarize RestBench JSONL logs against the practical winning tips."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize recent agent JSONL logs")
    parser.add_argument("--team", default="la-forchetta-intelligente")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--latest", type=int, default=12)
    args = parser.parse_args()

    paths = _latest_game_logs(Path(args.log_dir), args.team, args.latest)
    if not paths:
        print("No matching game logs found.")
        return

    print(f"{'Scenario':<15} {'Seed':>4} {'Score':>8} {'Stock':>5} {'Dup':>4} {'Pend':>5} {'Alerts':>6} {'Notes':>5} {'Many':>5}  File")
    print("-" * 110)
    for path in sorted(paths, key=lambda item: item.name):
        summary = summarize_log(path)
        print(
            f"{summary['scenario']:<15} {summary['seed']:>4} {summary['score']:>8} "
            f"{summary['stockout_days']:>5} {summary['same_day_dups']:>4} "
            f"{summary['ordered_while_pending']:>5} {summary['alerts_seen']:>6} "
            f"{summary['notes_saved']:>5} {summary['many_walkout_days']:>5}  {path.name}"
        )


def summarize_log(path: Path) -> dict[str, Any]:
    scenario = "?"
    seed = "?"
    score = "-"
    stockout_days = 0
    same_day_dups = 0
    ordered_while_pending = 0
    alerts_seen = 0
    notes_saved = 0
    many_walkout_days = 0

    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        event = record.get("event")
        if event == "game_created":
            scenario = record.get("scenario", scenario)
            seed = record.get("seed", seed)
            alerts_seen += len((record.get("observation") or {}).get("alerts") or [])
        elif event == "actions_planned":
            decision = record.get("decision_summary") or {}
            actions = record.get("actions") or []
            if decision:
                same_day_dups += len(decision.get("duplicate_order_ingredients_same_day") or [])
                ordered_while_pending += len(decision.get("ordered_while_pending") or [])
                notes_saved += int(bool(decision.get("save_notes")))
            else:
                order_ingredients = [
                    (action.get("args") or {}).get("ingredient")
                    for action in actions
                    if action.get("tool") == "place_order"
                ]
                same_day_dups += len({item for item in order_ingredients if order_ingredients.count(item) > 1})
                notes_saved += int(any(action.get("tool") == "save_notes" for action in actions))
        elif event == "day_result":
            observation = record.get("observation") or {}
            service = observation.get("service_summary") or {}
            stockout_days += int(bool(service.get("dishes_unavailable_at")))
            many_walkout_days += int(service.get("walkout_band") == "Many")
            alerts_seen += len(observation.get("alerts") or [])
        elif event == "score":
            score_data = ((record.get("score") or {}).get("score") or {})
            if "total_score" in score_data:
                score = f"{score_data['total_score']:.0f}"

    return {
        "scenario": scenario,
        "seed": seed,
        "score": score,
        "stockout_days": stockout_days,
        "same_day_dups": same_day_dups,
        "ordered_while_pending": ordered_while_pending,
        "alerts_seen": alerts_seen,
        "notes_saved": notes_saved,
        "many_walkout_days": many_walkout_days,
    }


def _latest_game_logs(log_dir: Path, team: str, count: int) -> list[Path]:
    paths = []
    for path in log_dir.glob(f"{team}-*.jsonl"):
        parts = path.stem.split("-")
        if parts[-1] in {"seed7", "seed55", "seed99", "seed42", "seed88", "seed123"}:
            continue
        paths.append(path)
    return sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True)[:count]


if __name__ == "__main__":
    main()
