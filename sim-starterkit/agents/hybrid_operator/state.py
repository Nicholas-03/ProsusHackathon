"""Observation parsing and normalized game state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import DEFAULT_STAFF_COST


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class IngredientAmount:
    ingredient: str
    quantity_kg: float


@dataclass(frozen=True)
class InventoryBatch:
    quantity_kg: float
    expires_in_days: int


@dataclass
class IngredientStock:
    ingredient: str
    total_kg: float = 0.0
    shelf_life_days: int = 7
    batches: list[InventoryBatch] = field(default_factory=list)

    @property
    def fresh_kg(self) -> float:
        return sum(b.quantity_kg for b in self.batches if b.expires_in_days > 1)

    @property
    def urgent_kg(self) -> float:
        return sum(b.quantity_kg for b in self.batches if b.expires_in_days <= 1)


@dataclass
class MenuDish:
    name: str
    category: str = ""
    base_price: float = 0.0
    current_price: float = 0.0
    is_active: bool = False
    ingredients: list[IngredientAmount] = field(default_factory=list)

    @property
    def price_ratio(self) -> float:
        if self.base_price <= 0:
            return 1.0
        return self.current_price / self.base_price


@dataclass
class Supplier:
    name: str
    lead_time_days: int = 1
    delivery_days: list[str] = field(default_factory=list)
    min_order_kg: float = 1.0
    ingredients: dict[str, float] = field(default_factory=dict)


@dataclass
class PendingOrder:
    supplier: str
    ingredient: str
    quantity_kg: float
    delivery_day: int = 0


@dataclass
class DeliveryRecord:
    supplier: str
    ingredient: str
    ordered_kg: float
    delivered_kg: float
    order_day: int = 0
    delivery_day: int = 0
    on_time: bool = True


@dataclass
class GameState:
    day: int = 1
    day_of_week: str = "Monday"
    days_remaining: int = 30
    cash: float = 0.0
    yesterday_revenue: float = 0.0
    yesterday_total_costs: float = 0.0
    cost_breakdown: dict[str, Any] = field(default_factory=dict)
    inventory: dict[str, IngredientStock] = field(default_factory=dict)
    service_summary: dict[str, Any] = field(default_factory=dict)
    suppliers: dict[str, Supplier] = field(default_factory=dict)
    pending_orders: list[PendingOrder] = field(default_factory=list)
    delivery_history: list[DeliveryRecord] = field(default_factory=list)
    menu_book: dict[str, MenuDish] = field(default_factory=dict)
    active_menu: list[str] = field(default_factory=list)
    staff_level: int = 8
    staff_cost_per_person: float = DEFAULT_STAFF_COST
    reputation_band: str = "Very Good"
    recent_reviews: list[dict[str, Any]] = field(default_factory=list)
    customer_trend: str = "Stable"
    weather_today: str = "cloudy"
    weather_forecast: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    notes: str = ""
    tick_budget_ms: int = 30000
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_observation(cls, observation: dict[str, Any] | None, day: int | None = None) -> "GameState":
        obs = observation or {}
        menu_book: dict[str, MenuDish] = {}
        for dish_raw in as_list(obs.get("menu_book")):
            dish = as_dict(dish_raw)
            name = str(dish.get("name", "")).strip()
            if not name:
                continue
            ingredients = []
            for ing_raw in as_list(dish.get("ingredients")):
                ing = as_dict(ing_raw)
                ing_name = str(ing.get("ingredient", "")).strip()
                if ing_name:
                    ingredients.append(
                        IngredientAmount(
                            ingredient=ing_name,
                            quantity_kg=as_float(ing.get("quantity_kg")),
                        ),
                    )
            base_price = as_float(dish.get("base_price"))
            current_price = as_float(dish.get("current_price"), base_price)
            menu_book[name] = MenuDish(
                name=name,
                category=str(dish.get("category", "")),
                base_price=base_price,
                current_price=current_price or base_price,
                is_active=bool(dish.get("is_active", False)),
                ingredients=ingredients,
            )

        active_menu = [str(d) for d in as_list(obs.get("active_menu")) if str(d) in menu_book]
        if not active_menu:
            active_menu = [name for name, dish in menu_book.items() if dish.is_active]

        inventory = {}
        for inv_raw in as_list(obs.get("inventory")):
            inv = as_dict(inv_raw)
            ingredient = str(inv.get("ingredient", "")).strip()
            if not ingredient:
                continue
            batches = []
            for batch_raw in as_list(inv.get("batches")):
                batch = as_dict(batch_raw)
                batches.append(
                    InventoryBatch(
                        quantity_kg=as_float(batch.get("quantity_kg")),
                        expires_in_days=as_int(batch.get("expires_in_days")),
                    ),
                )
            total = as_float(inv.get("total_kg"))
            if total <= 0 and batches:
                total = sum(b.quantity_kg for b in batches)
            inventory[ingredient] = IngredientStock(
                ingredient=ingredient,
                total_kg=total,
                shelf_life_days=as_int(inv.get("shelf_life_days"), 7),
                batches=batches,
            )

        suppliers = {}
        for sup_raw in as_list(obs.get("supplier_catalog")):
            sup = as_dict(sup_raw)
            name = str(sup.get("name", "")).strip()
            if not name:
                continue
            ingredients = {
                str(ingredient): as_float(price)
                for ingredient, price in as_dict(sup.get("ingredients")).items()
                if str(ingredient)
            }
            suppliers[name] = Supplier(
                name=name,
                lead_time_days=max(0, as_int(sup.get("lead_time_days"), 1)),
                delivery_days=[str(d) for d in as_list(sup.get("delivery_days"))],
                min_order_kg=max(0.1, as_float(sup.get("min_order_kg"), 1.0)),
                ingredients=ingredients,
            )

        pending_orders = []
        for po_raw in as_list(obs.get("pending_orders")):
            po = as_dict(po_raw)
            supplier = str(po.get("supplier", "")).strip()
            ingredient = str(po.get("ingredient", "")).strip()
            if supplier and ingredient:
                pending_orders.append(
                    PendingOrder(
                        supplier=supplier,
                        ingredient=ingredient,
                        quantity_kg=as_float(po.get("quantity_kg")),
                        delivery_day=as_int(po.get("delivery_day")),
                    ),
                )

        delivery_history = []
        for rec_raw in as_list(obs.get("delivery_history")):
            rec = as_dict(rec_raw)
            supplier = str(rec.get("supplier", "")).strip()
            ingredient = str(rec.get("ingredient", "")).strip()
            if supplier and ingredient:
                delivery_history.append(
                    DeliveryRecord(
                        supplier=supplier,
                        ingredient=ingredient,
                        ordered_kg=as_float(rec.get("ordered_kg")),
                        delivered_kg=as_float(rec.get("delivered_kg")),
                        order_day=as_int(rec.get("order_day")),
                        delivery_day=as_int(rec.get("delivery_day")),
                        on_time=bool(rec.get("on_time", True)),
                    ),
                )

        obs_day = as_int(obs.get("day"), day or 1)
        return cls(
            day=day or obs_day,
            day_of_week=str(obs.get("day_of_week", "Monday")),
            days_remaining=as_int(obs.get("days_remaining"), max(0, 31 - obs_day)),
            cash=as_float(obs.get("cash")),
            yesterday_revenue=as_float(obs.get("yesterday_revenue")),
            yesterday_total_costs=as_float(obs.get("yesterday_total_costs")),
            cost_breakdown=as_dict(obs.get("cost_breakdown")),
            inventory=inventory,
            service_summary=as_dict(obs.get("service_summary")),
            suppliers=suppliers,
            pending_orders=pending_orders,
            delivery_history=delivery_history,
            menu_book=menu_book,
            active_menu=active_menu,
            staff_level=as_int(obs.get("staff_level"), 8),
            staff_cost_per_person=as_float(obs.get("staff_cost_per_person"), DEFAULT_STAFF_COST),
            reputation_band=str(obs.get("reputation_band", "Very Good")),
            recent_reviews=[as_dict(r) for r in as_list(obs.get("recent_reviews"))],
            customer_trend=str(obs.get("customer_trend", "Stable")),
            weather_today=str(obs.get("weather_today", "cloudy")).lower(),
            weather_forecast=[str(w).lower() for w in as_list(obs.get("weather_forecast"))],
            alerts=[str(a) for a in as_list(obs.get("alerts"))],
            notes=str(obs.get("notes", "") or ""),
            tick_budget_ms=as_int(obs.get("tick_budget_ms"), 30000),
            raw=obs,
        )

    def pending_by_ingredient(self) -> dict[str, float]:
        pending: dict[str, float] = {}
        for order in self.pending_orders:
            pending[order.ingredient] = pending.get(order.ingredient, 0.0) + order.quantity_kg
        return pending

    def dish(self, name: str) -> MenuDish | None:
        return self.menu_book.get(name)

    def active_dishes(self) -> list[MenuDish]:
        return [self.menu_book[name] for name in self.active_menu if name in self.menu_book]
