"""Deterministic optimizers for constrained restaurant decisions."""

from __future__ import annotations

from typing import Any


def optimize_order_candidates(
    order_candidates: list[dict[str, Any]],
    budget: float,
) -> list[dict[str, Any]] | None:
    """Choose the best feasible order set deterministically.

    This solves a small grouped knapsack: at most one supplier option per
    ingredient, total cost under today's budget, maximal operational value.
    """
    if budget <= 0 or not order_candidates:
        return None

    budget_cents = max(0, int(round(budget * 100)))
    groups = _candidate_groups(order_candidates)
    best_value = 0
    best_cost = 0
    best_selected: tuple[dict[str, Any], ...] = ()

    def search(index: int, spent: int, value: int, selected: tuple[dict[str, Any], ...]) -> None:
        nonlocal best_value, best_cost, best_selected
        if spent > budget_cents:
            return
        if index == len(groups):
            key = (value, -spent, _tie_breaker(selected))
            best_key = (best_value, -best_cost, _tie_breaker(best_selected))
            if key > best_key:
                best_value = value
                best_cost = spent
                best_selected = selected
            return

        search(index + 1, spent, value, selected)
        for item in groups[index]:
            cost = max(0, int(round(float(item["cost"]) * 100)))
            search(index + 1, spent + cost, value + _candidate_value(item), selected + (item,))

    search(0, 0, 0, ())
    selected = list(best_selected)
    if not selected:
        return []
    selected.sort(key=lambda item: (not item["urgent"], item["coverage_days"], item["eta_days"], item["cost"]))
    return selected


def _candidate_groups(order_candidates: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in order_candidates:
        grouped.setdefault(str(item["ingredient"]), []).append(item)
    return [
        sorted(items, key=lambda item: (float(item.get("cost") or 0), str(item.get("supplier") or "")))
        for _, items in sorted(grouped.items())
    ]


def _tie_breaker(selected: tuple[dict[str, Any], ...]) -> tuple:
    return tuple(
        sorted(
            (
                str(item.get("ingredient") or ""),
                str(item.get("supplier") or ""),
                round(float(item.get("qty") or 0), 3),
            )
            for item in selected
        )
    )


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
    late_penalty = max(0.0, eta_days - coverage_days - 0.5) * 900.0
    timely_bonus = max(0.0, coverage_days + 1.0 - eta_days) * 220.0
    volume_bonus = min(need_per_day, 30.0) * 30.0
    cost_penalty = cost * 2.0

    value = (
        stockout_bonus
        + urgent_bonus
        + coverage_gap * 1_500.0
        + lead_bonus
        + timely_bonus
        + volume_bonus
        - late_penalty
        - cost_penalty
    )
    return max(1, int(round(value)))
