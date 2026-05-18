"""Supplier reliability and selection helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import DAY_INDEX, INDEX_DAY
from .memory import Memory
from .state import GameState, Supplier


@dataclass(frozen=True)
class SupplierChoice:
    supplier: Supplier
    score: float
    price: float
    reliability: float
    delivery_days: int


def effective_delivery_days(supplier: Supplier, current_day: int, current_day_of_week: str | None = None) -> int:
    if not supplier.delivery_days:
        return max(0, supplier.lead_time_days)
    start_index = DAY_INDEX.get(current_day_of_week or "", (current_day - 1) % 7)
    earliest_offset = max(0, supplier.lead_time_days)
    allowed = set(supplier.delivery_days)
    for offset in range(earliest_offset, earliest_offset + 15):
        weekday = INDEX_DAY[(start_index + offset) % 7]
        if weekday in allowed:
            return offset
    return earliest_offset + 7


def update_supplier_reliability(memory: Memory, state: GameState) -> Memory:
    seen = dict(memory.supplier_seen_deliveries)
    for record in state.delivery_history:
        key = f"{record.supplier}|{record.order_day}|{record.delivery_day}|{record.ingredient}"
        if seen.get(key):
            continue
        seen[key] = 1
        if record.ordered_kg <= 0:
            continue
        fill_rate = max(0.0, min(1.0, record.delivered_kg / record.ordered_kg))
        score = 0.75 * fill_rate + 0.25 * (1.0 if record.on_time else 0.0)
        previous = memory.supplier_reliability.get(record.supplier, 0.9)
        memory.supplier_reliability[record.supplier] = 0.35 * score + 0.65 * previous
    memory.supplier_seen_deliveries = dict(list(seen.items())[-160:])
    return memory


def reliability_for(memory: Memory, supplier_name: str, state: GameState | None = None) -> float:
    reliability = memory.supplier_reliability.get(supplier_name, 0.9)
    if state:
        alerts = " ".join(state.alerts).lower()
        if supplier_name.lower() in alerts:
            reliability -= 0.25
        elif any(word in alerts for word in ("supplier", "outage", "disruption", "strike", "delayed")):
            reliability -= 0.05
    return max(0.25, min(1.0, reliability))


def choose_supplier(
    state: GameState,
    memory: Memory,
    ingredient: str,
    *,
    intent: str = "balanced",
    diversify_from: set[str] | None = None,
) -> SupplierChoice | None:
    choices = []
    diversify_from = diversify_from or set()
    for supplier in state.suppliers.values():
        if ingredient not in supplier.ingredients:
            continue
        price = supplier.ingredients[ingredient]
        delivery = effective_delivery_days(supplier, state.day, state.day_of_week)
        reliability = reliability_for(memory, supplier.name, state)
        price_score = 1.0 / max(price, 0.1)
        delivery_score = 1.0 / (1.0 + delivery)
        diversify_bonus = 0.06 if supplier.name not in diversify_from else -0.05
        if intent == "cheapest":
            score = 0.58 * price_score + 0.22 * reliability + 0.20 * delivery_score
        elif intent == "reliable":
            score = 0.18 * price_score + 0.56 * reliability + 0.26 * delivery_score
        elif intent == "diversify":
            score = 0.24 * price_score + 0.42 * reliability + 0.24 * delivery_score + diversify_bonus
        else:
            score = 0.34 * price_score + 0.40 * reliability + 0.26 * delivery_score
        choices.append(SupplierChoice(supplier, score, price, reliability, delivery))
    if not choices:
        return None
    return max(choices, key=lambda choice: choice.score)
