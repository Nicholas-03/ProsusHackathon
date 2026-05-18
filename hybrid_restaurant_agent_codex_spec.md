# Codex Implementation Specification — Hybrid Restaurant Management Agent

## Purpose

Implement a robust autonomous agent for the ProsusAI / REST-bench restaurant management hackathon.

The agent must run a 30-day Italian restaurant simulation by making daily decisions around:

- Pricing
- Staffing
- Inventory
- Supplier management
- Customer satisfaction
- Promotions
- Menu management
- Long-term business strategy

The goal is to maximize final score:

```text
total_score = net_profit - penalties
```

Penalties include satisfaction, reputation, walkouts, and food waste. Bankruptcy results in a catastrophic score of `-100000`, so survival is always the first priority.

This specification is designed to be passed directly to Codex so it can implement the agent inside the provided `ProsusAI/sim-starterkit` repository.

---

## Source context

The starter kit is available at:

```text
https://github.com/ProsusAI/sim-starterkit
```

Important repo files:

```text
README.md
AGENT_CONTRACT.md
STRATEGY_GUIDE.md
agents/starter_template.py
agents/llm_template.py
agents/evaluate.py
```

The starter kit contract says the agent must expose:

```python
def strategy(observation: dict, day: int) -> list[dict]:
    ...
```

Each returned action must be a dict:

```python
{"tool": "<tool_name>", "args": {...}}
```

Available tools:

```text
place_order
set_staff_level
set_menu
set_price
set_marketing_spend
run_happy_hour
offer_daily_special
save_notes
```

Core constraints:

```text
Simulation length: 30 days
Starting cash: 15000 EUR
Fixed daily cost: 300 EUR
Staff cost: 120 EUR/person/day
Starting staff: 8
Staff range: 3 to 15
Marketing range: 0 to 500 EUR/day
Price range: 0.8x to 1.2x base dish price
Menu minimum: 5 dishes
Notes limit: 4000 chars
Tick budget: 30000 ms
Names are case-sensitive
```

Known development scenarios:

```text
baseline
supply_crisis
tourist_season
renovation
```

Possible extra scenarios exposed by the server or fallback evaluator:

```text
inflation
health_scare
```

Final evaluation expectation:

```text
10 scenarios x 3 seeds = 30 games per team
6 of the 10 final scenarios may be hidden
do not assume final scenario names
```

Known critical observation fields:

```text
cash
yesterday_revenue
yesterday_total_costs
cost_breakdown
inventory
service_summary
service_summary.dishes_unavailable_at
service_summary.dishes_sold
service_summary.walkout_band
service_summary.avg_wait_minutes
service_summary.peak_wait_minutes
service_summary.kitchen_bottleneck_hours
service_summary.hourly_covers
supplier_catalog
pending_orders
delivery_history
menu_book
active_menu
staff_level
reputation_band
recent_reviews
customer_trend
weather_today
weather_forecast
alerts
notes
tick_budget_ms
```

---

## High-level implementation goal

Build a **hybrid agent**, not a pure LLM agent.

The LLM may be used for high-level strategic classification and scenario reasoning, but all final executable actions must be created, validated, and repaired by deterministic Python modules.

Target architecture:

```text
observation
  -> parser / state normalizer
  -> memory loader
  -> metrics calculator
  -> risk engine
  -> scenario detector
  -> strategic planner
       -> deterministic fallback
       -> optional LLM strategic plan
  -> pricing module
  -> staffing module
  -> inventory module
  -> supplier module
  -> satisfaction/promotion module
  -> menu module
  -> action validator and repair
  -> save_notes
  -> list[tool_call]
```

The agent must be robust under hidden scenarios. Do not overfit to one seed or one known scenario.

Practical priority: build a small, hard-to-break deterministic controller first. Inventory, staffing, supplier timing, pending orders, stockouts, and cash reserve discipline matter more than a large architecture that is only partially implemented. Scenario labels are useful diagnostics, but final decisions should be driven mainly by observable symptoms such as stockout risk, service pressure, delivery failures, demand drift, reputation drift, and cash risk.

---

## Technology stack to use

This project should be implemented as a **Python-first hybrid control agent**.

The stack is split into four tiers:

1. **Required core stack**: must be implemented.
2. **Strongly recommended stack**: use unless time is very limited.
3. **Optional SOTA stack**: add only after the deterministic agent is stable.
4. **Avoid / not worth it for this hackathon**: technologies that add complexity without likely score gain.

---

### Required core technologies

These are the only technologies Codex should require for the scoring agent. The starter kit currently installs `httpx` and `litellm`; the deterministic core must not require additional packages at import time.

| Area                   | Technology                              | Use in this project                                      | Why it matters                                                |
| ---------------------- | --------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------- |
| Language               | **Python 3.11 or 3.12**                 | Entire agent implementation                              | Matches starter kit and VM setup                              |
| Package/env management | **venv + UV**                           | Simple VM setup                                          | Lowest friction for hackathon and evaluator compatibility     |
| Data models            | **standard-library dataclasses**        | `GameState`, `Metrics`, `RiskAssessment`, `StrategyPlan` | Strong typing without extra runtime dependency                |
| Parsing/serialization  | **json**                                | Notes, optional logs, LLM plan parsing                   | Already available and reliable                                |
| Numeric computation    | **plain Python math/statistics**        | EMAs, forecasts, clamps, scoring proxies                 | Enough for online control inside `strategy`                   |
| Validation             | **plain Python validator module**       | Validate and repair every action                         | Prevent invalid actions without relying on Pydantic           |
| Config                 | **os.environ**                          | `RESTBENCH_URL`, `TEAM_NAME`, optional LLM flags         | No `.env` dependency required by evaluator                     |
| Logging                | **standard `logging` + optional JSONL** | Daily decision logs                                      | Debug score failures without risking crashes                  |
| Optional LLM           | **litellm if already configured**       | Strategic plan only                                      | Starter kit already includes it, but core must work without it |

Required install line:

```bash
pip install -r requirements.txt
```

---

### Strongly recommended technologies

These should be used only after the deterministic controller works and survives known scenarios. They must stay optional and must not be imported unconditionally by the scoring path.

| Area                  | Technology                                        | Use in this project                                          | Why                                                     |
| --------------------- | ------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------- |
| Testing               | **pytest**                                        | Unit tests and smoke tests                                   | Prevent regressions in validators and inventory logic   |
| Code quality          | **ruff**                                          | Fast lint/format                                             | Avoid style and import errors                           |
| LLM abstraction       | **LiteLLM**                                       | Route calls to OpenAI or fallback models                     | Already aligned with starter kit                        |
| Structured LLM output | **JSON Schema / manual enum validation**           | Force the LLM planner to emit `StrategyPlan` JSON            | Prevent malformed LLM plans                             |
| Offline analytics     | **pandas or DuckDB**                              | Query JSONL/CSV evaluation logs                              | Useful for tuning, not needed in `strategy`             |
| Serialization         | **orjson**                                        | Faster compact JSON notes/logs                               | Optional; stdlib `json` is sufficient                   |
| Experiment tracking   | **CSV/Markdown experiment log**                   | Track changes and scores                                     | Simpler than MLflow/W&B                                 |

Recommended development install line:

```bash
pip install pytest ruff pandas duckdb orjson
```

---

### Optional SOTA agent technologies

Add these only after the deterministic agent is strong and stable.

| Area                   | Technology                                     | Use                                                                  | When to use                                                   |
| ---------------------- | ---------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------- |
| Agent framework        | **OpenAI Agents SDK**                    | Guardrails, tracing, structured strategic planner                    | Use if you want traceable planner calls and output guardrails |
| Agent graph runtime    | **LangGraph**                            | Explicit state graph: observe → risk → plan → modules → validate | Use if you want durable state graphs and clean orchestration  |
| Forecasting            | **scikit-learn**                         | Ridge/RandomForest demand prediction from eval logs                  | Use after collecting enough games                             |
| Optimization           | **scipy.optimize**                       | Lightweight continuous/discrete tuning                               | Use for quick parameter search                                |
| Hyperparameter search  | **Optuna**                               | Tune safety stock, staff thresholds, price rules                     | Use only if simulator can run many games quickly              |
| Monitoring             | **Prometheus + Grafana**                 | Runtime metrics dashboard                                            | Usually overkill unless the VM runs many evaluations          |
| Distributed evaluation | **Ray**                                  | Parallel scenario/seed sweeps                                        | Use only if local evaluator parallelism is insufficient       |
| Experiment tracking    | **MLflow** or **Weights & Biases** | Track scores and configurations                                      | Useful for teams, but not required                            |

Optional install line:

```bash
pip install openai-agents langgraph scikit-learn scipy optuna
```

Only install `ray`, `mlflow`, or `wandb` if the team really needs them.

---

### Technologies for VM deployment

Use this deployment stack on the VM:

| Layer                    | Technology                                      | Purpose                                                            |
| ------------------------ | ----------------------------------------------- | ------------------------------------------------------------------ |
| OS                       | **Ubuntu 22.04/24.04 LTS**                | Stable Python/Docker environment                                   |
| Process/session          | **tmux**                                  | Keep long evaluations alive over SSH                               |
| Runtime isolation        | **venv** initially                        | Fastest setup                                                      |
| Containerization         | **Docker**                                | Reproducible deployment after agent works                          |
| Multi-service deployment | **Docker Compose**                        | Optional wrapper + logs + monitoring                               |
| Secrets                  | **`.env` file + environment variables** | API keys and config                                                |
| Long-running service     | **systemd**                               | Only if exposing a persistent agent server                         |
| API wrapper              | **FastAPI + Uvicorn**                     | Only if the hackathon requires hosting an HTTP endpoint on your VM |
| Reverse proxy            | **Nginx or Caddy**                        | Only if exposing FastAPI publicly                                  |
| Logs                     | **JSONL files + logrotate**               | Keep logs bounded                                                  |

The starter kit normally imports the agent module directly through the evaluator, so **FastAPI is not required** unless the organizers specifically require your VM to expose an HTTP endpoint.

VM install baseline:

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv git tmux build-essential
```

Docker optional:

```bash
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker "$USER"
```

---

### Technologies by feature

#### 1. Pricing

Use:

```text
plain Python math and rolling metrics
plain Python action validation
optional contextual bandit implemented in plain Python
optional pandas/scipy/optuna only for offline tuning
```

Do not start with deep reinforcement learning.

Best implementation:

```text
- deterministic pricing rules
- small discrete price arms
- rolling demand/margin metrics
- safety guards against reputation damage
- optional Thompson Sampling or epsilon-greedy bandit
```

#### 2. Staffing

Use:

```text
plain Python forecasting heuristics
optional scikit-learn after collecting logs
```

Best implementation:

```text
- forecast covers
- map covers to staff
- adjust for wait/walkout pressure
- cash-aware clamps
```

#### 3. Inventory

Use:

```text
plain Python greedy ordering by criticality / cost
plain Python validators
supplier calendar functions
OR-Tools optional only after the greedy version is stable
```

Best implementation:

```text
- reorder point model
- safety stock by scenario
- supplier delivery-calendar awareness
- budget-constrained order selection
```

Optional OR-Tools formulation can be used as a 0/1 or mixed-integer problem after the greedy version is stable:

```text
maximize sum(criticality_i * selected_order_i)
subject to total_order_cost <= ordering_budget
subject to supplier/ingredient validity
subject to minimum order quantities
subject to not duplicating pending orders
```

The scoring agent must always have a greedy fallback by criticality / cost and must not require OR-Tools.

#### 4. Supplier management

Use:

```text
plain Python scoring
memory via save_notes
optional Bayesian/Beta reliability model
optional SQLite/DuckDB for offline supplier analysis
```

Best implementation:

```text
- reliability EMA
- alert penalty
- price + lead time + delivery day + reliability scoring
```

#### 5. Customer satisfaction

Use:

```text
rule-based root-cause classifier
LLM strategic diagnosis optional
structured output validation
```

Best implementation:

```text
- classify inventory issue / service issue / value issue / demand issue
- choose daily special, happy hour, marketing only when safe
```

#### 6. Long-term strategy

Use:

```text
mode-based finite-state controller
optional LLM planner
manual JSON Schema / enum validation
LiteLLM for model routing
OpenAI Agents SDK or LangGraph only if helpful
```

Best implementation:

```text
- deterministic mode selection first
- optional LLM StrategyPlan
- no direct LLM tool calls
```

---

### LLM technology choice

Use the LLM for **strategic planning only**, not direct actions.

Preferred setup:

```text
LiteLLM Router
  primary model: strong OpenAI model for strategy
  fallback model: cheaper/faster model
  output: StrategyPlan JSON
  timeout: 3-8 seconds
  retries: 1-2
```

Environment variables:

```bash
export USE_LLM_PLANNER=false
export AGENT_MODEL=openai/gpt-4.1-mini
export AGENT_MODEL_FALLBACK=openai/gpt-4.1-nano
export LLM_TIMEOUT_SECONDS=6
export OPENAI_API_KEY=...
```

The deterministic agent must work with:

```bash
export USE_LLM_PLANNER=false
```

LLM guardrails:

```text
- LLM never emits tool calls.
- LLM returns only StrategyPlan JSON.
- Manual JSON parsing and enum validation validates the plan; Pydantic is optional.
- Invalid/missing plan falls back to deterministic mode.
- Hard validator still checks final actions.
```

---

### OpenAI Agents SDK vs LangGraph vs plain Python

Use this decision rule:

```text
Default: plain Python modules
If you need model routing only: LiteLLM
If you need structured planner + tracing/guardrails: OpenAI Agents SDK
If you need explicit graph orchestration/checkpointing: LangGraph
```

Recommended for this hackathon:

```text
Phase 1: plain Python deterministic modules
Phase 2: LiteLLM optional strategic planner
Phase 3: OpenAI Agents SDK tracing/guardrails or LangGraph only if time remains
```

Do not rewrite the whole agent into a framework before the deterministic policy is reliable.

---

### Containerization files to add

Codex should add these only after the Python module works.

#### `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "agents.evaluate", "agents.hybrid_operator.agent", "--seeds", "42,88,123", "--parallel", "5"]
```

#### `docker-compose.yml`

```yaml
services:
  hybrid-agent:
    build: .
    env_file:
      - .env
    volumes:
      - ./logs:/app/logs
      - ./eval_results:/app/eval_results
    command: >
      python -m agents.evaluate agents.hybrid_operator.agent
      --seeds 42,88,123
      --parallel 5
```

#### `.env.example`

```bash
RESTBENCH_URL=http://52.48.183.209:8001
TEAM_NAME=YOUR_TEAM_NAME
USE_LLM_PLANNER=false
AGENT_MODEL=openai/gpt-4.1-mini
AGENT_MODEL_FALLBACK=openai/gpt-4.1-nano
LLM_TIMEOUT_SECONDS=6
OPENAI_API_KEY=
LOG_LEVEL=INFO
```

---

### Optional `requirements-hybrid.txt`

Create this file only for development and offline tuning. The submitted agent must still run after only `pip install -r requirements.txt`; optional packages must be imported lazily inside optional code paths.

```text
pytest>=8.0
ruff>=0.5
pandas>=2.2
duckdb>=1.0
orjson>=3.10
```

Optional extras:

```text
pydantic>=2.7
numpy>=1.26
tenacity>=8.2
python-dotenv>=1.0
rich>=13.7
ortools>=9.9
openai-agents
langgraph
scikit-learn
scipy
optuna
```

Do not make optional extras mandatory for the evaluator or import them at module import time.

---

### Technology priority order

Codex should implement technologies in this order:

```text
1. Python dataclasses / stdlib-only models
2. deterministic modules
3. validator and repair layer
4. JSONL logging
5. pytest tests
6. LiteLLM optional planner
7. greedy budget-constrained inventory optimizer
8. Docker/Compose packaging
9. OpenAI Agents SDK or LangGraph only if there is time
```

Score impact estimate:

```text
Very high:
- validators
- cash reserve
- inventory optimizer
- supplier reliability
- symptom-based risk detection
- save_notes memory

High:
- pricing heuristics
- staffing forecast
- root-cause satisfaction recovery
- JSONL logs for tuning

Medium:
- LiteLLM strategic planner
- scenario labels as diagnostics
- OR-Tools optimization
- DuckDB offline analysis

Low unless time remains:
- full LangGraph rewrite
- OpenAI Agents SDK multi-agent architecture
- MLflow/W&B
- Prometheus/Grafana
- Ray
```

---

### Technologies to avoid initially

Avoid these in the first implementation:

```text
Deep reinforcement learning
Large multi-agent debates
Vector databases
RAG over static docs
Kubernetes
Complex microservices
Heavy dashboards
Fine-tuning
End-to-end neural forecasting
Always-on LLM for every action
```

Reason:

```text
The simulator is short horizon, constrained, and risk-heavy.
Invalid actions, stockouts, cash collapse, and poor supplier choices matter more than fancy architecture.
A robust deterministic controller with optional LLM strategy is the best engineering tradeoff.
```

---

## Implementation constraints for Codex

### Do

- Implement the agent as a normal Python module compatible with the starter kit evaluator.
- Preserve the public function:

```python
def strategy(observation: dict, day: int) -> list[dict]:
    ...
```

- Use only the exact dish, supplier, and ingredient names from the observation.
- Validate all actions before returning them.
- Persist compact state using `save_notes`.
- Keep the agent deterministic when no LLM API key is configured.
- Make LLM usage optional and safe.
- Make sure the agent can run under the 30-second tick budget.
- Keep the deterministic scoring path standard-library first; any extra package must be optional and lazily imported.
- Wrap `strategy()` in a top-level fail-safe so unexpected errors return a minimal valid action list instead of crashing the game.
- Add tests for validators and core logic.
- Add JSONL logging if possible, but do not require it for scoring.

### Do not

- Do not rely on private hidden scenario names.
- Do not emit raw LLM tool calls directly.
- Do not exceed the notes limit.
- Do not spend cash without maintaining a safety reserve.
- Do not double-order without checking `pending_orders`.
- Do not place orders from suppliers that do not carry the ingredient.
- Do not set prices outside 0.8x–1.2x base.
- Do not set staff outside 3–15.
- Do not set marketing outside 0–500.
- Do not reduce the active menu below 5 dishes.
- Do not create heavyweight RL training loops inside `strategy`.

---

## Recommended file structure

Create a package under `agents/hybrid_operator/`.

```text
agents/
  hybrid_operator/
    __init__.py
    agent.py
    state.py
    memory.py
    metrics.py
    risk.py
    scenario.py
    planner.py
    pricing.py
    staffing.py
    inventory.py
    suppliers.py
    satisfaction.py
    menu.py
    validator.py
    logging_utils.py
    constants.py
    prompts.py
```

Also create:

```text
tests/
  test_hybrid_operator_validator.py
  test_hybrid_operator_inventory.py
  test_hybrid_operator_staffing.py
  test_hybrid_operator_memory.py
```

Optional:

```text
scripts/
  run_hybrid_eval.sh
```

The main import path should be:

```bash
python -m agents.evaluate agents.hybrid_operator.agent --seeds 42,88,123 --parallel 5
```

---

## Public entrypoint

`agents/hybrid_operator/agent.py`

Implement:

```python
from __future__ import annotations

from .state import parse_state
from .memory import parse_notes, build_notes
from .metrics import compute_metrics
from .risk import assess_risk
from .scenario import detect_scenario
from .planner import make_strategy_plan
from .pricing import make_pricing_actions
from .staffing import make_staffing_actions
from .inventory import make_inventory_actions
from .suppliers import update_supplier_memory
from .satisfaction import make_satisfaction_actions
from .menu import make_menu_actions
from .validator import make_safe_fallback_actions, validate_and_repair_actions


def strategy(observation: dict, day: int) -> list[dict]:
    try:
        state = parse_state(observation)
        memory = parse_notes(observation.get("notes", ""))

        metrics = compute_metrics(state, memory)
        memory = update_supplier_memory(state, memory)
        risk = assess_risk(state, metrics, memory)
        scenario = detect_scenario(state, metrics, memory)

        plan = make_strategy_plan(
            state=state,
            metrics=metrics,
            risk=risk,
            scenario=scenario,
            memory=memory,
        )

        actions = []
        actions.extend(make_staffing_actions(state, metrics, risk, scenario, plan))
        actions.extend(make_menu_actions(state, metrics, risk, scenario, plan))
        actions.extend(make_pricing_actions(state, metrics, risk, scenario, plan))
        actions.extend(make_inventory_actions(state, metrics, risk, scenario, plan))
        actions.extend(make_satisfaction_actions(state, metrics, risk, scenario, plan))

        notes_text = build_notes(state, metrics, risk, scenario, plan, memory)
        if notes_text:
            actions.append({"tool": "save_notes", "args": {"text": notes_text}})

        return validate_and_repair_actions(
            actions=actions,
            state=state,
            metrics=metrics,
            risk=risk,
        )
    except Exception:
        return make_safe_fallback_actions(observation, day)
```

Ordering is intentional:

1. Staff early because it affects service.
2. Menu before pricing because prices must target valid dishes.
3. Pricing before promotions.
4. Inventory orders after cash-aware planning.
5. Satisfaction/promotions only if service and inventory can handle extra demand.
6. Validate everything, including `save_notes`.

---

## Data models

Use lightweight dataclasses and defensive parsing in the scoring path. Pydantic may be used in optional development tools, but the agent must not require it at import time.

Recommended models:

```python
@dataclass
class IngredientBatch:
    quantity_kg: float
    expires_in_days: int


@dataclass
class InventoryItem:
    ingredient: str
    total_kg: float
    shelf_life_days: int
    batches: list[IngredientBatch]


@dataclass
class Supplier:
    name: str
    lead_time_days: int
    delivery_days: list[str]
    min_order_kg: float
    ingredients: dict[str, float]


@dataclass
class RecipeIngredient:
    ingredient: str
    quantity_kg: float


@dataclass
class Dish:
    name: str
    category: str | None
    base_price: float
    current_price: float
    is_active: bool
    ingredients: list[RecipeIngredient]


@dataclass
class ServiceSummary:
    total_covers: int
    total_revenue: float
    walkout_band: str
    hourly_covers: list[int]
    avg_wait_minutes: float
    peak_wait_minutes: float
    dishes_sold: dict[str, int]
    dishes_unavailable_at: dict[str, int]
    substitution_count: int
    table_utilization_peak: float
    kitchen_bottleneck_hours: list[int]


@dataclass
class GameState:
    day: int
    day_of_week: str
    days_remaining: int
    cash: float
    yesterday_revenue: float
    yesterday_total_costs: float
    cost_breakdown: dict[str, float]
    inventory: dict[str, InventoryItem]
    service: ServiceSummary
    suppliers: list[Supplier]
    pending_orders: list[dict]
    delivery_history: list[dict]
    menu_book: dict[str, Dish]
    active_menu: list[str]
    staff_level: int
    staff_cost_per_person: float
    reputation_band: str
    recent_reviews: list[dict]
    customer_trend: str
    weather_today: str
    weather_forecast: list[str]
    alerts: list[str]
    notes: str
    tick_budget_ms: int
```

Parsing must be defensive:

- Missing values should default to safe values.
- Numeric fields should be coerced to floats/ints where possible.
- Unknown fields should not crash the agent.

---

## Memory format

Use `save_notes` every day. Store compact JSON.

Maximum length: 4000 characters. Keep target length below 3500.

Recommended schema:

```json
{
  "v": 1,
  "last_day": 12,
  "mode": "balanced",
  "scenario": "supply_shock",
  "scenario_conf": 0.72,
  "cash_trend": [15120, 14980, 15310],
  "covers_trend": [92, 101, 114],
  "rev_trend": [1840, 2022, 2238],
  "walkout_trend": ["Few", "Few", "Some"],
  "rep_trend": ["Very Good", "Very Good", "Good"],
  "supplier_rel": {
    "Fresh Farms NL": 0.85,
    "Budget Foods": 0.55
  },
  "dish_sales_ema": {
    "Pizza Margherita": 18.4,
    "Chicken Parmesan": 12.1
  },
  "last_prices": {
    "Pizza Margherita": 15.2
  },
  "stockouts": {
    "Grilled Salmon": 2
  },
  "hh_streak": 0,
  "marketing_streak": 0
}
```

Memory rules:

- If parsing notes fails, ignore and start fresh.
- Never put raw observations in notes.
- Store only rolling indicators.
- Use exponential moving averages rather than large histories.
- Compress aggressively if length exceeds 3500 characters.
- Always include a version field `v`.

---

## Strategy modes

The planner should assign one of these modes:

```text
survival
defensive
balanced
growth
premium
recovery
```

### Mode: survival

Trigger when:

```text
cash is low
cash trend is negative for several days
projected cash after fixed/staff/order costs is unsafe
bankruptcy risk is high
```

Behavior:

```text
minimize spend
do not run marketing
do not run happy hour unless it is clearly needed and cheap
reduce staff only if wait/walkout signals allow it
order only critical ingredients
prefer cheaper suppliers unless reliability risk is extreme
avoid menu expansion
keep active menu valid with minimum viable dishes
```

### Mode: defensive

Trigger when:

```text
cash is moderate but risks exist
supply disruption alerts appear
reputation is worsening
walkouts are Some or Many
demand is uncertain
```

Behavior:

```text
preserve cash
favor reliable suppliers for critical ingredients
avoid aggressive price increases
staff enough to prevent walkouts
limit marketing
maintain 1-2 days of safety stock
```

### Mode: balanced

Trigger when:

```text
cash safe
reputation stable/good
no major disruption
demand stable
```

Behavior:

```text
maintain inventory coverage
small price experiments
moderate staffing
daily special on high-margin available dish
little or no marketing
```

### Mode: growth

Trigger when:

```text
customer trend is Growing
demand/covers rising
cash safe
no stockout or service bottleneck risk
tourist/demand spike likely
```

Behavior:

```text
staff up before peak
increase safety stock
raise selected prices moderately
run targeted marketing only if capacity and inventory are safe
offer daily specials
```

### Mode: premium

Trigger when:

```text
cash strong
reputation Very Good or Excellent
walkouts None/Few
demand strong
inventory stable
```

Behavior:

```text
favor service quality
favor reliable suppliers
use moderate price premium
avoid reputation damage
maintain broad menu
```

### Mode: recovery

Trigger when:

```text
reputation falls
walkouts increase
reviews worsen
dishes unavailable
wait times are high
customer trend Declining
```

Behavior:

```text
diagnose root cause
fix service and inventory first
pause price increases
offer daily special
possibly lower selected prices
run happy hour only after staffing/inventory are safe
```

---

## Risk engine

Create `risk.py`.

Inputs:

```text
state
metrics
memory
```

Outputs:

```python
@dataclass
class RiskAssessment:
    cash_risk: str          # low, medium, high, critical
    stockout_risk: str      # low, medium, high, critical
    service_risk: str       # low, medium, high, critical
    reputation_risk: str    # low, medium, high, critical
    waste_risk: str         # low, medium, high, critical
    demand_risk: str        # low, medium, high, critical
    bankruptcy_buffer: float
    projected_min_cash: float
    critical_ingredients: list[str]
    critical_dishes: list[str]
```

### Cash risk

Approximate expected costs:

```python
tomorrow_fixed = 300
tomorrow_staff = state.staff_level * state.staff_cost_per_person
cash_buffer = state.cash - tomorrow_fixed - tomorrow_staff
```

Classify:

```text
critical: cash < 1500 or projected_min_cash < 750
high:     cash < 3000 or negative cash trend for 3 days
medium:   cash < 6000 or yesterday profit negative
low:      otherwise
```

### Stockout risk

High if:

```text
service_summary.dishes_unavailable_at is non-empty
any active dish has ingredient coverage < effective lead time + safety days
critical ingredient stock + pending order is near zero
supplier disruption alert affects available ingredient
```

### Service risk

High if:

```text
walkout_band in ["Some", "Many"]
avg_wait_minutes > 8
peak_wait_minutes > 20
kitchen_bottleneck_hours non-empty
table_utilization_peak > 0.90
```

### Reputation risk

High if:

```text
reputation_band is Poor/Fair
reputation_band decreased from memory
recent review average < 3.8
walkout_band Some/Many
customer_trend Declining
```

### Waste risk

High if:

```text
cost_breakdown["waste"] high relative to revenue
many batches expire in 1-2 days
inventory coverage far above expected usage
```

---

## Scenario detector

Create `scenario.py`.

The detector should infer patterns from observations, not depend only on scenario names. Treat the label as a compact diagnostic for logs and planning, not as the main control signal. Risk modules and action modules should primarily use symptoms: stockout risk, service pressure, delivery reliability, demand drift, cost pressure, reputation drift, and cash risk.

Output:

```python
@dataclass
class ScenarioState:
    label: str
    confidence: float
    signals: list[str]
```

Labels:

```text
baseline
supply_shock
demand_spike
demand_drop
capacity_reduction
inflation_or_cost_pressure
health_or_reputation_shock
mixed_crisis
unknown
```

### Alert-based detection

Use lowercase alert strings.

Examples:

```python
alert_text = " ".join(state.alerts).lower()
```

Heuristics:

```text
if any(token in alert_text for token in ["supplier", "outage", "halted", "delivery"]):
    supply_shock

if any(token in alert_text for token in ["tourist", "festival", "surge", "visitors"]):
    demand_spike

if any(token in alert_text for token in ["renovation", "capacity", "tables"]):
    capacity_reduction

if any(token in alert_text for token in ["inflation", "cost", "price increase"]):
    inflation_or_cost_pressure

if any(token in alert_text for token in ["health", "inspection", "illness", "scare"]):
    health_or_reputation_shock
```

### Metric-based detection

Also infer from data:

```text
demand_spike:
  covers EMA rises sharply
  customer_trend Growing
  peak utilization high
  walkouts rising despite normal staff

demand_drop:
  covers EMA falls
  revenue falls
  customer_trend Declining
  table utilization low

supply_shock:
  delivery_history shows late/partial/failed deliveries
  pending orders not arriving as expected
  stockouts despite orders
  alerts mention suppliers

capacity_reduction:
  table utilization high despite lower covers
  walkouts rise with fewer covers
  alerts mention renovation/capacity

inflation_or_cost_pressure:
  cost per kg rises compared to memory
  ingredient costs rising
  margins compress

health_or_reputation_shock:
  reviews/reputation drop
  customer_trend Declining
  demand drops even with good service/inventory
```

Confidence scoring can be simple:

```python
score = number_of_signals / possible_signals
confidence = min(1.0, 0.25 + 0.15 * signal_count)
```

If multiple risks are high, return `mixed_crisis`.

Do not require a high-confidence scenario label before acting. If the symptoms show rising stockouts, service pressure, supplier failures, or cash stress, the corresponding action modules should respond immediately even when `scenario.label == "unknown"`.

---

## Metrics calculator

Create `metrics.py`.

Compute:

```python
@dataclass
class Metrics:
    yesterday_profit: float
    revenue_per_cover: float
    staff_cost: float
    staff_cost_ratio: float
    waste_ratio: float
    covers_ema: float
    revenue_ema: float
    dish_sales_ema: dict[str, float]
    active_dish_sales: dict[str, int]
    walkout_score: int
    reputation_score: int
    review_avg_recent: float | None
    expected_demand_multiplier: float
    weather_demand_factor: float
    day_of_week_factor: float
    predicted_covers: float
    ingredient_daily_usage: dict[str, float]
    ingredient_coverage_days: dict[str, float]
    pending_by_ingredient: dict[str, float]
    expiring_soon_by_ingredient: dict[str, float]
```

### Walkout score mapping

```python
WALKOUT_SCORE = {
    "None": 0,
    "Few": 1,
    "Some": 2,
    "Many": 3,
}
```

### Reputation score mapping

```python
REPUTATION_SCORE = {
    "Poor": 0,
    "Fair": 1,
    "Good": 2,
    "Very Good": 3,
    "Excellent": 4,
}
```

### Weather factor

Use conservative heuristics:

```python
WEATHER_FACTOR = {
    "sunny": 1.08,
    "cloudy": 1.00,
    "rainy": 0.92,
    "stormy": 0.82,
}
```

### Day-of-week factor

Day 1 is Monday. Use:

```python
DOW_FACTOR = {
    "Monday": 0.90,
    "Tuesday": 0.95,
    "Wednesday": 1.00,
    "Thursday": 1.05,
    "Friday": 1.15,
    "Saturday": 1.25,
    "Sunday": 1.10,
}
```

### Predicted covers

Use a weighted formula:

```python
base = max(
    state.service.total_covers,
    memory.covers_ema if available else state.service.total_covers,
    75
)

predicted_covers = base * weather_factor * day_of_week_factor
```

Adjust:

```text
customer_trend Growing: +10%
customer_trend Declining: -10%
reputation Excellent: +8%
reputation Very Good: +4%
reputation Fair: -8%
reputation Poor: -18%
demand_spike scenario: +20% to +45%
demand_drop/capacity_reduction: -15% to -35%
```

Cap predictions to prevent wild swings:

```python
predicted_covers = clamp(predicted_covers, 40, 220)
```

---

## Staffing module

Create `staffing.py`.

### Objective

Choose a staff level that prevents walkouts and excessive waits while avoiding unnecessary payroll.

### Constraints

```text
3 <= staff <= 15
staff cost = 120 EUR/person/day
```

### Algorithm

Inputs:

```text
predicted_covers
walkout_band
avg_wait_minutes
peak_wait_minutes
kitchen_bottleneck_hours
table_utilization_peak
cash risk
strategy mode
demand_spike_signal
demand_weak_signal
capacity_constrained_signal
```

Recommended formula:

```python
def target_staff_for_covers(predicted_covers: float) -> int:
    # Approximate capacity heuristic.
    # Tune via evaluations.
    if predicted_covers < 65:
        return 5
    if predicted_covers < 85:
        return 6
    if predicted_covers < 105:
        return 7
    if predicted_covers < 130:
        return 8
    if predicted_covers < 155:
        return 9
    if predicted_covers < 180:
        return 10
    return 11
```

Adjustments:

```python
if walkout_band == "Some":
    target += 1
elif walkout_band == "Many":
    target += 2

if avg_wait_minutes > 8:
    target += 1
if peak_wait_minutes > 20:
    target += 1
if kitchen_bottleneck_hours:
    target += 1
if table_utilization_peak > 0.92 and predicted_covers > 100:
    target += 1

if demand_spike_signal:
    target += 1
if capacity_constrained_signal and service_risk not in ["high", "critical"]:
    target -= 1
if demand_weak_signal and service_risk not in ["high", "critical"]:
    target -= 1

if risk.cash_risk == "critical":
    target = min(target, max(4, state.staff_level - 2))
elif risk.cash_risk == "high":
    target = min(target, max(5, state.staff_level - 1))
```

Mode adjustments:

```text
survival: cap at 6 unless walkouts are Some/Many
defensive: avoid big increases unless service risk high
balanced: normal
growth: allow +1
premium: allow +1 if cash safe
recovery: prioritize service if reputation/service risk high
```

Smoothing:

```python
# Avoid large daily staff jumps unless crisis
if abs(target - current) > 2:
    target = current + 2 * sign(target - current)
```

Return action only if target differs from current:

```python
{"tool": "set_staff_level", "args": {"level": target}}
```

---

## Inventory module

Create `inventory.py`.

### Objective

Prevent stockouts while minimizing waste and preserving cash.

The most important signal is:

```text
service_summary.dishes_unavailable_at
```

If a dish became unavailable, prioritize ingredients for that dish.

### Core concepts

For each ingredient:

```text
current_stock = inventory total kg
pending_stock = pending order quantity
effective_stock = current_stock + pending_stock
daily_usage = estimated kg/day consumed
coverage_days = effective_stock / max(daily_usage, small_number)
```

Use recipe consumption:

```python
daily_usage[ingredient] += predicted_dish_sales[dish] * recipe_quantity_kg
```

If no dish-level history exists, allocate predicted covers across active dishes:

```python
predicted_dish_sales[dish] = predicted_covers / len(active_menu) * dish_popularity_weight
```

Use actual `dishes_sold` from yesterday and EMA memory when available.

### Supplier delivery calendar

Orders arrive after lead time and only on supplier delivery days.

Implement:

```python
DAY_INDEX = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


def effective_delivery_days(current_day_name: str, lead_time_days: int, delivery_days: list[str]) -> int:
    current_idx = DAY_INDEX[current_day_name]
    earliest_idx_abs = current_idx + lead_time_days

    best = None
    for offset in range(0, 14):
        candidate_abs = earliest_idx_abs + offset
        candidate_name = INDEX_DAY[candidate_abs % 7]
        if candidate_name in delivery_days:
            best = candidate_abs - current_idx
            break

    return best if best is not None else lead_time_days + 7
```

### Safety stock days

Base values:

```text
survival: 0.5 to 1.0
defensive: 1.5 to 2.5
balanced: 1.5
growth: 2.5 to 3.5
premium: 2.0 to 3.0
recovery: 2.0 for stockout ingredients, 1.0 otherwise
```

Scenario adjustments:

```text
supply_shock: +1.5 to +2.5 for critical ingredients
demand_spike: +1.5
demand_drop: -0.5 to -1.0
capacity_reduction: -0.5
inflation_or_cost_pressure: +0.5 if prices rising and cash safe, otherwise -0.5
health_or_reputation_shock: -0.5 until demand recovers
```

### Ingredient criticality

Score each ingredient:

```python
criticality = 0

# Used by many active dishes
criticality += active_dish_count_using_ingredient * 2

# Used by high-selling dishes
criticality += sum(dish_sales_ema[dish] for active dishes using ingredient) / 10

# Stockout yesterday
if dish_using_ingredient in dishes_unavailable_at:
    criticality += 10

# Low coverage
if coverage_days < 1:
    criticality += 8
elif coverage_days < 2:
    criticality += 4

# High margin dish ingredient
criticality += estimated_margin_contribution
```

Order priority is descending criticality.

### Order target

For each ingredient:

```python
target_days = effective_delivery_days + safety_stock_days
target_qty = daily_usage * target_days
order_qty = target_qty - current_stock - pending_stock
```

Rules:

```text
Do not order if order_qty <= 0
Round to 0.5 kg or 1.0 kg increments
Respect supplier min_order_kg
Do not duplicate order if pending order already covers target
Respect cash budget
```

### Cash reserve

Maintain a reserve:

```python
if risk.cash_risk == "critical":
    reserve = 2500
elif risk.cash_risk == "high":
    reserve = 3500
elif plan.mode in ["growth", "premium"]:
    reserve = 2500
else:
    reserve = 3000
```

Available ordering budget:

```python
available_budget = max(0, state.cash - reserve - expected_staff_cost - fixed_cost)
```

If budget is low, order only critical ingredients.

### Supplier selection for inventory

For each ingredient, choose the best supplier using `suppliers.py`.

Do not simply pick the cheapest supplier during supply shocks.

### Emergency stockout handling

If `dishes_unavailable_at` is non-empty:

1. Identify each unavailable dish.
2. Find its ingredients.
3. For any ingredient with low coverage, prioritize order.
4. Choose most reliable supplier that can deliver soon.
5. Consider setting daily special to a different well-stocked dish.
6. Avoid marketing/happy hour that would worsen stockouts.

---

## Supplier module

Create `suppliers.py`.

### Objective

Choose suppliers by reliability, lead time, delivery schedule, price, and disruption risk.

### Supplier reliability memory

Initialize unknown suppliers to `0.75`.

Update from delivery history:

```python
if delivered_kg >= ordered_kg * 0.98 and on_time:
    observed = 1.0
elif delivered_kg >= ordered_kg * 0.75:
    observed = 0.6
elif delivered_kg > 0:
    observed = 0.35
else:
    observed = 0.0

new_rel = old_rel * 0.85 + observed * 0.15
```

If alerts mention a supplier negatively:

```python
new_rel *= 0.65
```

If supplier has repeated failed/partial deliveries, cap reliability:

```python
new_rel = min(new_rel, 0.55)
```

### Supplier score

For supplier `s` and ingredient `i`:

```python
price = s.ingredients[i]
effective_days = effective_delivery_days(...)
reliability = memory.supplier_rel.get(s.name, 0.75)

price_score = normalized lower-is-better score
delivery_score = normalized lower-days-is-better score
reliability_score = reliability
```

Weighted score by mode:

```python
if mode == "survival":
    score = 0.45 * price_score + 0.25 * reliability_score + 0.30 * delivery_score
elif supply_pressure:
    score = 0.20 * price_score + 0.50 * reliability_score + 0.30 * delivery_score
elif mode in ["growth", "premium", "recovery"]:
    score = 0.25 * price_score + 0.45 * reliability_score + 0.30 * delivery_score
else:
    score = 0.35 * price_score + 0.35 * reliability_score + 0.30 * delivery_score
```

Return the highest score supplier that carries the ingredient and satisfies minimum order.

### Diversification

During supply shock or high inventory risk:

```text
Do not send all critical ingredient orders to one unreliable supplier.
Prefer reliability > 0.65 for critical ingredients.
If top supplier has reliability < 0.6, use the next best reliable supplier even if more expensive.
```

---

## Pricing module

Create `pricing.py`.

### Objective

Maximize margin without damaging demand, satisfaction, or reputation.

### Constraints

```text
dish price must be between 0.8x and 1.2x base_price
```

### Approach

Use conservative discrete price multipliers:

```python
PRICE_ARMS = [0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20]
```

Avoid huge changes:

```python
MAX_DAILY_PRICE_MOVE = 0.05  # 5% of base or relative multiplier step
```

### Dish scoring

For each active dish:

```text
demand_score = sales EMA / active menu average
stock_safety = minimum ingredient coverage for that dish
margin_proxy = current_price - estimated ingredient_cost
reputation_risk = high if reputation falling or reviews low
stockout_penalty = high if dish unavailable yesterday
```

### Pricing rules

#### Raise price slightly when:

```text
dish demand above average
ingredient coverage safe
no stockout for dish
walkouts not Many
reputation not falling
scenario is demand_spike/growth/premium
```

Recommended:

```text
+5% toward 1.10 or 1.15
rarely use 1.20 unless demand is extremely strong and reputation Excellent
```

#### Lower price or hold when:

```text
customer_trend Declining
reputation falling
recent reviews poor
dish sales collapsing
price already high
health/reputation shock
```

Recommended:

```text
return toward 1.00 or 0.95 for selected dishes
```

#### Supply crisis:

```text
Do not discount scarce dishes.
For constrained popular dishes, raise only modestly if reputation allows.
For plentiful high-margin dishes, offer daily special rather than broad price cuts.
```

#### Survival cash crisis:

```text
Avoid broad discounts.
Set prices around 1.00 to 1.05.
Only discount if customer trend is collapsing and inventory is abundant.
```

### Bandit memory

Optional but useful:

Memory can store:

```json
"price_perf": {
  "Pizza Margherita": {
    "1.05": {"n": 3, "rev": 820, "sold": 54, "bad": 0}
  }
}
```

For hackathon speed, simple heuristics are acceptable. Do not implement complex RL unless everything else is stable.

### Action generation

Only set prices for a small number of dishes per day, for example top 3 active dishes, to avoid noisy over-control.

Return:

```python
{"tool": "set_price", "args": {"dish": dish_name, "price": rounded_price}}
```

Round prices to two decimals.

---

## Satisfaction and promotions module

Create `satisfaction.py`.

### Objective

Maintain reputation, reduce walkouts, avoid customer decline, and improve final score quality components.

The default promotion posture is conservative. Demand-generating actions can turn a manageable day into a stockout or walkout day, so marketing and happy hour must pass a strict gate. Daily specials are safer and can be used more often.

### Root-cause diagnosis

Determine dominant satisfaction issue:

```text
inventory_issue:
  dishes_unavailable_at non-empty
  substitutions high

service_issue:
  walkout_band Some/Many
  avg_wait_minutes high
  peak_wait_minutes high
  kitchen_bottleneck_hours non-empty

value_issue:
  price increases + declining reviews/customer trend
  high prices with poor demand

demand_issue:
  covers falling
  table utilization low
  customer_trend Declining

none:
  stable/good state
```

### Daily special

Use `offer_daily_special` often, but pick intelligently.

Candidate dish:

```text
active
ingredients have safe coverage
not stockout yesterday
good demand or high margin
not using expiring critical scarce ingredient unless trying to consume it deliberately
```

Daily special can be used:

```text
balanced: yes
growth: yes
premium: yes
recovery: yes
survival: only if it does not increase stockout risk
```

Return:

```python
{"tool": "offer_daily_special", "args": {"dish": best_dish}}
```

### Happy hour

Happy hour boosts demand and discounts prices. It can help satisfaction but can worsen stockouts and overload staff.

### Strict promotion gate

Before any `run_happy_hour` or non-zero `set_marketing_spend`, all of these should be true:

```text
cash_risk is low or medium
stockout_risk is low
service_risk is low or medium
no active dish stocked out yesterday
critical ingredient coverage is above target after pending orders
staff target can absorb predicted demand
supplier/delivery alerts are not causing scarcity
hh_streak and marketing_streak are below limits
```

If the gate fails, do not run happy hour or marketing. Prefer fixing root causes through staffing, inventory, menu simplification, supplier choice, price normalization, and a safe daily special.

Use when:

```text
inventory safe
staff adequate
demand is weak or reputation recovery needed
cash not critical
not already used repeatedly
```

Avoid when:

```text
stockout risk high
service risk high
cash critical
demand spike already happening
hh_streak >= 2
```

Rules:

```python
if promotion_gate and plan.mode == "recovery" and hh_streak == 0:
    run_happy_hour
elif promotion_gate and demand_is_weak and cash_risk != "critical":
    run_happy_hour
else:
    no happy hour
```

### Marketing

Marketing spend range: 0-500.

Use sparingly and only after the strict promotion gate passes.

Recommended amounts:

```text
0: default
50-100: light recovery or low demand
150-250: growth/tourist if inventory and staff safe
300+: rare, only if strong cash and very safe operations
```

Avoid marketing when:

```text
cash risk high/critical
inventory risk high
service risk high
staffing cannot absorb demand
supply shock causing ingredient scarcity
```

Action:

```python
{"tool": "set_marketing_spend", "args": {"amount": amount}}
```

---

## Menu module

Create `menu.py`.

### Objective

Maintain enough variety while preventing predictable stockouts.

Constraints:

```text
active menu must have at least 5 dishes
all dish names must exist
new dishes have a learning curve
narrow menus reduce demand
```

### Default behavior

Avoid changing the menu frequently. Menu instability can hurt kitchen learning.

Only change menu when:

```text
active dish is impossible to support due to supply shock
dish repeatedly stocks out
ingredient shortage is severe
demand drop requires simplification
health/reputation issue requires safer menu
```

### Menu selection algorithm

Score dishes:

```text
+ demand/sales
+ margin proxy
+ ingredients currently available
+ ingredients available from reliable suppliers
+ category variety
- stockout history
- uses disrupted supplier ingredient
- too many scarce/perishable ingredients
```

Maintain at least 5 dishes. Prefer 6-8 if safe.

During supply shock:

```text
remove dishes dependent on disrupted/scarce ingredients
replace with dishes using stable ingredients
do not reduce below 5
```

During recovery:

```text
keep customer favorites
avoid adding many new dishes
```

During growth/premium:

```text
maintain variety
avoid narrowing menu
```

Action:

```python
{"tool": "set_menu", "args": {"dishes": selected_dishes}}
```

Only emit if selected set differs meaningfully from active menu.

---

## Planner module

Create `planner.py`.

### Objective

Produce a high-level strategic plan.

Output:

```python
@dataclass
class StrategyPlan:
    mode: str
    pricing_intent: str       # lower, hold, raise_selective, raise_broad
    staffing_intent: str      # decrease, hold, increase
    inventory_intent: str     # conserve, normal, stockpile, emergency
    supplier_intent: str      # cheapest, balanced, reliable, diversify
    promotion_intent: str     # none, daily_special, happy_hour, marketing
    menu_intent: str          # hold, simplify, diversify, replace_shortage
    risk_tolerance: str       # low, medium, high
    rationale: str
```

### Deterministic fallback

Always implement deterministic fallback.

Mode decision:

```python
supply_pressure = (
    risk.stockout_risk in ["high", "critical"]
    or "supply" in scenario.signals
    or "delivery_failure" in scenario.signals
)
demand_spike = (
    scenario.label == "demand_spike"
    or state.customer_trend == "Growing"
    or risk.demand_risk == "high"
)

if risk.cash_risk == "critical":
    mode = "survival"
elif risk.reputation_risk in ["high", "critical"] or risk.service_risk in ["high", "critical"]:
    mode = "recovery"
elif supply_pressure:
    mode = "defensive"
elif demand_spike and risk.cash_risk in ["low", "medium"]:
    mode = "growth"
elif state.reputation_band in ["Very Good", "Excellent"] and risk.cash_risk == "low":
    mode = "premium"
elif risk.cash_risk == "high":
    mode = "defensive"
else:
    mode = "balanced"
```

Then set intents from mode, risk, and symptoms. Use `scenario.label` as a tie-breaker or explanation, not as the only trigger.

### Optional LLM strategic planner

Use LLM only if:

```text
environment variable USE_LLM_PLANNER=true
and API key / LiteLLM configuration exists
```

The LLM must not return executable actions. It returns only `StrategyPlan` JSON.

Use a very compact prompt. Include:

```text
day
cash
mode candidates
risk assessment
scenario symptoms and coarse label
service summary
stockout signals
supplier alerts
recent reviews summary
memory summary
```

Use `litellm` if available.

If LLM fails, times out, or returns invalid JSON, use deterministic fallback.

LLM temperature:

```text
0.1 to 0.3
```

Max tokens:

```text
500 to 800
```

Timeout:

```text
3 to 8 seconds
```

System prompt:

```text
You are the strategic planner for a restaurant simulation agent.
Return only JSON matching the StrategyPlan schema.
Do not return tool calls.
Prioritize survival, service quality, stockout prevention, and long-term reputation.
Be robust to hidden scenarios.
```

Validation:

```text
Parse JSON
Check enum values
Repair or fallback if invalid
```

---

## Action validator and repair

Create `validator.py`.

This is critical. It should be the last step before returning actions.

### Validate tool names

Allowed tools:

```python
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
```

Drop unknown tools.

### Validate notes

```text
text must be a string
text must be <= 4000 chars
target length should be <= 3500 chars
```

Repair by coercing to string, compacting JSON notes if possible, and truncating as a last resort.

### Validate staff

```text
level must be int
3 <= level <= 15
```

Repair by clamping.

### Validate prices

```text
dish exists in menu_book
price between 0.8x and 1.2x base
```

Repair by clamping and rounding.

### Validate menu

```text
all dishes exist
deduplicate
len >= 5
```

If invalid, drop action or repair with current active menu plus best available dishes.

### Validate marketing

```text
amount between 0 and 500
```

Clamp and round.

### Validate daily special

```text
dish exists
dish is active
```

If not active, replace with best active dish or drop.

### Validate orders

For each order:

```text
supplier exists
ingredient exists in supplier.ingredients
quantity > 0
quantity >= supplier.min_order_kg
projected cost <= available budget
not duplicate unless justified
```

Repair:

```text
quantity = max(quantity, min_order_kg)
round quantity
if too expensive, reduce or drop
if supplier invalid, choose valid supplier
if ingredient invalid, drop
```

### Cash-aware action budget

Before returning actions:

```python
target_staff_cost = target_staff_level * state.staff_cost_per_person
projected_spend = target_staff_cost + fixed_daily_cost + marketing + ingredient_orders
```

Because staff/fixed costs are paid end-of-day, reserve cash:

```python
reserve = risk-dependent value
```

If projected spend violates reserve:

1. Drop marketing.
2. Drop happy hour if it may increase operational risk.
3. Reduce non-critical orders.
4. Keep critical stockout-prevention orders.
5. Avoid staff cuts if service risk is high; otherwise reduce staff target.

### Fail-safe fallback

Implement `make_safe_fallback_actions(observation, day)`.

Requirements:

```text
- never raises
- returns a list
- uses only observation fields with `.get`
- sets staff to a conservative level if clearly out of range or missing
- optionally orders only obviously critical low-stock ingredients from valid suppliers within a strict cash reserve
- optionally saves short notes if safe
- never emits marketing, happy hour, broad menu churn, or risky price changes
```

This fallback is used only when the normal strategy path throws unexpectedly.

### De-duplication

Do not emit multiple actions for the same:

```text
set_staff_level
set_marketing_spend
run_happy_hour
offer_daily_special
save_notes
same dish price
same supplier+ingredient order unless intentional
```

Keep the latest or highest-priority action.

---

## Logging

Create `logging_utils.py`.

Optional but recommended.

Write JSONL to:

```text
logs/hybrid_operator/YYYYMMDD.jsonl
```

Each line:

```json
{
  "day": 7,
  "cash": 13200,
  "mode": "growth",
  "scenario": "demand_spike",
  "risk": {...},
  "metrics": {...},
  "actions": [...],
  "alerts": [...]
}
```

Do not crash if logging fails.

---

## Constants

Create `constants.py`.

Include:

```python
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
```

---

## Business decision playbooks

### 1. Pricing

Best approach:

```text
Safe contextual bandit + deterministic guardrails.
```

Implementation:

```text
- Track dish sales EMA.
- Track current/base price ratio.
- Raise only selected high-demand dishes.
- Lower or normalize prices if satisfaction/demand falls.
- Avoid broad discounts during cash crisis.
- Avoid aggressive price hikes during reputation recovery.
```

Codex should implement:

```python
make_pricing_actions(...)
```

Acceptance criteria:

```text
- Never sets invalid price.
- Does not adjust more than 3 dishes/day by default.
- Does not raise prices when reputation risk is high.
- Raises selected prices in growth/premium mode if stock is safe.
- Discounts or normalizes selected dishes in recovery/value issue mode.
```

### 2. Staffing

Best approach:

```text
Forecast demand and control service pressure.
```

Implementation:

```text
- Predict covers from EMA, weather, day of week, trend, scenario.
- Convert predicted covers to target staff.
- Add staff for walkouts, waits, bottlenecks.
- Reduce staff under demand drop or cash stress.
- Never cut too hard when service risk is high.
```

Acceptance criteria:

```text
- Always returns 3-15 staff.
- Increases staff after Many walkouts or high wait times unless cash critical.
- Cuts staff during demand drop/capacity reduction when service is safe.
- Smooths changes to at most 2 staff/day unless crisis.
```

### 3. Inventory

Best approach:

```text
Dynamic reorder points with supplier calendar awareness.
```

Implementation:

```text
- Estimate ingredient usage from predicted dish sales and recipes.
- Compute effective supplier delivery days.
- Compute target coverage.
- Order by ingredient criticality.
- Respect cash reserve.
- Avoid double-ordering.
- Prioritize stockout dishes.
```

Acceptance criteria:

```text
- Uses pending_orders.
- Uses dishes_unavailable_at.
- Respects min_order_kg.
- Chooses valid supplier.
- Maintains cash reserve.
- In supply shock, favors reliable suppliers and diversification.
```

### 4. Supplier management

Best approach:

```text
Online reliability scoring.
```

Implementation:

```text
- Use delivery_history to update reliability.
- Penalize suppliers mentioned negatively in alerts.
- Score supplier by price, reliability, effective delivery time.
- Change weights by mode/scenario.
```

Acceptance criteria:

```text
- Does not always choose cheapest supplier.
- Favors reliable suppliers during supply shock.
- Still considers cost during survival mode.
- Stores reliability in notes.
```

### 5. Customer satisfaction

Best approach:

```text
Root-cause recovery.
```

Implementation:

```text
- Distinguish service issue, inventory issue, value issue, and demand issue.
- Use daily specials frequently but safely.
- Use happy hour only when capacity and inventory are safe.
- Use marketing only when demand is weak/growth opportunity and operations can absorb it.
```

Acceptance criteria:

```text
- Does not run demand-generating promos when stockout/service risk high.
- Offers valid active-menu daily special.
- Enters recovery mode when reputation/walkouts/reviews worsen.
```

### 6. Overall strategy

Best approach:

```text
Mode-based strategy with hard safety overrides.
```

Implementation:

```text
- Compute risk.
- Detect scenario symptoms and coarse labels.
- Pick mode.
- Generate actions from deterministic modules.
- Validate/repair.
- Save memory.
```

Acceptance criteria:

```text
- Survives baseline and known scenarios in most seeds.
- Never emits invalid actions.
- Handles missing fields.
- Prioritizes symptom-based controls over exact scenario-name recognition.
- Performs deterministic fallback without LLM.
```

---

## Scenario-specific behavior

These are playbooks, not hardcoded names. In hidden evaluation, apply the playbook whenever the symptoms match, even if the scenario label is unknown or misleading.

### Baseline

```text
Mode: balanced or premium
Staff: normal day-of-week demand
Inventory: 1.5 days safety stock
Pricing: small selective increases
Promotions: daily special, low/no marketing
Suppliers: balanced cost/reliability
```

### Supply crisis

```text
Mode: defensive or recovery
Staff: protect service
Inventory: increase safety stock for critical ingredients
Suppliers: favor reliability and diversify
Pricing: modest increases on scarce high-demand dishes if reputation safe
Promotions: avoid demand spikes if stock constrained
Menu: replace dishes dependent on disrupted ingredients
```

### Tourist season / demand spike

```text
Mode: growth
Staff: preemptively increase
Inventory: raise coverage
Suppliers: reliable and fast
Pricing: selective price increases
Promotions: little marketing needed; daily special safe dish
Menu: preserve variety
```

### Renovation / capacity reduction

```text
Mode: defensive
Staff: reduce if service safe
Inventory: reduce perishable orders
Pricing: avoid aggressive increases
Promotions: cautious, avoid over-demanding limited capacity
Menu: stable, maybe simplify
```

### Inflation / cost pressure

```text
Mode: defensive or balanced
Staff: optimize but do not damage service
Inventory: avoid overstock, monitor supplier price changes
Suppliers: cost-sensitive but reliable
Pricing: gradual selected increases to protect margin
Promotions: avoid deep discounts
```

### Health scare / reputation shock

```text
Mode: recovery
Staff: protect service
Inventory: avoid stockouts
Pricing: normalize/lower selected overpriced dishes
Promotions: daily special; happy hour only if safe
Marketing: maybe low spend after service stabilizes
Menu: stable and reliable
```

### Hidden scenario

Classify from symptoms:

```text
- Supply signals -> supply_shock response
- Demand surge -> growth response
- Demand collapse -> defensive/recovery response
- Cost inflation -> margin/cost response
- Reputation drop -> recovery response
- Mixed crisis -> survival first
```

---

## Testing plan

### Unit tests

Create tests for:

```text
parse_notes handles invalid JSON
build_notes stays under 4000 chars
effective_delivery_days handles weekday-only suppliers
validator clamps staff and price
validator drops invalid supplier orders
inventory respects pending orders
inventory prioritizes unavailable dishes
staffing increases after walkouts
staffing reduces during cash critical
scenario detects alert text
```

### Smoke test

Run:

```bash
python -m agents.hybrid_operator.agent
```

If `agent.py` includes a `__main__`, make it run one baseline game.

Recommended bottom of `agent.py`:

```python
if __name__ == "__main__":
    import os

    from agents.runner import run_game

    result = run_game(
        strategy,
        team_name=os.getenv("TEAM_NAME", "hybrid_operator"),
        seed=42,
    )
    print(result)
```

### Evaluation commands

```bash
python -m agents.evaluate agents.hybrid_operator.agent \
  --scenarios baseline,supply_crisis,tourist_season,renovation \
  --seeds 42,88,123 \
  --parallel 5
```

If server exposes more scenarios:

```bash
python -m agents.evaluate agents.hybrid_operator.agent \
  --seeds 42,88,123 \
  --parallel 5
```

Final-style run:

```bash
python -m agents.evaluate agents.hybrid_operator.agent \
  --seeds 7,55,99 \
  --parallel 5 \
  --team-name YOUR_TEAM_NAME
```

---

## VM deployment notes

On the VM:

```bash
git clone https://github.com/ProsusAI/sim-starterkit
cd sim-starterkit

python3.11 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
# Optional development extras only if needed:
pip install -r requirements-hybrid.txt
```

Environment:

```bash
export RESTBENCH_URL=http://52.48.183.209:8001
export TEAM_NAME=YOUR_TEAM_NAME
```

Optional LLM:

```bash
export USE_LLM_PLANNER=true
export AGENT_MODEL=openai/gpt-4.1-mini
export OPENAI_API_KEY=...
```

Run:

```bash
python -m agents.evaluate agents.hybrid_operator.agent --seeds 42,88,123 --parallel 5 --team-name "$TEAM_NAME"
```

For persistent process or repeated eval scripts, use `tmux`:

```bash
tmux new -s restbench
```

Or create a `systemd` unit only if you build a long-running wrapper. The starter kit evaluation is command-based, so `tmux` is usually enough.

---

## Implementation priority

Codex should implement in this order:

1. `state.py`
2. `memory.py`
3. `validator.py` with `make_safe_fallback_actions`
4. `metrics.py`
5. `risk.py`
6. `suppliers.py`
7. `inventory.py`
8. `staffing.py`
9. `planner.py`
10. `agent.py`
11. Focused tests for validator, memory, inventory, staffing
12. `scenario.py` diagnostics
13. `pricing.py`
14. `satisfaction.py`
15. `menu.py`
16. Optional logging and optional LLM planner

The first working version should be deterministic and not require an LLM.

After that, add conservative pricing, strict-gated promotions, diagnostics, and finally the optional LLM planner.

---

## Minimal deterministic policy summary

If time is short, implement this simplified policy before adding optional LLM planning, optimization libraries, advanced pricing, or broad promotion logic:

```text
Every day:
1. Parse state and notes.
2. Update supplier reliability.
3. Compute predicted covers.
4. Set staff based on predicted covers and service risk.
5. Check stockouts and low ingredient coverage.
6. Order critical ingredients using reliable/fast suppliers with cash reserve.
7. Offer daily special on stocked active dish.
8. Adjust 0-2 prices conservatively only when reputation and demand signals are safe.
9. Default to no marketing/happy hour; enable only when the strict promotion gate passes.
10. Save compact notes.
```

MVP rule: no bankruptcies and no invalid actions beat clever upside. Add complexity only after the agent completes known scenarios and seeds with stable scores.

This should beat a naive LLM wrapper because it uses simulator-specific signals, especially:

```text
dishes_unavailable_at
pending_orders
delivery_history
supplier delivery days
walkout_band
avg_wait_minutes
reputation_band
recent_reviews
weather_forecast
alerts
```

---

## Suggested exact Codex task prompt

Use this prompt with Codex:

```text
Implement the hybrid_operator agent described in hybrid_restaurant_agent_codex_spec.md.

Create the package agents/hybrid_operator with modules:
agent.py, state.py, memory.py, metrics.py, risk.py, scenario.py, planner.py, pricing.py, staffing.py, inventory.py, suppliers.py, satisfaction.py, menu.py, validator.py, constants.py, logging_utils.py, prompts.py.

The public strategy function must be:
def strategy(observation: dict, day: int) -> list[dict]

It must be compatible with python -m agents.evaluate agents.hybrid_operator.agent.

Implement deterministic fallback first. LLM planner must be optional and disabled unless USE_LLM_PLANNER=true.

Focus on:
- survival first
- no invalid actions
- cash reserve
- no double-ordering
- supplier calendar awareness
- supplier reliability from delivery_history
- dishes_unavailable_at as the highest-priority inventory signal
- symptom-based risk controls before scenario-label recognition
- mode-based strategy
- strict promotion gate for marketing and happy hour
- save_notes compact memory
- top-level fail-safe fallback from strategy()
- standard-library deterministic core with optional lazy imports only
- hidden scenario robustness

Add unit tests for validators, notes, delivery day calculation, inventory ordering, and staffing.

Do not change the simulator, runner, or evaluator APIs.
```

---

## Acceptance checklist

Before considering implementation complete:

```text
[ ] strategy() returns a list for empty/minimal observations.
[ ] strategy() catches unexpected exceptions and returns safe fallback actions.
[ ] No action with unknown tool name is returned.
[ ] Agent imports and runs after only `pip install -r requirements.txt`.
[ ] Staff actions always use 3 <= level <= 15.
[ ] Price actions always use 0.8x <= price/base <= 1.2x.
[ ] Menu actions always include at least 5 valid dishes.
[ ] Marketing spend is always 0 <= amount <= 500.
[ ] Daily special is always active-menu valid.
[ ] Orders use valid supplier/ingredient pairs.
[ ] Orders respect min_order_kg.
[ ] Orders account for pending_orders.
[ ] Orders maintain cash reserve when possible.
[ ] save_notes is <= 4000 chars.
[ ] Marketing and happy hour are blocked unless the strict promotion gate passes.
[ ] Agent runs without LLM credentials.
[ ] Agent can run with optional LLM planner.
[ ] Unit tests pass.
[ ] Evaluation runs across baseline, supply_crisis, tourist_season, renovation.
[ ] Worst-case score is improved before optimizing best-case score.
[ ] No known scenario consistently bankrupts the agent.
```

---

## Tuning strategy after implementation

When tuning, optimize in this order:

```text
1. Bankruptcy count
2. Worst scenario average score
3. Walkout penalty
4. Reputation penalty
5. Waste penalty
6. Net profit
7. Best-case score
```

Do not tune only on baseline seed 42. Run multiple seeds.

Recommended tuning table:

```bash
python -m agents.evaluate agents.hybrid_operator.agent --scenarios baseline --seeds 42,88,123
python -m agents.evaluate agents.hybrid_operator.agent --scenarios supply_crisis --seeds 42,88,123
python -m agents.evaluate agents.hybrid_operator.agent --scenarios tourist_season --seeds 42,88,123
python -m agents.evaluate agents.hybrid_operator.agent --scenarios renovation --seeds 42,88,123
python -m agents.evaluate agents.hybrid_operator.agent --seeds 42,88,123 --parallel 5
```

Record changes in a simple experiment log:

```text
date, git commit, change, baseline avg, supply avg, tourist avg, renovation avg, bankruptcies, notes
```

---

## Final strategic advice

The best hackathon agent is likely not the fanciest LLM agent.

It is a robust controller with:

```text
- deterministic survival logic
- strong validation
- persistent compact memory
- symptom-based risk detection with scenario labels as diagnostics
- cash-aware inventory planning
- supplier reliability tracking
- conservative pricing optimization
- root-cause customer satisfaction recovery
- optional LLM strategic layer
```

The LLM should improve high-level judgment, not directly operate the restaurant.
