"""Menu selection and shortage replacement."""

from __future__ import annotations

from .constants import MIN_MENU_DISHES
from .economics import dish_ingredient_cost, dish_margin, dish_margin_ratio, ingredient_reference_prices
from .memory import Memory
from .metrics import Metrics, dish_is_stocked
from .planner import StrategyPlan
from .risk import RiskAssessment
from .state import GameState, MenuDish


def _dish_score(state: GameState, metrics: Metrics, dish: MenuDish, selected_categories: set[str]) -> float:
    prices = ingredient_reference_prices(state)
    score = metrics.dish_sales.get(dish.name, 2.0)
    if dish.name in state.active_menu:
        score += 8.0
    if dish_is_stocked(state, dish, portions=8.0):
        score += 7.0
    else:
        score -= 10.0
    if dish.category and dish.category not in selected_categories:
        score += 2.5
    margin = dish_margin(state, dish, prices)
    margin_ratio = dish_margin_ratio(state, dish, prices)
    ingredient_cost = dish_ingredient_cost(state, dish, prices)
    score += min(7.0, max(-5.0, margin / 2.5))
    score += min(4.0, max(-4.0, (margin_ratio - 0.55) * 10.0))
    score -= min(3.5, ingredient_cost / 6.0)
    return score


def choose_menu(
    state: GameState,
    memory: Memory,
    metrics: Metrics,
    risk: RiskAssessment,
    plan: StrategyPlan,
) -> list[str]:
    if not state.menu_book:
        return []
    unavailable = set(metrics.stockout_dishes)
    active = [name for name in state.active_menu if name in state.menu_book]
    should_replace = (
        plan.menu_intent == "replace_shortage"
        or len(active) < MIN_MENU_DISHES
        or bool(unavailable)
    )
    days_since_change = state.day - memory.last_menu_day if memory.last_menu_day else 99
    if not should_replace and days_since_change < 3:
        return active
    if not should_replace and plan.menu_intent not in {"diversify", "simplify"}:
        return active

    target_size = max(MIN_MENU_DISHES, len(active) or MIN_MENU_DISHES)
    if risk.cash_risk in {"high", "critical"}:
        target_size = MIN_MENU_DISHES
    elif plan.menu_intent == "diversify":
        target_size = min(max(target_size, 7), max(MIN_MENU_DISHES, len(state.menu_book)))
    elif plan.menu_intent == "simplify" or risk.inventory_risk in {"high", "critical"}:
        target_size = min(max(MIN_MENU_DISHES, target_size), 6)

    selected: list[str] = []
    categories: set[str] = set()
    for name in active:
        dish = state.menu_book[name]
        if name in unavailable and not dish_is_stocked(state, dish, portions=6.0):
            continue
        if risk.inventory_risk in {"high", "critical"} and not dish_is_stocked(state, dish, portions=5.0):
            continue
        if risk.cash_risk in {"high", "critical"} and dish_margin_ratio(state, dish) < 0.48:
            continue
        selected.append(name)
        if dish.category:
            categories.add(dish.category)

    candidates = sorted(
        state.menu_book.values(),
        key=lambda dish: _dish_score(state, metrics, dish, categories),
        reverse=True,
    )
    for dish in candidates:
        if len(selected) >= target_size:
            break
        if dish.name in selected:
            continue
        if risk.inventory_risk in {"high", "critical"} and not dish_is_stocked(state, dish, portions=5.0):
            continue
        if risk.cash_risk in {"high", "critical"} and dish_margin_ratio(state, dish) < 0.42:
            continue
        selected.append(dish.name)
        if dish.category:
            categories.add(dish.category)

    if len(selected) < MIN_MENU_DISHES:
        for dish in candidates:
            if dish.name not in selected:
                selected.append(dish.name)
            if len(selected) >= MIN_MENU_DISHES:
                break
    return selected[: max(MIN_MENU_DISHES, target_size)]


def make_menu_actions(
    state: GameState,
    memory: Memory,
    metrics: Metrics,
    risk: RiskAssessment,
    plan: StrategyPlan,
) -> tuple[list[dict], list[str]]:
    selected = choose_menu(state, memory, metrics, risk, plan)
    if not selected:
        return [], state.active_menu
    if selected == state.active_menu or set(selected) == set(state.active_menu):
        return [], state.active_menu
    return [{"tool": "set_menu", "args": {"dishes": selected}}], selected
