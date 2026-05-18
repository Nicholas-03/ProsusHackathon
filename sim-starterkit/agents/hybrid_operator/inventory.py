"""Inventory ordering decisions."""

from __future__ import annotations

from .economics import ingredient_margin_weight
from .finance import available_order_budget
from .memory import Memory
from .metrics import Metrics
from .optimization import OrderCandidate, select_order_candidates
from .planner import StrategyPlan
from .risk import RiskAssessment
from .scenario import ScenarioSignal
from .state import GameState
from .suppliers import choose_supplier


ORDER_CAP_KG = {
    "Flour": 10.0,
    "Tomato Sauce": 5.0,
    "Mozzarella": 5.0,
    "Fresh Pasta": 8.0,
    "Cream": 5.0,
    "Mushrooms": 5.0,
    "Chicken": 5.0,
    "Lettuce": 5.0,
    "Pepperoni": 5.0,
    "Salmon": 3.0,
}

REORDER_POINT_KG = {
    "Flour": 6.0,
    "Tomato Sauce": 3.0,
    "Mozzarella": 3.0,
    "Fresh Pasta": 4.0,
    "Cream": 2.0,
    "Mushrooms": 2.0,
    "Chicken": 3.0,
    "Lettuce": 2.0,
    "Pepperoni": 2.0,
    "Salmon": 2.0,
}

ORDER_QTY_KG = {
    "Flour": 8.0,
    "Tomato Sauce": 5.0,
    "Mozzarella": 5.0,
    "Fresh Pasta": 8.0,
    "Cream": 5.0,
    "Mushrooms": 5.0,
    "Chicken": 5.0,
    "Lettuce": 5.0,
    "Pepperoni": 5.0,
    "Salmon": 5.0,
}


def _target_coverage(plan: StrategyPlan, scenario: ScenarioSignal, risk: RiskAssessment, days_remaining: int) -> float:
    if plan.inventory_intent == "emergency":
        target = 1.25
    elif plan.inventory_intent == "stockpile":
        target = 1.65
    elif plan.inventory_intent == "conserve":
        target = 0.75
    else:
        target = 1.05
    if scenario.label == "supply_shock":
        target += 0.2
    if scenario.label == "demand_spike":
        target += 0.15
    if risk.cash_risk in {"medium", "high", "critical"}:
        target -= 0.35
    if risk.cash_risk in {"high", "critical"}:
        target -= 0.75
    if risk.cash_risk == "critical":
        target = min(target, 0.85)
    elif risk.cash_risk == "high":
        target = min(target, 1.15)
    elif risk.cash_risk == "medium":
        target = min(target, 1.25)
    if days_remaining <= 5:
        target = min(target, 1.0)
    elif days_remaining <= 10:
        target = min(target, 1.4)
    return max(0.55, min(3.0, target))


def _stockout_ingredients(state: GameState, metrics: Metrics) -> set[str]:
    ingredients: set[str] = set()
    for dish_name in metrics.stockout_dishes:
        dish = state.menu_book.get(dish_name)
        if dish:
            ingredients.update(ing.ingredient for ing in dish.ingredients)
    return ingredients


def _usable_stock(state: GameState, ingredient: str, risk: RiskAssessment) -> float:
    stock = state.inventory.get(ingredient)
    if not stock:
        return 0.0
    if risk.waste_risk == "high":
        return stock.fresh_kg + stock.urgent_kg * 0.35
    return stock.fresh_kg + stock.urgent_kg * 0.65


def build_order_candidates(
    state: GameState,
    memory: Memory,
    metrics: Metrics,
    risk: RiskAssessment,
    scenario: ScenarioSignal,
    plan: StrategyPlan,
) -> list[OrderCandidate]:
    target_days = _target_coverage(plan, scenario, risk, state.days_remaining)
    pending = state.pending_by_ingredient()
    stockout_ingredients = _stockout_ingredients(state, metrics)
    candidates: list[OrderCandidate] = []
    selected_suppliers: set[str] = set()
    tracked_ingredients = set(metrics.ingredient_daily_need) | set(REORDER_POINT_KG)

    for ingredient in sorted(tracked_ingredients):
        daily_need = metrics.ingredient_daily_need.get(ingredient, 0.0)
        if daily_need <= 0:
            if ingredient not in stockout_ingredients:
                continue
            daily_need = 1.0
        if ingredient not in metrics.ingredient_daily_need and ingredient not in stockout_ingredients:
            continue
        usable = _usable_stock(state, ingredient, risk)
        effective = usable + pending.get(ingredient, 0.0)
        reorder_point = REORDER_POINT_KG.get(ingredient, max(1.5, daily_need * max(0.65, target_days)))
        order_qty = ORDER_QTY_KG.get(ingredient, max(2.5, daily_need * max(0.7, target_days)))
        urgent = ingredient in stockout_ingredients or effective < reorder_point * 0.45
        margin_weight = ingredient_margin_weight(state, metrics, ingredient)
        if state.days_remaining <= 3 and not urgent:
            continue
        if risk.cash_risk == "critical" and not urgent:
            continue
        if risk.cash_risk == "high" and not urgent and margin_weight < 18.0:
            continue
        if risk.cash_risk == "medium" and not urgent and margin_weight < 10.0:
            continue
        if not urgent and effective >= reorder_point:
            continue
        if pending.get(ingredient, 0.0) >= order_qty * 0.75 and not urgent:
            continue

        desired = order_qty
        if urgent:
            urgent_multiplier = 0.65 if risk.cash_risk == "critical" else 0.85 if risk.cash_risk == "high" else 1.0
            desired = max(desired * urgent_multiplier, reorder_point - effective)

        choice = choose_supplier(
            state,
            memory,
            ingredient,
            intent=plan.supplier_intent,
            diversify_from=selected_suppliers if scenario.label == "supply_shock" else None,
        )
        if not choice:
            continue

        supplier = choice.supplier
        qty = max(supplier.min_order_kg, desired)
        cap = ORDER_CAP_KG.get(ingredient, 5.0)
        if scenario.label == "demand_spike" and risk.cash_risk == "low":
            cap *= 1.35
        if scenario.label == "supply_shock" and risk.cash_risk == "low":
            cap *= 1.25
        if risk.cash_risk == "critical":
            cap *= 0.7
        stock = state.inventory.get(ingredient)
        shelf_life = stock.shelf_life_days if stock else 7
        perishable_cap = daily_need * (2.4 if shelf_life <= 5 else 3.3 if shelf_life <= 8 else 4.5)
        if risk.waste_risk in {"medium", "high"}:
            perishable_cap *= 0.75
        if risk.cash_risk == "critical":
            perishable_cap *= 0.55
        elif risk.cash_risk == "high":
            perishable_cap *= 0.70
        if state.days_remaining <= 7:
            perishable_cap = min(perishable_cap, daily_need * max(1.0, state.days_remaining / 2.0))
        qty = min(qty, max(supplier.min_order_kg, perishable_cap))
        qty = min(qty, max(supplier.min_order_kg, cap))
        qty = round(max(supplier.min_order_kg, qty) * 2.0) / 2.0

        deficit = max(0.0, reorder_point - effective) / max(reorder_point, 0.1)
        priority = 2.0 + deficit * 10.0
        if urgent:
            priority += 12.0
        if ingredient in stockout_ingredients:
            priority += 20.0
        if choice.delivery_days <= 1:
            priority += 1.2
        priority += choice.reliability * 2.0
        priority += min(18.0, margin_weight / 8.0)
        if risk.cash_risk in {"high", "critical"}:
            priority += max(0.0, 10.0 - choice.price)

        candidates.append(
            OrderCandidate(
                supplier=supplier.name,
                ingredient=ingredient,
                quantity_kg=qty,
                unit_price=choice.price,
                priority=priority,
                delivery_days=choice.delivery_days,
                reliability=choice.reliability,
            ),
        )
        selected_suppliers.add(supplier.name)
    return candidates


def make_inventory_actions(
    state: GameState,
    memory: Memory,
    metrics: Metrics,
    risk: RiskAssessment,
    scenario: ScenarioSignal,
    plan: StrategyPlan,
    planned_staff_level: int | None = None,
) -> list[dict]:
    candidates = build_order_candidates(state, memory, metrics, risk, scenario, plan)
    if not candidates:
        return []
    budget = available_order_budget(state, risk, metrics, staff_level=planned_staff_level)
    if budget <= 0:
        return []
    max_orders = 4
    if risk.cash_risk == "critical":
        max_orders = 1
    elif risk.cash_risk == "high":
        max_orders = 2
    elif risk.cash_risk == "medium":
        max_orders = 2
    selected = select_order_candidates(candidates, budget, max_orders=max_orders)
    return [
        {
            "tool": "place_order",
            "args": {
                "supplier": candidate.supplier,
                "ingredient": candidate.ingredient,
                "quantity_kg": round(candidate.quantity_kg, 1),
            },
        }
        for candidate in selected
    ]
