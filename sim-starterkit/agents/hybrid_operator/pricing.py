"""Conservative pricing adjustments."""

from __future__ import annotations

from .economics import dish_margin_ratio, minimum_profitable_price
from .metrics import Metrics
from .planner import StrategyPlan
from .risk import RiskAssessment
from .scenario import ScenarioSignal
from .state import GameState, MenuDish


def _stock_safe_for_dish(dish: MenuDish, metrics: Metrics, threshold: float = 1.2) -> bool:
    if not dish.ingredients:
        return True
    return all(metrics.ingredient_days_cover.get(ing.ingredient, 2.0) >= threshold for ing in dish.ingredients)


def make_pricing_actions(
    state: GameState,
    metrics: Metrics,
    risk: RiskAssessment,
    scenario: ScenarioSignal,
    plan: StrategyPlan,
    menu: list[str] | None = None,
) -> list[dict]:
    if not state.menu_book:
        return []
    actions: list[dict] = []
    active_names = menu or state.active_menu
    active = [state.menu_book[name] for name in active_names if name in state.menu_book]
    if not active:
        return []

    sold = metrics.dish_sales
    sorted_active = sorted(active, key=lambda dish: sold.get(dish.name, 0.0), reverse=True)

    if risk.cash_risk not in {"high", "critical"} and (
        plan.pricing_intent == "lower" or risk.reputation_risk in {"high", "critical"}
    ):
        for dish in sorted(active, key=lambda d: d.price_ratio, reverse=True):
            if len(actions) >= 3:
                break
            if dish.base_price <= 0:
                continue
            profitable_floor = min(dish.base_price, minimum_profitable_price(state, dish, target_food_cost=0.38))
            target = max(profitable_floor, dish.base_price * 0.96, dish.current_price * 0.97)
            if dish.price_ratio > 1.06 and target < dish.current_price - 0.05:
                actions.append({"tool": "set_price", "args": {"dish": dish.name, "price": round(target, 2)}})
        return actions

    if (risk.inventory_risk in {"high", "critical"} and risk.cash_risk not in {"high", "critical"}) or (
        risk.service_risk == "critical" and risk.cash_risk == "low"
    ):
        return []

    should_raise = (
        plan.pricing_intent in {"raise_selective", "raise_broad"}
        or scenario.label == "cost_pressure"
        or risk.cash_risk in {"medium", "high", "critical"}
    )
    if not should_raise:
        return []

    max_changes = 3 if risk.cash_risk in {"high", "critical"} or plan.pricing_intent == "raise_broad" else 2
    ranked = sorted(
        sorted_active,
        key=lambda dish: (
            sold.get(dish.name, 1.0),
            -dish_margin_ratio(state, dish),
            dish.base_price,
        ),
        reverse=True,
    )
    for dish in ranked:
        if len(actions) >= max_changes:
            break
        stock_threshold = 0.55 if risk.cash_risk in {"high", "critical"} else 1.2
        if dish.base_price <= 0 or not _stock_safe_for_dish(dish, metrics, stock_threshold):
            continue
        if sold and sold.get(dish.name, 0.0) <= 0:
            continue
        raise_factor = 1.03
        if plan.mode == "premium":
            raise_factor = 1.05
        if scenario.label == "cost_pressure":
            raise_factor = 1.06
        if risk.cash_risk in {"high", "critical"}:
            raise_factor = max(raise_factor, 1.04)
        profitable_target = minimum_profitable_price(state, dish, target_food_cost=0.30)
        cash_target = dish.base_price * (1.06 if risk.cash_risk in {"high", "critical"} else 1.02)
        target = max(dish.current_price * raise_factor, profitable_target, cash_target)
        target = min(dish.base_price * 1.18, target)
        if risk.reputation_risk in {"high", "critical"} and risk.cash_risk not in {"high", "critical"}:
            target = min(target, dish.base_price * 1.08)
        if target > dish.current_price + 0.10 and dish.price_ratio < 1.18:
            actions.append({"tool": "set_price", "args": {"dish": dish.name, "price": round(target, 2)}})
    return actions
