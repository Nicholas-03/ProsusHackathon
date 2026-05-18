"""Configuration for the hybrid restaurant agent."""

from __future__ import annotations

import os

TEAM_NAME = os.getenv("RESTBENCH_TEAM_NAME", "la-forchetta-intelligente")

LLM_MODEL = os.getenv("AGENT_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.5"
LLM_BASE_URL = (
    os.getenv("MY_AGENT_OPENAI_BASE_URL")
    or os.getenv("AGENT_OPENAI_BASE_URL")
    or "https://api.openai.com/v1"
)
LLM_TIMEOUT_SECONDS = float(os.getenv("MY_AGENT_LLM_TIMEOUT_SECONDS", "6"))
LLM_MAX_TOKENS = int(os.getenv("MY_AGENT_LLM_MAX_TOKENS", "1200"))
LLM_REASONING_EFFORT = os.getenv("MY_AGENT_LLM_REASONING_EFFORT", "medium")
LLM_AUDIT_EVERY_DAYS = int(os.getenv("MY_AGENT_LLM_AUDIT_EVERY_DAYS", "0"))
LLM_ALLOW_CHAT_FALLBACK = os.getenv("MY_AGENT_LLM_ALLOW_CHAT_FALLBACK", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

USE_LLM = os.getenv("MY_AGENT_USE_LLM", "1").strip().lower() not in {"0", "false", "no", "off"}

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
