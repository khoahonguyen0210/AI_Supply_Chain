from __future__ import annotations

import statistics
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

SKUS = [f"SKU-{n:03d}" for n in range(1, 41)]
TERMINAL = {"SUCCEEDED", "FAILED"}
MAX_BATCH = 100  # the job list endpoint returns at most 100 of the caller's jobs


def workload(jobs: int) -> list[dict[str, Any]]:
    plans = []
    for index in range(jobs):
        skus = [SKUS[(index * 4 + k) % len(SKUS)] for k in range(4)]
        plans.append(
            {"skuIds": skus, "horizonWeeks": 8, "demandMultiplier": 1.0 + (index % 5) / 10}
        )
    return plans


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    done = [j for j in jobs if j["status"] == "SUCCEEDED"]
    created = [parse_time(j["createdAt"]) for j in jobs]
    finished = [parse_time(j["finishedAt"]) for j in jobs if j.get("finishedAt")]
    makespan = (max(finished) - min(created)).total_seconds() if finished else None
    waits = [
        (parse_time(j["startedAt"]) - parse_time(j["createdAt"])).total_seconds()
        for j in done
        if j.get("startedAt")
    ]
    runs = [
        (parse_time(j["finishedAt"]) - parse_time(j["startedAt"])).total_seconds()
        for j in done
        if j.get("startedAt")
    ]
    return {
        "jobs": len(jobs),
        "succeeded": len(done),
        "failed": sum(1 for j in jobs if j["status"] == "FAILED"),
        "retried_jobs": sum(1 for j in jobs if j["attempts"] > 1),
        "total_attempts": sum(j["attempts"] for j in jobs),
        "makespan_s": makespan,
        "throughput_jobs_per_min": (len(done) / makespan * 60) if makespan else None,
        "wait_s": _stats(waits),
        "run_s": _stats(runs),
        "errors": sorted({j["errorCode"] for j in jobs if j.get("errorCode")}),
    }


def _stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "p50": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
        "max": max(values),
        "mean": statistics.fmean(values),
    }


def login(base_url: str, user: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, timeout=60)
    response = client.post("/api/auth/login", json={"userId": user, "password": password})
    response.raise_for_status()
    client.headers["Authorization"] = f"Bearer {response.json()['accessToken']}"
    return client


class ClockWatch:
    TICK_S = 1.0
    SUSPEND_GAP_S = 15.0

    def __init__(self) -> None:
        self.max_gap_s = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        last = time.time()
        while not self._stop.wait(self.TICK_S):
            now = time.time()
            self.max_gap_s = max(self.max_gap_s, now - last - self.TICK_S)
            last = now

    def __enter__(self) -> ClockWatch:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join()

    @property
    def suspended(self) -> bool:
        return self.max_gap_s > self.SUSPEND_GAP_S


def run_batch(
    client: httpx.Client,
    jobs: int,
    *,
    timeout_s: float = 1800,
    disrupt_after_s: float | None = None,
    disrupt: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    with ClockWatch() as clock:
        summary = _run_batch(client, jobs, timeout_s, disrupt_after_s, disrupt)
    summary["max_clock_gap_s"] = round(clock.max_gap_s, 3)
    summary["host_suspended"] = clock.suspended
    return summary


def _run_batch(
    client: httpx.Client,
    jobs: int,
    timeout_s: float,
    disrupt_after_s: float | None,
    disrupt: Callable[[], Any] | None,
) -> dict[str, Any]:
    if not 1 <= jobs <= MAX_BATCH:
        raise ValueError(f"jobs must be between 1 and {MAX_BATCH}")
    run_id = uuid.uuid4().hex[:8]
    ids: list[str] = []
    for index, plan in enumerate(workload(jobs)):
        response = client.post(
            "/api/jobs",
            json={"type": "OPTIMIZATION", "payload": plan},
            headers={"Idempotency-Key": f"bench-{run_id}-{index}"},
        )
        response.raise_for_status()
        ids.append(response.json()["id"])

    disruption: dict[str, Any] | None = None
    if disrupt is not None:
        disruption = {"after_s": disrupt_after_s}

        def run_disruption() -> None:
            time.sleep(disrupt_after_s or 0)
            assert disruption is not None
            try:
                disruption["done"] = disrupt()
            except Exception as exc:  # recorded, so a failed disruption is never mistaken for one
                disruption["error"] = repr(exc)

        threading.Thread(target=run_disruption, daemon=True).start()

    # one list call per cycle (the caller's newest jobs) keeps polling far below the API rate limit
    deadline = time.time() + timeout_s
    wanted = set(ids)
    records: dict[str, dict[str, Any]] = {}
    while time.time() < deadline:
        response = client.get("/api/jobs", params={"limit": MAX_BATCH})
        response.raise_for_status()
        records.update({j["id"]: j for j in response.json() if j["id"] in wanted})
        if len(records) == len(ids) and all(r["status"] in TERMINAL for r in records.values()):
            break
        time.sleep(2)
    finished = [r for r in records.values() if r["status"] in TERMINAL]
    summary: dict[str, Any] = summarize(finished) if finished else {"jobs": 0}
    summary["unfinished"] = len(ids) - len(finished)
    summary["run_id"] = run_id
    if disruption is not None:
        summary["disruption"] = disruption
    return summary
