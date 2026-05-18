"""Evaluation harness - run an agent against multiple scenarios and seeds."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from agents.runner import run_game
from agents.run_logging import append_jsonl, make_log_path

FALLBACK_SCENARIOS = [
    "baseline", "supply_crisis", "tourist_season",
    "inflation", "renovation", "health_scare",
]
DEFAULT_SEEDS = [42, 88, 123]
MAX_PARALLEL = 10


def fetch_scenarios(base_url: str) -> list[str]:
    """Fetch available scenario names from the server."""
    try:
        r = httpx.get(f"{base_url}/scenarios", timeout=10.0)
        r.raise_for_status()
        return [s["name"] for s in r.json()]
    except Exception as e:
        print(f"Warning: Could not fetch scenarios from {base_url}/scenarios: {e}")
        print("Falling back to default known scenarios.")
        return list(FALLBACK_SCENARIOS)


def load_strategy(module_path: str):
    """Dynamically import a strategy function from a dotted module path."""
    mod = importlib.import_module(module_path)
    if not hasattr(mod, "strategy"):
        print(f"Error: {module_path} has no 'strategy' function")
        sys.exit(1)
    return mod.strategy


def _run_one(
    strategy,
    scenario: str,
    seed: int,
    base_url: str,
    team_name: str,
    verbose: bool,
    label: str,
) -> dict:
    if verbose:
        print(f"\n{'=' * 60}")
        print(label)
        print("=" * 60)

    attempts = int(os.getenv("RESTBENCH_EVAL_RETRIES", "2")) + 1
    last_error = ""
    for attempt in range(1, attempts + 1):
        result = _run_one_attempt(strategy, scenario, seed, base_url, team_name, verbose)
        if result["status"] != "error":
            return result
        last_error = result.get("error", "")
        if attempt < attempts and _retryable_error(last_error):
            print(f"  RETRY ({scenario} seed={seed}) after transient error: {last_error}")
            continue
        return result

    return _empty_result(scenario, seed, "error", -100_000, last_error)


def _run_one_attempt(
    strategy,
    scenario: str,
    seed: int,
    base_url: str,
    team_name: str,
    verbose: bool,
) -> dict:
    try:
        result = run_game(
            strategy,
            base_url=base_url,
            team_name=team_name,
            scenario=scenario,
            seed=seed,
            verbose=verbose,
        )
        score = result["score"]["total_score"]
        return {
            "scenario": scenario,
            "seed": seed,
            "score": score,
            "days": result["days_survived"],
            "cash": result["final_cash"],
            "profit": result["score"]["net_profit"],
            "sat_pen": result["score"]["satisfaction_penalty"],
            "rep_pen": result["score"]["reputation_penalty"],
            "walk_pen": result["score"]["walkout_penalty"],
            "waste_pen": result["score"]["waste_penalty"],
            "status": result["status"],
            "error": "",
        }
    except Exception as e:
        status_code, detail = _exception_status_and_detail(e)
        if status_code == 403 and "not available" in detail:
            print(f"  SKIPPED ({scenario} seed={seed}): {detail}")
            append_jsonl(
                make_log_path(team_name, scenario, seed),
                "game_unavailable",
                scenario=scenario,
                seed=seed,
                detail=detail,
            )
            return _empty_result(scenario, seed, "unavailable", None, detail)
        if status_code == 429:
            print(f"  SKIPPED ({scenario} seed={seed}): rate limited - {detail}")
            append_jsonl(
                make_log_path(team_name, scenario, seed),
                "game_rate_limited",
                scenario=scenario,
                seed=seed,
                detail=detail,
            )
            return _empty_result(scenario, seed, "rate_limited", None, detail)

        print(f"  FAILED ({scenario} seed={seed}): {detail or e}")
        append_jsonl(
            make_log_path(team_name, scenario, seed),
            "game_error",
            scenario=scenario,
            seed=seed,
            detail=detail or str(e),
        )
        return _empty_result(scenario, seed, "error", -100_000, detail or str(e))


def _retryable_error(detail: str) -> bool:
    text = detail.lower()
    return any(
        token in text
        for token in (
            "server disconnected",
            "not found",
            "timeout",
            "timed out",
            "connection",
            "502",
            "503",
            "504",
        )
    )


def _exception_status_and_detail(exc: Exception) -> tuple[int | None, str]:
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        detail = response.text
        try:
            data = response.json()
            detail = str(data.get("detail", data))
        except Exception:
            pass
        return response.status_code, detail
    return None, str(exc)


def _empty_result(scenario: str, seed: int, status: str, score: float | None, error: str) -> dict:
    return {
        "scenario": scenario,
        "seed": seed,
        "score": score,
        "days": 0,
        "cash": 0,
        "profit": 0,
        "sat_pen": 0,
        "rep_pen": 0,
        "walk_pen": 0,
        "waste_pen": 0,
        "status": status,
        "error": error,
    }


def evaluate(
    strategy,
    *,
    scenarios: list[str],
    seeds: list[int],
    base_url: str,
    team_name: str,
    verbose: bool,
    parallel: int = MAX_PARALLEL,
) -> dict:
    jobs = []
    total_games = len(scenarios) * len(seeds)
    game_num = 0
    for scenario in scenarios:
        for seed in seeds:
            game_num += 1
            label = f"[{game_num}/{total_games}] {scenario} seed={seed}"
            jobs.append((scenario, seed, label))

    results: list[dict] = []
    completed = 0

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {
            pool.submit(
                _run_one, strategy, scenario, seed,
                base_url, team_name, verbose, label,
            ): (scenario, seed)
            for scenario, seed, label in jobs
        }
        for future in as_completed(futures):
            r = future.result()
            results.append(r)
            completed += 1
            if r["score"] is None:
                print(f"  Completed {completed}/{total_games}: {r['scenario']} seed={r['seed']} -> {r['status']}")
            else:
                print(f"  Completed {completed}/{total_games}: {r['scenario']} seed={r['seed']} -> {r['score']:,.0f}")

    results.sort(key=lambda r: (r["scenario"], r["seed"]))

    scenario_totals: dict[str, list[float]] = {}
    for r in results:
        if r["score"] is not None:
            scenario_totals.setdefault(r["scenario"], []).append(r["score"])

    return {"results": results, "scenario_totals": scenario_totals}


def print_report(data: dict, team_name: str, seeds: list[int]) -> None:
    results = data["results"]
    scenario_totals = data["scenario_totals"]
    multi_seed = len(seeds) > 1

    print("\n")
    print("=" * 80)
    print(f"  EVALUATION REPORT - {team_name}")
    print("=" * 80)

    if multi_seed:
        print(f"\n{'Scenario':<20} {'Seed':>6} {'Score':>10} {'Profit':>10} {'Walk':>7} {'Rep':>9} {'Days':>5} {'Status':<12}")
        print("-" * 82)
        for r in results:
            score = "-" if r["score"] is None else f"{r['score']:.0f}"
            print(
                f"{r['scenario']:<20} {r['seed']:>6} {score:>10} "
                f"{r['profit']:>10.0f} {r['walk_pen']:>7.0f} {r['rep_pen']:>9.0f} "
                f"{r['days']:>5} {r['status']:<12}"
            )

    print(f"\n{'Scenario':<20} {'Avg Score':>10} {'Min':>10} {'Max':>10} {'Games':>6}")
    print("-" * 60)
    for scenario in sorted({r["scenario"] for r in results}):
        scores = scenario_totals.get(scenario, [])
        if not scores:
            print(f"{scenario:<20} {'n/a':>10} {'n/a':>10} {'n/a':>10} {0:>6}")
            continue
        avg = sum(scores) / len(scores)
        print(f"{scenario:<20} {avg:>10.0f} {min(scores):>10.0f} {max(scores):>10.0f} {len(scores):>6}")

    all_scores = [r["score"] for r in results if r["score"] is not None]
    avg_score = sum(all_scores) / len(all_scores) if all_scores else 0
    bankrupt_count = sum(1 for r in results if r["status"] == "bankrupt")
    error_count = sum(1 for r in results if r["status"] == "error")
    unavailable_count = sum(1 for r in results if r["status"] == "unavailable")
    rate_limited_count = sum(1 for r in results if r["status"] == "rate_limited")

    print(f"\n{'-' * 60}")
    print(f"  Games played:    {len(all_scores)}")
    print(f"  Bankruptcies:    {bankrupt_count}")
    if error_count:
        print(f"  Errors:          {error_count}")
    if unavailable_count:
        print(f"  Unavailable:     {unavailable_count}")
    if rate_limited_count:
        print(f"  Rate limited:    {rate_limited_count}")
    print(f"  Average score:   {avg_score:,.0f}")
    if scenario_totals:
        print(f"  Best scenario:   {max(scenario_totals, key=lambda s: sum(scenario_totals[s]) / len(scenario_totals[s]))}")
        print(f"  Worst scenario:  {min(scenario_totals, key=lambda s: sum(scenario_totals[s]) / len(scenario_totals[s]))}")
    print(f"\n  *** FINAL SCORE: {avg_score:,.0f} ***")
    print("-" * 60)


def main():
    parser = argparse.ArgumentParser(description="Evaluate an agent across scenarios and seeds")
    parser.add_argument("agent", help="Dotted module path to agent (e.g., agents.naive_rule)")
    parser.add_argument("--scenarios", help="Comma-separated scenario names (default: fetch from server)")
    parser.add_argument("--seeds", default="42,88,123", help="Comma-separated seeds (default: 42,88,123)")
    parser.add_argument(
        "--url",
        default=os.getenv("RESTBENCH_URL", "http://localhost:8001"),
        help="Server URL (default: RESTBENCH_URL env var or http://localhost:8001)",
    )
    parser.add_argument("--team-name", default=None, help="Team name for leaderboard (default: agent module name)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only show summary table, not per-game output")
    parser.add_argument("--parallel", "-p", type=int, default=MAX_PARALLEL, help=f"Max parallel games (default: {MAX_PARALLEL})")
    args = parser.parse_args()

    strategy = load_strategy(args.agent)
    scenarios = args.scenarios.split(",") if args.scenarios else fetch_scenarios(args.url)
    seeds = [int(s) for s in args.seeds.split(",")]
    team_name = args.team_name or args.agent.split(".")[-1]

    print(f"Agent:     {args.agent}")
    print(f"Scenarios: {', '.join(scenarios)}")
    print(f"Seeds:     {', '.join(str(s) for s in seeds)}")
    print(f"Games:     {len(scenarios) * len(seeds)}")
    print(f"Server:    {args.url}")

    data = evaluate(
        strategy,
        scenarios=scenarios,
        seeds=seeds,
        base_url=args.url,
        team_name=team_name,
        verbose=not args.quiet,
        parallel=args.parallel,
    )

    print_report(data, team_name, seeds)


if __name__ == "__main__":
    main()
