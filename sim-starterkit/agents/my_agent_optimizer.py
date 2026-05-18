"""Optional OR-Tools optimizers for constrained restaurant decisions."""

from __future__ import annotations

from typing import Any

from agents.my_agent_config import USE_ORTOOLS


def optimize_order_candidates(
    order_candidates: list[dict[str, Any]],
    budget: float,
) -> list[dict[str, Any]] | None:
    """Choose the best feasible order set with OR-Tools if available.

    The deterministic greedy planner is still the fallback. This helper only
    solves the bounded knapsack-style part: which supplier/ingredient orders
    deserve today's limited cash.
    """
    if not USE_ORTOOLS or budget <= 0 or not order_candidates:
        return None

    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return None

    model = cp_model.CpModel()
    variables = [model.NewBoolVar(f"order_{idx}") for idx, _ in enumerate(order_candidates)]

    cost_cents = [max(0, int(round(item["cost"] * 100))) for item in order_candidates]
    budget_cents = max(0, int(round(budget * 100)))
    model.Add(sum(cost_cents[idx] * variables[idx] for idx in range(len(variables))) <= budget_cents)

    by_ingredient: dict[str, list[int]] = {}
    for idx, item in enumerate(order_candidates):
        by_ingredient.setdefault(str(item["ingredient"]), []).append(idx)
    for indexes in by_ingredient.values():
        model.Add(sum(variables[idx] for idx in indexes) <= 1)

    values = [_candidate_value(item) for item in order_candidates]
    model.Maximize(sum(values[idx] * variables[idx] for idx in range(len(variables))))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 0.08
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)
    if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        return None

    selected = [
        item
        for idx, item in enumerate(order_candidates)
        if solver.BooleanValue(variables[idx])
    ]
    selected.sort(key=lambda item: (not item["urgent"], item["coverage_days"], item["eta_days"], item["cost"]))
    return selected


def _candidate_value(item: dict[str, Any]) -> int:
    coverage_days = float(item.get("coverage_days") or 0)
    target_days = float(item.get("target_days") or 0)
    eta_days = float(item.get("eta_days") or 0)
    need_per_day = float(item.get("need_per_day") or 0)
    cost = float(item.get("cost") or 0)

    coverage_gap = max(0.0, target_days - coverage_days)
    stockout_bonus = 8_000 if item.get("stockout") else 0
    urgent_bonus = 3_000 if item.get("urgent") else 0
    lead_bonus = max(0.0, 4.0 - eta_days) * 250.0
    volume_bonus = min(need_per_day, 30.0) * 30.0
    cost_penalty = cost * 2.0

    value = stockout_bonus + urgent_bonus + coverage_gap * 1_500.0 + lead_bonus + volume_bonus - cost_penalty
    return max(1, int(round(value)))
