# Prosus Hackathon RestBench Agent

This repository contains a Python agent for the Prosus/AISO RestBench AI Agent
Hackathon. The challenge is to manage an Italian restaurant for a 30-day
simulation through a REST API: buy perishable inventory, set prices, choose a
menu, schedule staff, run promotions, protect reputation, and maximize the final
score.

The current custom solution lives in `sim-starterkit/agents/my_agent.py`. It is a
hybrid agent: a deterministic rule engine makes complete daily decisions, and an
optional bounded LLM advisory layer can review high-risk days without taking over
the core strategy.

## Table of Contents

- [Project Status](#project-status)
- [Repository Layout](#repository-layout)
- [How the Simulation Works](#how-the-simulation-works)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Running the Agent](#running-the-agent)
- [Evaluating Performance](#evaluating-performance)
- [Agent Architecture](#agent-architecture)
- [Strategy Summary](#strategy-summary)
- [Logs and Debugging](#logs-and-debugging)
- [Development Workflow](#development-workflow)
- [Troubleshooting](#troubleshooting)
- [Reference Documents](#reference-documents)

## Project Status

- Root package: `prosushackathon`
- Python version: `3.13`
- Main playable agent: `sim-starterkit/agents/my_agent.py`
- Team name default: `la-forchetta-intelligente`
- Default simulator URL in code: `http://localhost:8001`
- Starter-kit dependencies: `httpx`, `litellm`, `openai`
- Optional hybrid dependency file: `sim-starterkit/requirements-hybrid.txt`

The root `main.py` is only a minimal placeholder. Use the modules inside
`sim-starterkit/agents` for the actual hackathon agent.

## Repository Layout

```text
.
├── README.md
├── SPEC.md
├── Prosus_AISO AI Agent Hackathon Cheat Sheet .md
├── pyproject.toml
├── main.py
└── sim-starterkit/
    ├── README.md
    ├── AGENT_CONTRACT.md
    ├── STRATEGY_GUIDE.md
    ├── requirements.txt
    ├── requirements-hybrid.txt
    └── agents/
        ├── my_agent.py
        ├── my_agent_rules.py
        ├── my_agent_llm.py
        ├── my_agent_optimizer.py
        ├── my_agent_inventory.py
        ├── my_agent_utils.py
        ├── my_agent_config.py
        ├── runner.py
        ├── evaluate.py
        ├── run_logging.py
        ├── log_report.py
        ├── naive_rule.py
        ├── do_nothing.py
        ├── starter_template.py
        └── llm_template.py
```

Important files:

| File | Purpose |
| --- | --- |
| `sim-starterkit/agents/my_agent.py` | Public agent entry point used for runs and evaluation. |
| `sim-starterkit/agents/my_agent_rules.py` | Deterministic strategy layer for menu, staff, price, promotions, and ordering. |
| `sim-starterkit/agents/my_agent_llm.py` | Optional OpenAI advisory layer with strict validation and conservative merging. |
| `sim-starterkit/agents/my_agent_optimizer.py` | Small grouped knapsack optimizer for order candidate selection. |
| `sim-starterkit/agents/my_agent_inventory.py` | EOQ-inspired inventory sizing helpers. |
| `sim-starterkit/agents/my_agent_utils.py` | Shared inventory, supplier, delivery, reliability, and note helpers. |
| `sim-starterkit/agents/runner.py` | Reusable full-game runner against the REST API. |
| `sim-starterkit/agents/evaluate.py` | Multi-scenario, multi-seed evaluation harness. |
| `sim-starterkit/agents/run_logging.py` | JSONL logging of observations, planned actions, decisions, and scores. |
| `sim-starterkit/agents/log_report.py` | Compact report over recent JSONL logs. |
| `sim-starterkit/AGENT_CONTRACT.md` | Full API and action contract for the simulation. |
| `sim-starterkit/STRATEGY_GUIDE.md` | Strategic guidance for restaurant management tradeoffs. |
| `SPEC.md` | Implementation specification for the hybrid agent design. |

## How the Simulation Works

RestBench is a 30-day restaurant management game. Each day the agent receives an
observation and submits zero or more tool calls before ending the turn.

High-level loop:

```text
POST /games                  -> create a game and receive day 1 observation
POST /games/{id}/action      -> submit one action, repeated as needed
POST /games/{id}/end-turn    -> advance the simulation by one day
GET  /games/{id}/score       -> retrieve final score after completion
```

The score is based on profit minus penalties. Penalties can come from poor
satisfaction, reputation damage, walkouts, food waste, and bankruptcy.

Available action tools include:

| Tool | What it controls |
| --- | --- |
| `place_order` | Ingredient purchasing from a named supplier. |
| `set_staff_level` | Daily staffing level from 3 to 15. |
| `set_menu` | Active menu selection, with at least 5 dishes. |
| `set_price` | Dish price within 80%-120% of base price. |
| `set_marketing_spend` | Daily marketing spend from 0 to 500 EUR. |
| `run_happy_hour` | Temporary demand boost with price discount effects. |
| `offer_daily_special` | One active dish promoted as the daily special. |
| `save_notes` | Persistent scratchpad carried into future observations. |

For the full schema, validation rules, and scoring details, read
`sim-starterkit/AGENT_CONTRACT.md`.

## Quick Start

Run commands from the repository root unless a step says otherwise.

### 1. Create and activate a virtual environment

PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r .\sim-starterkit\requirements.txt
```

Optional, if you want the hybrid/optimization extras listed by the spec:

```powershell
python -m pip install -r .\sim-starterkit\requirements-hybrid.txt
```

### 3. Configure the simulator URL

Set `RESTBENCH_URL` to the simulator you are using. The runner defaults to
`http://localhost:8001`, but hackathon runs usually point at an organizer-hosted
server.

PowerShell:

```powershell
$env:RESTBENCH_URL = "http://localhost:8001"
```

macOS/Linux:

```bash
export RESTBENCH_URL=http://localhost:8001
```

If the organizers provided a public URL, use that instead.

### 4. Run a smoke test

```powershell
cd .\sim-starterkit
python -m agents.my_agent
```

The agent should create a game, play up to 30 simulated days, and print the
final score breakdown.

## Configuration

The runner loads simple `KEY=VALUE` pairs from the nearest `.env` file. The
repository's `.gitignore` ignores `.env`, so local secrets should stay out of
git.

Common variables:

| Variable | Default | Description |
| --- | --- | --- |
| `RESTBENCH_URL` | `http://localhost:8001` | Base URL for the RestBench API. |
| `RESTBENCH_TEAM_NAME` | `la-forchetta-intelligente` | Team name used by `my_agent.py`. |
| `RESTBENCH_LOG_DIR` | `logs` | Directory where JSONL run logs are written. |
| `RESTBENCH_DISABLE_LOGS` | unset | Set to `1`, `true`, `yes`, or `on` to disable JSONL logs. |
| `RESTBENCH_EVAL_RETRIES` | `2` | Number of retries per evaluation game after transient errors. |
| `OPENAI_API_KEY` | unset | Enables the optional OpenAI advisory layer if `MY_AGENT_USE_LLM` is enabled. |
| `AGENT_MODEL` | `gpt-5.5` | Model used by the custom LLM advisory layer. |
| `OPENAI_MODEL` | unset | Secondary model fallback if `AGENT_MODEL` is unset. |
| `MY_AGENT_USE_LLM` | `1` | Set to `0`, `false`, `no`, or `off` to force deterministic-only mode. |
| `MY_AGENT_OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible API base URL. |
| `MY_AGENT_LLM_TIMEOUT_SECONDS` | `22` | Timeout for advisory model calls. |
| `MY_AGENT_LLM_MAX_TOKENS` | `450` | Max response tokens for advisory output. |
| `MY_AGENT_LLM_REASONING_EFFORT` | `low` | Reasoning effort sent to the Responses API. |
| `MY_AGENT_LLM_AUDIT_EVERY_DAYS` | `0` | Periodic LLM review interval for stress scenarios; `0` disables periodic audits. |
| `MY_AGENT_LLM_ALLOW_ADJUSTMENTS` | `0` | When `0`, the LLM can be consulted but its proposed adjustments are not applied. |
| `MY_AGENT_LLM_ALLOW_CHAT_FALLBACK` | `0` | Allows fallback to Chat Completions if Responses API call fails. |

Example `.env`:

```dotenv
RESTBENCH_URL=http://localhost:8001
RESTBENCH_TEAM_NAME=la-forchetta-intelligente

# Deterministic-only mode:
MY_AGENT_USE_LLM=0

# Optional LLM advisory mode:
# OPENAI_API_KEY=sk-...
# AGENT_MODEL=gpt-5.5
# MY_AGENT_USE_LLM=1
# MY_AGENT_LLM_ALLOW_ADJUSTMENTS=0
```

Important: by default, `MY_AGENT_LLM_ALLOW_ADJUSTMENTS=0`. In that mode the LLM
may be queried on high-risk days, but the rule plan remains unchanged and notes
record `llm=checked`. Set it to `1` only when you want validated LLM adjustments
to be merged into the daily action plan.

## Running the Agent

Use `sim-starterkit` as the working directory so Python can import the `agents`
package directly.

Run the custom hybrid agent:

```powershell
cd .\sim-starterkit
python -m agents.my_agent
```

Run deterministic-only mode:

```powershell
cd .\sim-starterkit
$env:MY_AGENT_USE_LLM = "0"
python -m agents.my_agent
```

Run with a custom team name:

```powershell
cd .\sim-starterkit
$env:RESTBENCH_TEAM_NAME = "my-team"
python -m agents.my_agent
```

Run baseline agents:

```powershell
cd .\sim-starterkit
python -m agents.do_nothing
python -m agents.naive_rule
python -m agents.starter_template
```

Run the starter LLM template:

```powershell
cd .\sim-starterkit
$env:OPENAI_API_KEY = "sk-..."
$env:AGENT_MODEL = "openai/gpt-4.1-mini"
python -m agents.llm_template
```

## Evaluating Performance

The evaluation harness runs an agent across scenarios and seeds, optionally in
parallel.

Evaluate `my_agent` across all scenarios returned by the server and seeds
`42`, `88`, and `123`:

```powershell
cd .\sim-starterkit
python -m agents.evaluate agents.my_agent
```

Quiet summary only:

```powershell
cd .\sim-starterkit
python -m agents.evaluate agents.my_agent --quiet
```

Evaluate selected scenarios:

```powershell
cd .\sim-starterkit
python -m agents.evaluate agents.my_agent --scenarios baseline,supply_crisis
```

Evaluate selected seeds:

```powershell
cd .\sim-starterkit
python -m agents.evaluate agents.my_agent --seeds 42,88
```

Limit concurrency to reduce rate-limit pressure:

```powershell
cd .\sim-starterkit
python -m agents.evaluate agents.my_agent --parallel 5
```

Use a custom server and team name:

```powershell
cd .\sim-starterkit
python -m agents.evaluate agents.my_agent --url http://localhost:8001 --team-name la-forchetta-intelligente
```

Compare baselines:

```powershell
cd .\sim-starterkit
python -m agents.compare
```

Known/fallback scenarios in the harness:

- `baseline`
- `supply_crisis`
- `tourist_season`
- `inflation`
- `renovation`
- `health_scare`

The server may expose a different set through `GET /scenarios`; when available,
the harness uses the server-provided list.

## Agent Architecture

The custom agent is intentionally conservative. It should remain playable and
complete even with no model API key.

### Entry Point

`my_agent.py` exposes:

```python
def strategy(observation: dict[str, Any], day: int) -> list[dict[str, Any]]:
    rule_actions = build_rule_actions(observation, day)
    return refine_actions_with_llm(observation, day, rule_actions)
```

The runner calls this function once per simulated day. It must return a list of
tool calls shaped like:

```json
{"tool": "set_staff_level", "args": {"level": 8}}
```

### Deterministic Rule Layer

Implemented in `my_agent_rules.py`.

Responsibilities:

- Select a planned menu and avoid dishes that recently stocked out.
- Set staff based on day of week, weather, trend, reputation, walkouts, waits,
  cash, and scenario flags.
- Set marketing spend only when demand generation is likely to be serviceable.
- Set prices within the simulator's 80%-120% bounds using reputation and demand
  pressure.
- Run happy hour on slow or declining days when inventory and service are stable.
- Pick a daily special with enough available servings and healthy margin.
- Project ingredient needs and place supplier orders while preserving cash.
- Save compact state notes every day for scenario memory and diagnostics.

### Inventory Math

Implemented in `my_agent_inventory.py`.

The agent uses EOQ-inspired formulas to balance:

- expected daily ingredient demand,
- lead time until the next valid delivery day,
- supplier price,
- shelf life and spoilage risk,
- setup cost as a proxy for stockout risk.

The order planner uses fresh inventory only by default, so soon-to-expire
inventory is discounted when deciding whether the restaurant is truly covered.

### Order Optimizer

Implemented in `my_agent_optimizer.py`.

The optimizer treats ordering as a grouped knapsack problem:

- each ingredient can have multiple supplier candidates,
- at most one supplier option is chosen per ingredient,
- total estimated cost must fit inside today's cash-aware budget,
- urgent stockout coverage and short delivery times are valued heavily.

If optimization is skipped or cannot produce a useful result, the agent falls
back to a sorted deterministic order list.

### Supplier Logic

Implemented in `my_agent_utils.py`.

Supplier selection considers:

- price per ingredient,
- delivery lead time and delivery-day calendar,
- historical delivered-vs-ordered reliability,
- scenario alerts that mention outages, delays, strikes, disruptions, or closed
  suppliers.

This helps the agent avoid blindly using the cheapest supplier when the delivery
risk is too high.

### LLM Advisory Layer

Implemented in `my_agent_llm.py`.

The LLM is not the primary decision maker. It is only consulted when the day
looks risky, such as:

- day 1 setup,
- fresh alerts,
- poor reputation,
- declining customer trend,
- dishes unavailable yesterday,
- severe walkouts plus wait-time pressure,
- very low cash,
- periodic audits in stress scenarios if configured.

Allowed LLM adjustment tools are intentionally limited:

- `place_order`
- `set_staff_level`
- `set_marketing_spend`
- `run_happy_hour`
- `offer_daily_special`

The LLM is not allowed to set menu or price. Proposed actions are parsed as JSON,
validated against the observation, checked for duplicate or speculative orders,
bounded by cash budget, and merged conservatively. Any model failure falls back
to the rule plan.

## Strategy Summary

The current strategy prioritizes survival and robustness over one-scenario
overfitting.

Core operating principles:

- Prevent stockouts before chasing marginal profit.
- Respect supplier delivery calendars; a cheap supplier is bad if it arrives too
  late.
- Preserve a cash reserve for several days of overhead.
- Staff up for Friday/Saturday, growing demand, weak reputation, walkouts, and
  long waits.
- Reduce marketing when the restaurant cannot service extra demand.
- Raise prices only when reputation and capacity can support it.
- Avoid promotions during stockouts, renovation capacity limits, or major
  service stress.
- Use notes as lightweight memory for scenario detection.
- Treat hidden scenarios as first-class by reacting to alerts and observed
  metrics rather than hard-coding only known names.

Scenario-aware behavior:

| Scenario signal | Typical response |
| --- | --- |
| `supply` alerts or supplier disruption | Prefer safer menu, route around blocked suppliers, allow more urgent inventory coverage. |
| `renovation` alerts | Reduce marketing/happy-hour pressure, use a safer menu, adapt staffing to capacity limits. |
| `tourist` or festival alerts | Consider higher demand through projected covers and periodic LLM audits if enabled. |
| Poor reputation or declining trend | Protect service quality and use measured marketing only if capacity is stable. |
| Stockouts in `dishes_unavailable_at` | Identify ingredient causes, avoid unsafe menu items, prioritize urgent reorder coverage. |

## Logs and Debugging

Runs write JSONL logs unless disabled. By default, logs are written to a `logs`
directory relative to the working directory.

Each log can include:

- game creation metadata,
- summarized observations,
- planned actions,
- accepted/rejected action responses,
- day results,
- final score payload.

Disable logs:

```powershell
$env:RESTBENCH_DISABLE_LOGS = "1"
```

Write logs somewhere else:

```powershell
$env:RESTBENCH_LOG_DIR = "logs"
```

Summarize recent logs:

```powershell
cd .\sim-starterkit
python -m agents.log_report --team la-forchetta-intelligente --log-dir logs --latest 12
```

The report highlights practical failure modes:

- stockout days,
- duplicate same-day ingredient orders,
- orders placed while the same ingredient was already pending,
- alerts seen,
- days where notes were saved,
- days with many walkouts.

## Development Workflow

Suggested loop:

1. Run a single game on `baseline` seed `42`.
2. Inspect console output for rejected actions and score breakdown.
3. Review JSONL logs for stockouts, pending-order mistakes, and walkout days.
4. Run `agents.log_report` over recent logs.
5. Evaluate across a small scenario set.
6. Broaden evaluation to all scenarios and default seeds.
7. Tune one module at a time and compare results before moving on.

Useful commands:

```powershell
cd .\sim-starterkit
python -m agents.my_agent
python -m agents.evaluate agents.my_agent --scenarios baseline --seeds 42 --quiet
python -m agents.evaluate agents.my_agent --scenarios baseline,supply_crisis,renovation --seeds 42,88 --parallel 3 --quiet
python -m agents.log_report --team la-forchetta-intelligente --latest 20
```

Recommended areas for improvement:

- Add unit tests for delivery-day calculations, supplier alert detection, and
  order candidate validation.
- Add regression tests around stockout-heavy observations.
- Tune demand projections using saved logs from multiple seeds.
- Compare deterministic-only mode against LLM-audited mode before allowing LLM
  adjustments.
- Keep scenario logic based on observable alerts and metrics so hidden scenarios
  still behave sensibly.

## Troubleshooting

### `ModuleNotFoundError: No module named 'agents'`

Run the command from inside `sim-starterkit`:

```powershell
cd .\sim-starterkit
python -m agents.my_agent
```

Alternative from the repository root:

```powershell
$env:PYTHONPATH = ".\sim-starterkit"
python -m agents.my_agent
```

### Connection errors

Check that `RESTBENCH_URL` points to a reachable simulator:

```powershell
$env:RESTBENCH_URL
```

If you are running a local simulator, confirm it is listening on the configured
port. If you are using the hackathon server, verify the URL with the organizers.

### `429 Too Many Requests`

The API has rate limits. Reduce evaluation parallelism:

```powershell
cd .\sim-starterkit
python -m agents.evaluate agents.my_agent --parallel 2 --quiet
```

### Rejected actions

Rejected actions are printed in the console and saved in JSONL logs. Common
causes include:

- ingredient not sold by the named supplier,
- quantity below supplier minimum order,
- price outside the 80%-120% range,
- menu with fewer than 5 valid dishes,
- insufficient cash,
- case-sensitive names that do not match the observation.

### LLM calls do not change actions

This can be expected. The default is conservative:

- `MY_AGENT_USE_LLM=1` allows consultation,
- `MY_AGENT_LLM_ALLOW_ADJUSTMENTS=0` prevents model suggestions from being
  applied,
- missing `OPENAI_API_KEY` silently falls back to deterministic rules.

Set `MY_AGENT_LLM_ALLOW_ADJUSTMENTS=1` only after checking logs and validating
that the model's suggestions improve performance.

### No logs appear

Confirm logs are not disabled:

```powershell
$env:RESTBENCH_DISABLE_LOGS
```

Also check the current working directory. If you run from `sim-starterkit`, logs
will appear under `sim-starterkit/logs` unless `RESTBENCH_LOG_DIR` is absolute or
points elsewhere.

## Reference Documents

- `sim-starterkit/README.md`: upstream starter-kit quick start and challenge
  overview.
- `sim-starterkit/AGENT_CONTRACT.md`: authoritative API contract, observation
  schema, action tools, validation, and scoring notes.
- `sim-starterkit/STRATEGY_GUIDE.md`: qualitative strategy guide for balancing
  profit, quality, resilience, reputation, pricing, and exploration.
- `SPEC.md`: detailed implementation spec for the hybrid restaurant agent.
- `Prosus_AISO AI Agent Hackathon Cheat Sheet .md`: event logistics, resources,
  judging context, and hackathon notes.

## Submission Checklist

Before final evaluation:

- Confirm `RESTBENCH_URL` points at the correct evaluation server.
- Confirm `RESTBENCH_TEAM_NAME` is set to the intended leaderboard name.
- Run at least one deterministic-only evaluation.
- Run all available scenarios with seeds `42`, `88`, and `123`.
- Inspect logs for rejected actions, stockouts, duplicate orders, and many-walkout
  days.
- Decide whether LLM adjustments should remain disabled or be enabled.
- Remove any local secrets from shell history, shared snippets, and committed
  files.
