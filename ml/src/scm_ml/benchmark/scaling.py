from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path
from typing import Any

from scm_ml.forecast.artifacts import provenance, write_json

from .workers import login, run_batch

DEFAULT_OUT = Path("ml/experiments/systems/worker-scaling.json")
SECRETS = Path("infrastructure/kubernetes/secrets.env")
WARMUP_JOBS_PER_WORKER = 2
MAX_TRIES = 3


def kubectl(context: str, *args: str) -> str:
    result = subprocess.run(
        ["kubectl", "--context", context, "-n", "scm", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def scale(context: str, replicas: int) -> None:
    kubectl(context, "scale", "deployment/worker", f"--replicas={replicas}")
    kubectl(context, "rollout", "status", "deployment/worker", "--timeout=900s")
    # a just-ready engine has loaded its model; give the workers' first poll a moment
    time.sleep(5)


def pod_settings(context: str) -> dict[str, Any]:
    return {
        "worker": kubectl(
            context,
            "get",
            "deployment/worker",
            "-o",
            "jsonpath={.spec.template.spec.containers[0].resources}",
        ),
        "engine_sidecar": kubectl(
            context,
            "get",
            "deployment/worker",
            "-o",
            "jsonpath={.spec.template.spec.initContainers[?(@.name=='engine')].resources}",
        ),
        "node_cpus": kubectl(
            context, "get", "nodes", "-o", "jsonpath={.items[0].status.capacity.cpu}"
        ),
    }


def demo_password(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("SCM_DEMO_PASSWORD="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"SCM_DEMO_PASSWORD not found in {path}; run scripts/kind.sh up first")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure job throughput against worker count.")
    parser.add_argument("--context", default="kind-scm")
    parser.add_argument("--url", default="http://localhost:8380")
    parser.add_argument("--replicas", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--jobs", type=int, default=48)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--disrupt", action="store_true")
    parser.add_argument("--disrupt-after", type=float, default=8.0)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    client = login(args.url, "planner", demo_password(SECRETS))
    runs: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []

    def measured(replicas: int, **kwargs: Any) -> dict[str, Any]:
        for _ in range(MAX_TRIES):
            summary = run_batch(client, args.jobs, **kwargs)
            if not summary["host_suspended"]:
                return summary
            print(f"  host suspended (clock gap {summary['max_clock_gap_s']:.0f}s); run again")
            discarded.append(summary | {"replicas": replicas})
        raise SystemExit("host kept suspending; keep the machine awake and on power")

    for replicas in args.replicas:
        scale(args.context, replicas)
        run_batch(client, WARMUP_JOBS_PER_WORKER * replicas)
        for repeat in range(args.repeats):
            summary = measured(replicas)
            summary |= {"replicas": replicas, "repeat": repeat, "disrupted": False}
            runs.append(summary)
            print(
                f"replicas {replicas} run {repeat}: {summary['succeeded']}/{args.jobs} ok, "
                f"makespan {summary['makespan_s']:.1f}s, "
                f"{summary['throughput_jobs_per_min']:.1f} jobs/min"
            )
    if args.disrupt:
        replicas = max(args.replicas)
        scale(args.context, replicas)
        context = args.context

        def kill_one_worker() -> str:
            victim = kubectl(context, "get", "pods", "-l", "app=worker", "-o", "name").split()[0]
            kubectl(context, "delete", victim, "--grace-period=0", "--force", "--wait=false")
            return victim

        summary = measured(replicas, disrupt_after_s=args.disrupt_after, disrupt=kill_one_worker)
        summary |= {"replicas": replicas, "repeat": 0, "disrupted": True}
        runs.append(summary)
        print(
            f"disrupted run at {replicas}: {summary['succeeded']}/{args.jobs} ok, "
            f"{summary['failed']} failed, {summary['retried_jobs']} retried, "
            f"makespan {summary['makespan_s']:.1f}s, disruption {summary.get('disruption')}"
        )
        scale(args.context, replicas)

    result = {
        "benchmark": "worker-scaling",
        "workload": {
            "type": "OPTIMIZATION",
            "jobs": args.jobs,
            "plan": "4 SKUs, 8-week horizon, demand multiplier 1.0-1.4 (workers.workload)",
        },
        "cluster": {
            "context": args.context,
            "resources": pod_settings(args.context),
            "scaling_unit": "worker pod = queue worker + engine sidecar (1 CPU)",
        },
        "method": (
            f"{WARMUP_JOBS_PER_WORKER} unrecorded warm-up jobs per worker after each scale; "
            "runs taken across a host suspend are discarded and repeated"
        ),
        "runs": runs,
        "discarded_runs": discarded,
        "provenance": provenance(),
    }
    write_json(args.out, result)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
