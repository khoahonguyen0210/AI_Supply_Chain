from typing import Any

import pytest

from scm_ml.benchmark.workers import ClockWatch, percentile, summarize, workload


def job(
    status: str, created: str, started: str, finished: str, attempts: int = 1, error: str = ""
) -> dict[str, Any]:
    day = "2026-10-07T10:00:"
    return {
        "status": status,
        "createdAt": day + created + "Z",
        "startedAt": day + started + "Z",
        "finishedAt": day + finished + "Z",
        "attempts": attempts,
        "errorCode": error or None,
    }


def test_workload_is_deterministic_and_valid() -> None:
    first, second = workload(48), workload(48)
    assert first == second
    assert len(first) == 48
    assert all(len(set(plan["skuIds"])) == 4 for plan in first)
    assert {plan["demandMultiplier"] for plan in first} == {1.0, 1.1, 1.2, 1.3, 1.4}


def test_percentile_interpolates() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == pytest.approx(2.5)
    assert percentile([5.0], 0.95) == 5.0


def test_summary_uses_job_timestamps() -> None:
    jobs = [
        job("SUCCEEDED", "00", "01", "03"),
        job("SUCCEEDED", "00", "03", "06", attempts=2),
        job("FAILED", "00", "06", "07", error="UNKNOWN_SKU"),
    ]
    summary = summarize(jobs)
    assert summary["makespan_s"] == pytest.approx(7.0)
    assert summary["succeeded"] == 2 and summary["failed"] == 1
    assert summary["retried_jobs"] == 1 and summary["total_attempts"] == 4
    assert summary["throughput_jobs_per_min"] == pytest.approx(2 / 7 * 60)
    assert summary["wait_s"]["max"] == pytest.approx(3.0)
    assert summary["run_s"]["p50"] == pytest.approx(2.5)
    assert summary["errors"] == ["UNKNOWN_SKU"]


def test_clock_watch_flags_a_jump_as_a_suspend() -> None:
    watch = ClockWatch()
    assert not watch.suspended
    watch.max_gap_s = ClockWatch.SUSPEND_GAP_S + 1
    assert watch.suspended


def test_clock_watch_measures_gaps() -> None:
    with ClockWatch() as watch:
        pass
    assert watch.max_gap_s < ClockWatch.SUSPEND_GAP_S
