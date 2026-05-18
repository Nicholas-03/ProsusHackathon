"""Shared constants for the hybrid operator agent."""

FIXED_DAILY_COST = 300.0
DEFAULT_STAFF_COST = 120.0
MIN_STAFF = 3
MAX_STAFF = 15
MIN_MENU_DISHES = 5
MAX_MARKETING = 500.0
NOTES_LIMIT = 4000
TARGET_NOTES_LIMIT = 3500

WALKOUT_SCORE = {
    "None": 0,
    "Few": 1,
    "Some": 2,
    "Many": 3,
}

REPUTATION_SCORE = {
    "Poor": 0,
    "Fair": 1,
    "Good": 2,
    "Very Good": 3,
    "Excellent": 4,
}

DAY_INDEX = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}

INDEX_DAY = {v: k for k, v in DAY_INDEX.items()}

WEATHER_FACTOR = {
    "sunny": 1.08,
    "cloudy": 1.00,
    "rainy": 0.92,
    "stormy": 0.82,
}

DOW_FACTOR = {
    "Monday": 0.90,
    "Tuesday": 0.95,
    "Wednesday": 1.00,
    "Thursday": 1.05,
    "Friday": 1.15,
    "Saturday": 1.25,
    "Sunday": 1.10,
}

ALLOWED_TOOLS = {
    "place_order",
    "set_staff_level",
    "set_menu",
    "set_price",
    "set_marketing_spend",
    "run_happy_hour",
    "offer_daily_special",
    "save_notes",
}
