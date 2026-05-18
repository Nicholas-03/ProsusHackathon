"""Configuration for the deterministic restaurant agent."""

from __future__ import annotations

import os

TEAM_NAME = os.getenv("RESTBENCH_TEAM_NAME", "la-forchetta-intelligente")

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

BASE_COVERS_BY_DAY = {
    "Monday": 84,
    "Tuesday": 88,
    "Wednesday": 94,
    "Thursday": 108,
    "Friday": 130,
    "Saturday": 142,
    "Sunday": 116,
}

WEATHER_DEMAND = {
    "sunny": 1.06,
    "cloudy": 1.00,
    "rainy": 0.92,
    "stormy": 0.78,
}

TREND_DEMAND = {
    "Declining": 0.88,
    "Stable": 1.00,
    "Growing": 1.12,
}

REPUTATION_PRICE_MULTIPLIER = {
    "Poor": 0.92,
    "Fair": 0.96,
    "Good": 1.00,
    "Very Good": 1.05,
    "Excellent": 1.08,
}

WALKOUT_PRESSURE = {
    "None": 0,
    "Few": 1,
    "Some": 2,
    "Many": 3,
}

SLOW_DAYS = {"Monday", "Tuesday", "Wednesday"}
BUSY_DAYS = {"Friday", "Saturday"}
