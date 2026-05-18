# Prosus Hackathon Hybrid Operator

This repository contains a hybrid autonomous agent for the Prosus/AISO REST-bench
restaurant management hackathon. The agent runs a 30-day Italian restaurant
simulation and returns daily tool calls for staffing, inventory, suppliers,
menu, pricing, promotions, and persistent notes.

The implementation lives in `sim-starterkit/agents/hybrid_operator`, but the
Python project is managed from the repository root with `uv` and
`pyproject.toml`.

## System Overview

The agent is intentionally hybrid:

- deterministic controller for survival, inventory, staffing, prices, and
  validation
- optional LLM planner for high-level strategic intent only
- strict final validator so invalid simulator actions are repaired or dropped
- compact `save_notes` memory for covers, supplier reliability, stockouts, cash,
  and recent mode/scenario
- OR-Tools CP-SAT for bounded inventory order selection, with a greedy fallback

Daily flow:

```text
observation
  -> normalized GameState
  -> notes/memory update
  -> metrics and demand forecast
  -> risk assessment
  -> scenario detection
  -> deterministic plan + optional LLM strategic plan
  -> staffing / menu / inventory / pricing / promotion modules
  -> action validator and cash repair
  -> save_notes
```

The LLM never emits executable tool calls. It can only return a compact
`StrategyPlan`, and the deterministic modules still generate and validate all
actions.

## Environment

A local `.env` file is included for the hackathon LiteLLM proxy setup, and
`.env.example` keeps the same template in git:

```env
RESTBENCH_URL=http://52.48.183.209:8001
TEAM_NAME=hybrid_operator
USE_LLM_PLANNER=true
AGENT_MODEL=openai/gpt-4.1-mini
AGENT_MODEL_FALLBACK=openai/gpt-4.1-nano
LLM_TIMEOUT_SECONDS=6
LITELLM_LOG=ERROR
OPENAI_API_KEY=sk-your-virtual-key
OPENAI_BASE_URL=http://litellm-production.eba-pvykax23.eu-west-1.elasticbeanstalk.com
OPENAI_API_BASE=http://litellm-production.eba-pvykax23.eu-west-1.elasticbeanstalk.com
```

Replace `sk-your-virtual-key` with the key issued for your team. Keep `.env`
private; it is ignored by git.

The proxy is OpenAI-compatible. A direct smoke test matching the provided setup:

Windows PowerShell:

```powershell
@'
import os
import openai
from dotenv import load_dotenv

load_dotenv(".env", override=True)
client = openai.OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ["OPENAI_BASE_URL"],
)
print(f"OpenAI-compatible client configured for {client.base_url}")
'@ | uv run python -
```

macOS/Linux:

```bash
uv run python - <<'PY'
import os
import openai
from dotenv import load_dotenv

load_dotenv(".env", override=True)
client = openai.OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ["OPENAI_BASE_URL"],
)
print(f"OpenAI-compatible client configured for {client.base_url}")
PY
```

## Bootstrap

From the repository root:

Windows PowerShell:

```powershell
uv sync
```

macOS/Linux:

```bash
uv sync
```

Verify imports, tests, and lint:

Windows PowerShell:

```powershell
uv run pytest -q
uv run ruff check sim-starterkit/agents/hybrid_operator sim-starterkit/tests/test_hybrid_operator.py
uv run python -m compileall sim-starterkit/agents/hybrid_operator
```

macOS/Linux:

```bash
uv run pytest -q
uv run ruff check sim-starterkit/agents/hybrid_operator sim-starterkit/tests/test_hybrid_operator.py
uv run python -m compileall sim-starterkit/agents/hybrid_operator
```

Run one local strategy smoke check without creating a server game:

Windows PowerShell:

```powershell
uv run python -c "from agents.hybrid_operator.agent import strategy; print(strategy({}, 1))"
```

macOS/Linux:

```bash
uv run python -c 'from agents.hybrid_operator.agent import strategy; print(strategy({}, 1))'
```

This smoke check uses an empty synthetic observation, so the agent intentionally
skips the optional LLM planner and returns deterministic fallback actions.

Run the known-scenario evaluation matrix:

Windows PowerShell:

```powershell
$env:TEAM_NAME="your-team-name"
uv run python -m agents.evaluate agents.hybrid_operator.agent `
  --scenarios baseline,supply_crisis,tourist_season,renovation `
  --seeds 42,88,123 `
  --parallel 5 `
  --team-name $env:TEAM_NAME
```

macOS/Linux:

```bash
export TEAM_NAME="your-team-name"
uv run python -m agents.evaluate agents.hybrid_operator.agent \
  --scenarios baseline,supply_crisis,tourist_season,renovation \
  --seeds 42,88,123 \
  --parallel 5 \
  --team-name "$TEAM_NAME"
```

Final-style run once hidden scenarios are unlocked:

Windows PowerShell:

```powershell
$env:TEAM_NAME="your-team-name"
uv run python -m agents.evaluate agents.hybrid_operator.agent `
  --seeds 7,55,99 `
  --parallel 5 `
  --team-name $env:TEAM_NAME
```

macOS/Linux:

```bash
export TEAM_NAME="your-team-name"
uv run python -m agents.evaluate agents.hybrid_operator.agent \
  --seeds 7,55,99 \
  --parallel 5 \
  --team-name "$TEAM_NAME"
```

To disable LLM calls and use the deterministic controller only:

Windows PowerShell:

```powershell
$env:USE_LLM_PLANNER="false"
uv run python -m agents.evaluate agents.hybrid_operator.agent --scenarios baseline --seeds 42 --team-name $env:TEAM_NAME
```

macOS/Linux:

```bash
export USE_LLM_PLANNER=false
uv run python -m agents.evaluate agents.hybrid_operator.agent --scenarios baseline --seeds 42 --team-name "$TEAM_NAME"
```

## Key Files

- `pyproject.toml`: root `uv` dependencies and package mapping
- `.env`: local REST-bench and LiteLLM proxy configuration
- `.env.example`: tracked environment template
- `sim-starterkit/agents/hybrid_operator/agent.py`: public `strategy` entry point
- `sim-starterkit/agents/hybrid_operator/planner.py`: deterministic and optional
  LLM strategic planner
- `sim-starterkit/agents/hybrid_operator/validator.py`: final action validation
- `sim-starterkit/tests/test_hybrid_operator.py`: focused safety tests
