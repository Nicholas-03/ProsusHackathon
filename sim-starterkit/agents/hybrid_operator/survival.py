"""Cash-first deterministic controller based on the known surviving baseline."""

from __future__ import annotations

from .metrics import Metrics, dish_is_stocked
from .risk import RiskAssessment
from .scenario import ScenarioSignal
from .state import GameState


REORDER_POINT = {
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

ORDER_QTY = {
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

SLOW_DAYS = {"Monday", "Tuesday", "Wednesday"}


def _target_staff(state: GameState, metrics: Metrics, risk: RiskAssessment, scenario: ScenarioSignal) -> int:
    target = 5
    if scenario.label == "demand_spike" and state.cash > 9000:
        target = 7
    elif metrics.predicted_covers > 150 and state.cash > 9000:
        target = 7
    elif metrics.predicted_covers > 105 and state.cash > 7000:
        target = 6

    if risk.cash_risk in {"high", "critical"}:
        target = min(target, 5)
    if risk.cash_risk == "critical" and state.cash < 900:
        target = 3
    return max(3, min(8, target))


def _fresh_stock(state: GameState) -> dict[str, float]:
    return {
        ingredient: stock.fresh_kg
        for ingredient, stock in state.inventory.items()
    }


def _cheapest_suppliers(state: GameState) -> dict[str, tuple[str, float, float]]:
    cheapest: dict[str, tuple[str, float, float]] = {}
    for supplier in state.suppliers.values():
        for ingredient, price in supplier.ingredients.items():
            if ingredient not in cheapest or price < cheapest[ingredient][1]:
                cheapest[ingredient] = (supplier.name, price, supplier.min_order_kg)
    return cheapest


def _pending_quantities(state: GameState) -> dict[str, float]:
    pending: dict[str, float] = {}
    for order in state.pending_orders:
        pending[order.ingredient] = pending.get(order.ingredient, 0.0) + order.quantity_kg
    return pending


def _best_daily_special(state: GameState, metrics: Metrics) -> str | None:
    active = [state.menu_book[name] for name in state.active_menu if name in state.menu_book]
    stocked = [dish for dish in active if dish_is_stocked(state, dish, portions=8.0)]
    candidates = stocked or active
    if not candidates:
        return None
    return max(candidates, key=lambda dish: (metrics.dish_sales.get(dish.name, 1.0), dish.current_price)).name


def make_cash_first_actions(
    state: GameState,
    metrics: Metrics,
    risk: RiskAssessment,
    scenario: ScenarioSignal,
) -> list[dict]:
    actions: list[dict] = []

    staff_target = _target_staff(state, metrics, risk, scenario)
    if staff_target != state.staff_level:
        actions.append({"tool": "set_staff_level", "args": {"level": staff_target}})

    inventory_safe = risk.inventory_risk not in {"high", "critical"}
    service_safe = risk.service_risk not in {"high", "critical"}
    if (
        state.day_of_week in SLOW_DAYS
        and state.cash > 3500
        and inventory_safe
        and service_safe
        and scenario.label not in {"demand_spike", "capacity_reduction"}
    ):
        actions.append({"tool": "run_happy_hour", "args": {}})

    special = _best_daily_special(state, metrics)
    if special and risk.cash_risk != "critical":
        actions.append({"tool": "offer_daily_special", "args": {"dish": special}})

    fresh = _fresh_stock(state)
    pending = _pending_quantities(state)
    cheapest = _cheapest_suppliers(state)

    reserve = 1500.0
    if risk.cash_risk == "high":
        reserve = 1900.0
    elif risk.cash_risk == "critical":
        reserve = 1200.0
    budget = state.cash - reserve
    if budget <= 0:
        return actions

    needs = []
    for ingredient, reorder in REORDER_POINT.items():
        if ingredient not in cheapest:
            continue
        effective = fresh.get(ingredient, 0.0) + pending.get(ingredient, 0.0)
        if effective >= reorder:
            continue
        supplier_name, price, min_order = cheapest[ingredient]
        qty = max(ORDER_QTY.get(ingredient, 5.0), min_order)
        cost = qty * price
        urgent = effective < reorder * 0.4
        if risk.cash_risk == "critical" and not urgent:
            continue
        needs.append((0 if urgent else 1, cost, ingredient, supplier_name, qty))

    needs.sort()
    spent = 0.0
    max_orders = 3 if risk.cash_risk == "low" else 2 if risk.cash_risk in {"medium", "high"} else 1
    for _, cost, ingredient, supplier_name, qty in needs:
        if len([action for action in actions if action["tool"] == "place_order"]) >= max_orders:
            break
        if spent + cost > budget:
            continue
        actions.append(
            {
                "tool": "place_order",
                "args": {
                    "supplier": supplier_name,
                    "ingredient": ingredient,
                    "quantity_kg": round(qty, 1),
                },
            },
        )
        spent += cost

    return actions
