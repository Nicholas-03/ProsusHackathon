"""Small bounded optimization helpers with deterministic fallbacks."""

from __future__ import annotations

from dataclasses import dataclass

try:
    from ortools.sat.python import cp_model

    ORTOOLS_AVAILABLE = True
except Exception:  # pragma: no cover - optional fallback
    cp_model = None
    ORTOOLS_AVAILABLE = False


@dataclass(frozen=True)
class OrderCandidate:
    supplier: str
    ingredient: str
    quantity_kg: float
    unit_price: float
    priority: float
    delivery_days: int
    reliability: float

    @property
    def cost(self) -> float:
        return self.quantity_kg * self.unit_price


def greedy_select_orders(
    candidates: list[OrderCandidate],
    budget: float,
    *,
    max_orders: int | None = None,
) -> list[OrderCandidate]:
    if budget <= 0:
        return []
    selected: list[OrderCandidate] = []
    spent = 0.0
    ordered = sorted(
        candidates,
        key=lambda item: (
            item.priority / max(item.cost, 1.0),
            item.priority,
            item.reliability,
            -item.delivery_days,
        ),
        reverse=True,
    )
    used_ingredients: set[str] = set()
    for candidate in ordered:
        if max_orders is not None and len(selected) >= max_orders:
            break
        if candidate.ingredient in used_ingredients:
            continue
        if candidate.cost <= budget - spent:
            selected.append(candidate)
            spent += candidate.cost
            used_ingredients.add(candidate.ingredient)
    return selected


def select_order_candidates(
    candidates: list[OrderCandidate],
    budget: float,
    *,
    max_orders: int | None = None,
    time_limit_seconds: float = 0.4,
) -> list[OrderCandidate]:
    if budget <= 0 or not candidates:
        return []
    if not ORTOOLS_AVAILABLE or cp_model is None:
        return greedy_select_orders(candidates, budget, max_orders=max_orders)

    try:
        model = cp_model.CpModel()
        variables = [model.NewBoolVar(f"o_{idx}") for idx, _ in enumerate(candidates)]
        scaled_costs = [max(1, int(round(candidate.cost * 100))) for candidate in candidates]
        scaled_budget = int(round(budget * 100))
        model.Add(sum(var * cost for var, cost in zip(variables, scaled_costs, strict=True)) <= scaled_budget)
        if max_orders is not None:
            model.Add(sum(variables) <= max(0, int(max_orders)))

        by_ingredient: dict[str, list[int]] = {}
        for idx, candidate in enumerate(candidates):
            by_ingredient.setdefault(candidate.ingredient, []).append(idx)
        for indexes in by_ingredient.values():
            if len(indexes) > 1:
                model.Add(sum(variables[idx] for idx in indexes) <= 1)

        objective = []
        for idx, candidate in enumerate(candidates):
            value = candidate.priority * 1000 + candidate.reliability * 80 - candidate.delivery_days * 15
            objective.append(variables[idx] * int(round(value)))
        model.Maximize(sum(objective))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.num_search_workers = 1
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return greedy_select_orders(candidates, budget, max_orders=max_orders)
        return [
            candidate
            for variable, candidate in zip(variables, candidates, strict=True)
            if solver.BooleanValue(variable)
        ]
    except Exception:
        return greedy_select_orders(candidates, budget, max_orders=max_orders)
