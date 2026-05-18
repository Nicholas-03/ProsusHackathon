"""Menu and ingredient economics used by deterministic decisions."""

from __future__ import annotations

from .state import GameState, MenuDish


def ingredient_reference_prices(state: GameState) -> dict[str, float]:
    prices: dict[str, float] = {}
    for supplier in state.suppliers.values():
        for ingredient, price in supplier.ingredients.items():
            if price <= 0:
                continue
            current = prices.get(ingredient)
            if current is None or price < current:
                prices[ingredient] = float(price)
    return prices


def dish_ingredient_cost(state: GameState, dish: MenuDish, prices: dict[str, float] | None = None) -> float:
    reference = prices if prices is not None else ingredient_reference_prices(state)
    total = 0.0
    fallback_unit = max(1.0, dish.base_price * 0.12)
    for ingredient in dish.ingredients:
        unit_price = reference.get(ingredient.ingredient, fallback_unit)
        total += max(0.0, ingredient.quantity_kg) * unit_price
    return total


def dish_margin(state: GameState, dish: MenuDish, prices: dict[str, float] | None = None) -> float:
    price = dish.current_price or dish.base_price
    return price - dish_ingredient_cost(state, dish, prices)


def dish_margin_ratio(state: GameState, dish: MenuDish, prices: dict[str, float] | None = None) -> float:
    price = max(0.01, dish.current_price or dish.base_price)
    return dish_margin(state, dish, prices) / price


def dish_sales_signal(metrics: object, dish_name: str, default: float = 1.0) -> float:
    sales = getattr(metrics, "dish_sales", {}) or {}
    if not sales:
        return default
    return max(default, float(sales.get(dish_name, 0.0) or 0.0))


def ingredient_margin_weight(state: GameState, metrics: object, ingredient: str) -> float:
    prices = ingredient_reference_prices(state)
    weight = 0.0
    for dish in state.menu_book.values():
        if not any(part.ingredient == ingredient for part in dish.ingredients):
            continue
        demand = dish_sales_signal(metrics, dish.name)
        margin = dish_margin(state, dish, prices)
        ratio = dish_margin_ratio(state, dish, prices)
        weight += max(0.0, margin) * max(0.35, ratio) * demand
    return weight


def minimum_profitable_price(state: GameState, dish: MenuDish, target_food_cost: float = 0.32) -> float:
    ingredient_cost = dish_ingredient_cost(state, dish)
    if ingredient_cost <= 0:
        return dish.base_price
    return ingredient_cost / max(0.18, target_food_cost)
