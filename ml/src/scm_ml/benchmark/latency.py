"""CLI: request latency of the main API calls against a running deployment.

    uv run python -m scm_ml.benchmark.latency --url http://localhost:3000 --password <demo password>

Each call is made sequentially by one signed-in planner (no concurrency, so this is service time
plus the proxy hop, not a load test), after a warm-up call. Latency is wall-clock time measured by
the client. The copilot task is the full agent run (forecast, inventory, sourcing, optimisation,
scenario, policies) and opens an approval request each time, so it is sampled fewer times.
"""

from __future__ import annotations

import argparse
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from scm_ml.forecast.artifacts import provenance, write_json

from .workers import login, percentile

DEFAULT_OUT = Path("ml/experiments/systems/api-latency.json")
AS_OF = "2024-12-30"  # the synthetic world's planning date
Call = Callable[[httpx.Client], httpx.Response]


def calls() -> dict[str, tuple[Call, int]]:
    """Name -> (request, default sample count)."""
    return {
        "GET /api/skus": (lambda c: c.get("/api/skus"), 50),
        "GET /api/inventory": (lambda c: c.get("/api/inventory", params={"skuId": "SKU-001"}), 50),
        "POST /api/forecasts": (
            lambda c: c.post(
                "/api/forecasts",
                json={"skuId": "SKU-001", "regionId": "R1", "asOf": AS_OF, "horizonWeeks": 8},
            ),
            30,
        ),
        "POST /api/suppliers/search": (
            lambda c: c.post(
                "/api/suppliers/search",
                json={"skuId": "SKU-001", "warehouseId": "WH-1", "quantity": 500},
            ),
            30,
        ),
        "POST /api/documents/ask": (
            lambda c: c.post(
                "/api/documents/ask",
                json={"question": "What approval is needed for a purchase order above budget?"},
            ),
            30,
        ),
        "POST /api/agent/tasks": (
            lambda c: c.post(
                "/api/agent/tasks",
                json={"text": "Demand for SKU-001 is expected to rise by 20%. What should I do?"},
            ),
            10,
        ),
    }


def timed(client: httpx.Client, call: Call) -> tuple[float, int]:
    """Milliseconds of one successful call, and how many 429s were waited out first.

    The heavy endpoints are rate limited (30 per user per minute, docs/security.md); a refusal is
    retried after its Retry-After, outside the timed window, so the result is service time.
    """
    throttled = 0
    while True:
        start = time.perf_counter()
        response = call(client)
        elapsed = time.perf_counter() - start
        if response.status_code != 429:
            break
        throttled += 1
        time.sleep(float(response.headers.get("Retry-After", "1")))
    if response.status_code >= 400:
        raise RuntimeError(f"{response.status_code} {response.text[:300]}")
    return elapsed * 1000, throttled


def measure(client: httpx.Client, call: Call, samples: int) -> dict[str, Any]:
    timed(client, call)  # warm-up
    times: list[float] = []
    throttled = 0
    for _ in range(samples):
        elapsed, waits = timed(client, call)
        times.append(elapsed)
        throttled += waits
    return {
        "samples": samples,
        "p50_ms": percentile(times, 0.5),
        "p95_ms": percentile(times, 0.95),
        "max_ms": max(times),
        "mean_ms": statistics.fmean(times),
        "rate_limited_retries": throttled,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure API latency on a running deployment.")
    parser.add_argument("--url", default="http://localhost:3000")
    parser.add_argument("--password", required=True)
    parser.add_argument("--deployment", default="docker compose (local)")
    parser.add_argument("--scale", type=float, default=1.0, help="multiply the sample counts")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    client = login(args.url, "planner", args.password)
    client.timeout = httpx.Timeout(300)
    results: dict[str, Any] = {}
    for name, (call, samples) in calls().items():
        count = max(1, round(samples * args.scale))
        results[name] = measure(client, call, count)
        row = results[name]
        print(f"{name:28s} n={count:3d}  p50 {row['p50_ms']:8.1f} ms  p95 {row['p95_ms']:8.1f} ms")
    write_json(
        args.out,
        {
            "benchmark": "api-latency",
            "url": args.url,
            "deployment": args.deployment,
            "method": "sequential, one client, after one warm-up call per endpoint; "
            "429 responses waited out and retried outside the timed window",
            "endpoints": results,
            "provenance": provenance(),
        },
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
