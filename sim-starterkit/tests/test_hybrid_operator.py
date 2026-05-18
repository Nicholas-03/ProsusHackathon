from __future__ import annotations

from agents.hybrid_operator.inventory import make_inventory_actions
from agents.hybrid_operator.memory import build_notes, parse_notes
from agents.hybrid_operator.metrics import calculate_metrics, forecast_covers
from agents.hybrid_operator.planner import deterministic_plan
from agents.hybrid_operator.pricing import make_pricing_actions
from agents.hybrid_operator.risk import assess_risk
from agents.hybrid_operator.scenario import detect_scenario
from agents.hybrid_operator.staffing import target_staff_level
from agents.hybrid_operator.state import GameState, Supplier
from agents.hybrid_operator.suppliers import effective_delivery_days
from agents.hybrid_operator.validator import validate_actions


def sample_observation() -> dict:
    menu_book = [
        {
            "name": "Pizza Margherita",
            "category": "Pizza",
            "base_price": 14.5,
            "current_price": 14.5,
            "is_active": True,
            "ingredients": [
                {"ingredient": "Flour", "quantity_kg": 0.25},
                {"ingredient": "Tomato Sauce", "quantity_kg": 0.08},
                {"ingredient": "Mozzarella", "quantity_kg": 0.1},
            ],
        },
        {
            "name": "Spaghetti Carbonara",
            "category": "Pasta",
            "base_price": 16.0,
            "current_price": 16.0,
            "is_active": True,
            "ingredients": [
                {"ingredient": "Fresh Pasta", "quantity_kg": 0.22},
                {"ingredient": "Cream", "quantity_kg": 0.05},
            ],
        },
        {
            "name": "Chicken Parmesan",
            "category": "Main",
            "base_price": 19.0,
            "current_price": 19.0,
            "is_active": True,
            "ingredients": [
                {"ingredient": "Chicken", "quantity_kg": 0.24},
                {"ingredient": "Tomato Sauce", "quantity_kg": 0.06},
            ],
        },
        {
            "name": "Mushroom Risotto",
            "category": "Rice",
            "base_price": 17.0,
            "current_price": 17.0,
            "is_active": True,
            "ingredients": [{"ingredient": "Mushrooms", "quantity_kg": 0.12}],
        },
        {
            "name": "Grilled Salmon",
            "category": "Main",
            "base_price": 23.0,
            "current_price": 23.0,
            "is_active": True,
            "ingredients": [{"ingredient": "Salmon", "quantity_kg": 0.24}],
        },
        {
            "name": "Caesar Salad",
            "category": "Salad",
            "base_price": 12.0,
            "current_price": 12.0,
            "is_active": False,
            "ingredients": [{"ingredient": "Lettuce", "quantity_kg": 0.12}],
        },
    ]
    ingredients = [
        "Flour",
        "Tomato Sauce",
        "Mozzarella",
        "Fresh Pasta",
        "Cream",
        "Chicken",
        "Mushrooms",
        "Salmon",
        "Lettuce",
    ]
    return {
        "day": 4,
        "day_of_week": "Thursday",
        "days_remaining": 26,
        "cash": 9000,
        "yesterday_revenue": 1900,
        "yesterday_total_costs": 1450,
        "cost_breakdown": {"staff": 840, "fixed": 300, "marketing": 0, "waste": 0},
        "inventory": [
            {
                "ingredient": ingredient,
                "total_kg": 12.0 if ingredient != "Tomato Sauce" else 0.2,
                "shelf_life_days": 7,
                "batches": [
                    {
                        "quantity_kg": 12.0 if ingredient != "Tomato Sauce" else 0.2,
                        "expires_in_days": 4,
                    },
                ],
            }
            for ingredient in ingredients
        ],
        "service_summary": {
            "total_covers": 95,
            "total_revenue": 1900,
            "walkout_band": "None",
            "avg_wait_minutes": 4,
            "peak_wait_minutes": 12,
            "dishes_sold": {
                "Pizza Margherita": 20,
                "Spaghetti Carbonara": 20,
                "Chicken Parmesan": 18,
                "Mushroom Risotto": 18,
                "Grilled Salmon": 19,
            },
            "dishes_unavailable_at": {},
            "kitchen_bottleneck_hours": [],
        },
        "supplier_catalog": [
            {
                "name": "Fresh Farms NL",
                "lead_time_days": 1,
                "delivery_days": ["Monday", "Wednesday", "Friday"],
                "min_order_kg": 5.0,
                "ingredients": {"Tomato Sauce": 3.0, "Mushrooms": 4.2, "Chicken": 8.5, "Lettuce": 2.8},
            },
            {
                "name": "Wholesale Italia",
                "lead_time_days": 2,
                "delivery_days": ["Tuesday", "Thursday"],
                "min_order_kg": 5.0,
                "ingredients": {
                    "Flour": 1.2,
                    "Tomato Sauce": 2.8,
                    "Mozzarella": 5.5,
                    "Fresh Pasta": 2.9,
                    "Cream": 4.0,
                    "Salmon": 11.0,
                },
            },
        ],
        "pending_orders": [
            {
                "supplier": "Wholesale Italia",
                "ingredient": "Tomato Sauce",
                "quantity_kg": 8.0,
                "delivery_day": 5,
            },
        ],
        "delivery_history": [],
        "menu_book": menu_book,
        "active_menu": [
            "Pizza Margherita",
            "Spaghetti Carbonara",
            "Chicken Parmesan",
            "Mushroom Risotto",
            "Grilled Salmon",
        ],
        "staff_level": 7,
        "staff_cost_per_person": 120,
        "reputation_band": "Very Good",
        "recent_reviews": [{"stars": 4.3}],
        "customer_trend": "Stable",
        "weather_today": "cloudy",
        "weather_forecast": ["sunny", "rainy", "cloudy"],
        "alerts": [],
        "notes": "",
        "tick_budget_ms": 30000,
    }


def test_parse_notes_invalid_json_returns_default() -> None:
    memory = parse_notes("day 4: plain text")
    assert memory.version == 1
    assert memory.last_mode == "balanced"


def test_build_notes_stays_under_limit() -> None:
    state = GameState.from_observation(sample_observation(), 4)
    memory = parse_notes("")
    memory.stockouts = {f"dish-{idx}": idx for idx in range(200)}
    notes = build_notes(memory, state, mode="balanced", scenario="baseline", actions=[])
    assert len(notes) <= 4000


def test_effective_delivery_days_weekday_calendar() -> None:
    supplier = Supplier(
        name="Wednesday Only",
        lead_time_days=1,
        delivery_days=["Wednesday"],
        min_order_kg=5,
        ingredients={"Tomato Sauce": 3.0},
    )
    assert effective_delivery_days(supplier, current_day=4, current_day_of_week="Thursday") == 6


def test_validator_clamps_staff_price_and_drops_bad_order() -> None:
    state = GameState.from_observation(sample_observation(), 4)
    metrics = calculate_metrics(state, parse_notes(""))
    risk = assess_risk(state, metrics)
    actions = validate_actions(
        [
            {"tool": "set_staff_level", "args": {"level": 99}},
            {"tool": "set_price", "args": {"dish": "Pizza Margherita", "price": 999}},
            {"tool": "place_order", "args": {"supplier": "Nope", "ingredient": "Truffles", "quantity_kg": 1}},
        ],
        state,
        risk,
    )
    assert {"tool": "set_staff_level", "args": {"level": 15}} in actions
    price = next(action["args"]["price"] for action in actions if action["tool"] == "set_price")
    assert price == 17.4
    assert not any(action["tool"] == "place_order" for action in actions)


def test_inventory_respects_pending_orders() -> None:
    state = GameState.from_observation(sample_observation(), 4)
    memory = parse_notes("")
    metrics = calculate_metrics(state, memory)
    risk = assess_risk(state, metrics)
    scenario = detect_scenario(state, metrics, risk)
    plan = deterministic_plan(state, metrics, risk, scenario)
    actions = make_inventory_actions(state, memory, metrics, risk, scenario, plan)
    ordered_ingredients = {action["args"]["ingredient"] for action in actions}
    assert "Tomato Sauce" not in ordered_ingredients


def test_staffing_increases_after_many_walkouts() -> None:
    obs = sample_observation()
    obs["service_summary"]["walkout_band"] = "Many"
    obs["service_summary"]["avg_wait_minutes"] = 21
    state = GameState.from_observation(obs, 4)
    memory = parse_notes("")
    metrics = calculate_metrics(state, memory)
    risk = assess_risk(state, metrics)
    scenario = detect_scenario(state, metrics, risk)
    plan = deterministic_plan(state, metrics, risk, scenario)
    assert target_staff_level(state, metrics, risk, scenario, plan) > state.staff_level


def test_cash_critical_caps_staff_even_with_bad_service() -> None:
    obs = sample_observation()
    obs["cash"] = 900
    obs["staff_level"] = 10
    obs["yesterday_revenue"] = 400
    obs["yesterday_total_costs"] = 1800
    obs["service_summary"]["walkout_band"] = "Many"
    obs["service_summary"]["avg_wait_minutes"] = 24
    state = GameState.from_observation(obs, 4)
    memory = parse_notes("")
    metrics = calculate_metrics(state, memory)
    risk = assess_risk(state, metrics)
    scenario = detect_scenario(state, metrics, risk)
    plan = deterministic_plan(state, metrics, risk, scenario)

    assert risk.cash_risk == "critical"
    assert target_staff_level(state, metrics, risk, scenario, plan) <= 6


def test_inventory_limits_orders_under_cash_crisis() -> None:
    obs = sample_observation()
    obs["cash"] = 1150
    obs["staff_level"] = 8
    obs["yesterday_revenue"] = 350
    obs["yesterday_total_costs"] = 1700
    for item in obs["inventory"]:
        item["total_kg"] = 0.1
        item["batches"] = [{"quantity_kg": 0.1, "expires_in_days": 3}]
    state = GameState.from_observation(obs, 4)
    memory = parse_notes("")
    metrics = calculate_metrics(state, memory)
    risk = assess_risk(state, metrics)
    scenario = detect_scenario(state, metrics, risk)
    plan = deterministic_plan(state, metrics, risk, scenario)

    actions = make_inventory_actions(state, memory, metrics, risk, scenario, plan, planned_staff_level=5)

    assert risk.cash_risk == "critical"
    assert len([action for action in actions if action["tool"] == "place_order"]) <= 1


def test_pricing_does_not_discount_during_cash_stress() -> None:
    obs = sample_observation()
    obs["cash"] = 2300
    obs["yesterday_revenue"] = 700
    obs["yesterday_total_costs"] = 2300
    obs["reputation_band"] = "Fair"
    obs["recent_reviews"] = [{"stars": 2.6}]
    state = GameState.from_observation(obs, 4)
    memory = parse_notes("")
    metrics = calculate_metrics(state, memory)
    risk = assess_risk(state, metrics)
    scenario = detect_scenario(state, metrics, risk)
    plan = deterministic_plan(state, metrics, risk, scenario)

    actions = make_pricing_actions(state, metrics, risk, scenario, plan)

    assert risk.cash_risk in {"high", "critical"}
    assert actions
    assert all(action["args"]["price"] >= state.menu_book[action["args"]["dish"]].current_price for action in actions)


def test_scenario_keeps_reputation_as_symptom_without_alert() -> None:
    obs = sample_observation()
    obs["reputation_band"] = "Poor"
    obs["recent_reviews"] = [{"stars": 2.1}]
    obs["alerts"] = []
    state = GameState.from_observation(obs, 4)
    metrics = calculate_metrics(state, parse_notes(""))
    risk = assess_risk(state, metrics)

    scenario = detect_scenario(state, metrics, risk)

    assert scenario.label != "reputation_shock"
    assert "reputation_risk" in scenario.symptoms


def test_forecast_uncensors_walkout_demand() -> None:
    obs = sample_observation()
    obs["service_summary"]["total_covers"] = 70
    obs["service_summary"]["hourly_covers"] = []
    state_clean = GameState.from_observation(obs, 4)
    forecast_clean = forecast_covers(state_clean, parse_notes(""))

    obs["service_summary"]["walkout_band"] = "Many"
    obs["service_summary"]["avg_wait_minutes"] = 24
    obs["service_summary"]["peak_wait_minutes"] = 55
    state_censored = GameState.from_observation(obs, 4)
    forecast_censored = forecast_covers(state_censored, parse_notes(""))

    assert forecast_censored > forecast_clean


def test_scenario_detects_supply_alert() -> None:
    obs = sample_observation()
    obs["alerts"] = ["Fresh Farms NL supplier outage delayed all deliveries"]
    state = GameState.from_observation(obs, 4)
    memory = parse_notes("")
    metrics = calculate_metrics(state, memory)
    risk = assess_risk(state, metrics)
    scenario = detect_scenario(state, metrics, risk)
    assert scenario.label == "supply_shock"
