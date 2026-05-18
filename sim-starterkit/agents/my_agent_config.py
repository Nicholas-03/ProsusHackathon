"""Configuration for the deterministic RestBench agent."""

from __future__ import annotations

import os


TEAM_NAME = os.getenv("RESTBENCH_TEAM_NAME", "la-forchetta-deterministica")

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_INDEX = {name: index for index, name in enumerate(WEEKDAYS)}

STAFF_MIN = 3
STAFF_MAX = 15
STAFF_COST = 120.0
FIXED_DAILY_COST = 300.0

PRICE_MIN_MULTIPLIER = 0.80
PRICE_MAX_MULTIPLIER = 1.20

MENU_MIN_SIZE = 5
MENU_TARGET_SIZE = 8

DEFAULT_COVERS = 120.0
MAX_EXPECTED_COVERS = 285.0
MIN_EXPECTED_COVERS = 42.0

ORDER_SETUP_COST = 24.0
DAILY_CAPITAL_RATE = 0.002
WASTE_HOLDING_FACTOR = 0.32

MIN_CASH_RESERVE = 2100.0
EMERGENCY_CASH_RESERVE = 950.0
MAX_ORDER_BUDGET_FRACTION = 0.62

NOTES_PREFIX = "deterministic_eoq_v1:"
NOTES_LIMIT = 3900
