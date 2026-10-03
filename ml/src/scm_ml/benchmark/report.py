from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

NOT_MEASURED = "NOT YET MEASURED"
DEFAULT_EXPERIMENTS = Path("ml/experiments")
DEFAULT_OUT = Path("docs/benchmarks.md")

Artifact = dict[str, Any]


def load(root: Path, relative: str) -> Artifact | None:
    path = root / relative
    if not path.is_file():
        return None
    data: Artifact = json.loads(path.read_text(encoding="utf-8"))
    return data


def num(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return str(value)


def pct(value: Any, digits: int = 1) -> str:
    return "n/a" if value is None else f"{100 * float(value):.{digits}f}%"


def table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def source(relative: str, artifact: Artifact) -> str:
    prov = artifact.get("provenance", {})
    revision = prov.get("code_revision", "unknown")
    created = prov.get("created_at", "unknown")
    return f"Source: `ml/experiments/{relative}` (code `{revision}`, {created})."


def missing(relative: str) -> list[str]:
    return [f"{NOT_MEASURED}: `ml/experiments/{relative}` does not exist.", ""]


def forecast_section(root: Path) -> list[str]:
    out = ["## Forecast: baselines vs LightGBM", ""]
    for label, relative in (
        ("Synthetic world", "forecast/synthetic.json"),
        ("Real data (Online Retail II)", "forecast/real.json"),
    ):
        art = load(root, relative)
        out += [f"### {label}", ""]
        if art is None:
            out += missing(relative)
            continue
        ds = art["dataset"]
        out.append(
            f"{ds['n_series']} series, {ds['n_weeks']} weeks, test from {ds['test_start']} "
            f"({ds['test_weeks']} weeks x {art['config']['horizons']} horizons)."
        )
        out.append("")
        rows = []
        for name, result in art["baselines"].items():
            m = result["test"]["overall"]
            rows.append(
                [name, num(m["mae"]), num(m["rmse"]), num(m["wape"]), num(m["bias"]), "n/a"]
            )
        m = art["model"]["test"]["overall"]
        coverage = art["intervals"]["test"]["calibrated"]["overall"]["coverage"]
        rows.append(
            [
                f"**LightGBM** `{art['model_version']}`",
                num(m["mae"]),
                num(m["rmse"]),
                num(m["wape"]),
                num(m["bias"]),
                num(coverage),
            ]
        )
        out += table(["Model", "MAE", "RMSE", "WAPE", "Bias", "80% interval coverage"], rows)
        out += [
            "",
            "Test MAE improvement over the selected baseline "
            f"(`{art['selected_baseline']}`, chosen on "
            f"validation): **{pct(art['test_mae_improvement_vs_selected_baseline'])}**.",
            source(relative, art),
            "",
        ]
    return out


POLICY_LABELS = {
    "heuristic_cheapest": "cheapest supplier",
    "heuristic_weighted": "weighted ranking",
    "milp": "MILP optimizer",
}


def optimization_section(root: Path) -> list[str]:
    relative = "optimization/synthetic.json"
    art = load(root, relative)
    out = ["## Sourcing and procurement: cheapest vs ranking vs optimizer", ""]
    if art is None:
        return out + missing(relative)
    out.append(
        f"Demand: {art['demand_source']} ({num(art['total_forecast_demand_units'], 1)} units, "
        f"{art['procurement_params']['horizon_weeks']}-week horizon, service target "
        f"{pct(art['procurement_params']['service_level_target'], 0)})."
    )
    out.append("")
    for case in art["cases"].values():
        budget = case.get("budget")
        title = "Base case" if budget is None else f"Tight budget ({num(budget, 0)})"
        out += [f"### {title}", ""]
        rows = [
            [
                label,
                num(case[key]["objective"], 0),
                num(case[key]["spend"], 0),
                num(case[key]["fill_rate"]),
                num(case[key]["unmet_demand"], 1),
                num(case[key]["constraint_violations"]["count"]),
                num(case[key]["runtime_seconds"], 2),
            ]
            for key, label in POLICY_LABELS.items()
        ]
        out += table(
            [
                "Policy",
                "Total cost (objective)",
                "Spend",
                "Fill rate",
                "Unmet units",
                "Constraint violations",
                "Runtime (s)",
            ],
            rows,
        )
        out.append("")

    out += [
        "## Inventory: nearest-warehouse rule vs optimized allocation",
        "",
        "Base case: the stock each procurement plan produces, shipped to regional demand.",
        "",
    ]
    rows = []
    for key, label in POLICY_LABELS.items():
        for policy, result in art["cases"]["base"][key]["allocation"].items():
            rows.append(
                [
                    label,
                    "optimized (MILP)" if policy == "milp" else policy.replace("_", " "),
                    num(result["fill_rate"]),
                    num(result["unmet_units"]),
                    num(result["shipping_cost"], 0),
                    num(result["mean_transit_days"], 2),
                    num(result["constraint_violations"]["count"]),
                ]
            )
    out += table(
        [
            "Procurement plan",
            "Allocation",
            "Fill rate",
            "Unmet units",
            "Shipping cost",
            "Mean transit days",
            "Violations",
        ],
        rows,
    )
    out += ["", source(relative, art), ""]
    return out


def scenario_section(root: Path) -> list[str]:
    relative = "scenario/synthetic.json"
    art = load(root, relative)
    out = ["## Scenarios: baseline vs disrupted vs optimized response", ""]
    if art is None:
        return out + missing(relative)
    rows = []
    for s in art["scenarios"]:
        rows.append(
            [
                s["name"],
                num(s["baseline"]["fill_rate"]),
                num(s["disrupted"]["fill_rate"]),
                num(s["response"]["fill_rate"]),
                num(s["baseline"]["objective"], 0),
                num(s["disrupted"]["objective"], 0),
                num(s["response"]["objective"], 0),
                num(s["response_benefit"], 0),
            ]
        )
    out += table(
        [
            "Scenario",
            "Fill: baseline",
            "Fill: disrupted plan",
            "Fill: re-optimized",
            "Cost: baseline",
            "Cost: disrupted plan",
            "Cost: re-optimized",
            "Saved by re-optimizing",
        ],
        rows,
    )
    out += [
        "",
        "Disrupted plan = the baseline plan kept unchanged under the scenario; re-optimized = the "
        "optimizer re-run with the scenario's changes. Costs include stockout penalties.",
        source(relative, art),
        "",
    ]
    return out


def rag_section(root: Path) -> list[str]:
    out = ["## RAG: retrieval, citations, groundedness", ""]
    rows = []
    sources: list[str] = []
    last: Artifact | None = None
    for relative in ("rag/synthetic-fastembed.json", "rag/synthetic-hashing.json"):
        art = load(root, relative)
        if art is None:
            rows.append([relative, NOT_MEASURED, "", "", "", "", "", ""])
            continue
        ret, ans = art["retrieval"], art["answers"]
        rows.append(
            [
                f"`{art['embedder']}`",
                num(ret["hit@1"]),
                num(ret["hit@5"]),
                num(ret["mrr"]),
                num(ans["citation_accuracy"]),
                num(ans["groundedness"]),
                num(ans["answer_accuracy"]),
                num(ans["restricted_leaks"]),
            ]
        )
        sources.append(source(relative, art))
        last = art
    out += table(
        [
            "Embedder",
            "Hit@1",
            "Hit@5",
            "MRR",
            "Citation accuracy",
            "Groundedness",
            "Answer accuracy",
            "Restricted leaks",
        ],
        rows,
    )
    out.append("")
    if last is not None:
        out += [
            f"{last['cases']} questions over {last['documents']} documents; answers from the "
            f"`{last['generator']}` generator. Claude-generated answers: "
            f"{last.get('llm_generator_metrics', NOT_MEASURED)}.",
            *sources,
            "",
        ]
    return out


AGENT_DIMENSIONS = (
    "tool_correctness",
    "parameter_correctness",
    "sequence_correctness",
    "constraint_compliance",
    "permission_compliance",
    "action_safety",
    "grounded_numbers",
    "appropriate_refusal",
)


FIRST_RUNS = (
    ("holdout-v2", "agent/synthetic-rule-planner-v2-first-run.json"),
    ("holdout-v3", "agent/synthetic-rule-planner-v3-first-run.json"),
    ("holdout-v4", "agent/synthetic-rule-planner-v4-first-run.json"),
)


def agent_section(root: Path) -> list[str]:
    relative = "agent/synthetic-rule-planner.json"
    art = load(root, relative)
    out = ["## Agent: workflow and tool use", ""]
    if art is None:
        return out + missing(relative)

    # each unseen set is scored once, before anything is changed because of it
    first = [
        [
            f"`{split}`",
            num(run["by_split"][split]["workflow_success"]),
            num(run["by_split"][split]["cases"]),
        ]
        for split, path in FIRST_RUNS
        if (run := load(root, path)) is not None and split in run["by_split"]
    ]
    if first:
        out += table(["Unseen set, first and only scoring", "Workflow success", "Cases"], first)
        out += [
            "",
            "Each unseen set was committed before the planner changes it measures and scored once;"
            " after that it counts as seen. Planner changes between sets are in the git history.",
            "",
        ]

    rows = [["workflow success (all cases)", num(art["workflow_success"]), num(art["cases"])]]
    for split, result in art["by_split"].items():
        rows.append(
            [f"workflow success ({split})", num(result["workflow_success"]), num(result["cases"])]
        )
    for dim in AGENT_DIMENSIONS:
        d = art["dimensions"].get(dim)
        if d is not None:
            rows.append([dim.replace("_", " "), num(d["pass_rate"]), num(d["applicable"])])
    out += table(["Metric (current planner, all cases)", "Pass rate", "Cases"], rows)
    out += [
        "",
        f"Planner: `{art['planner']}` (keyword rules plus embedding-based intent matching, offline,"
        " deterministic). The current scores include cases that were used to improve the planner,"
        " so the first-run scores above are the honest measure of unseen requests."
        f" Claude planner: {art.get('llm_planner_metrics', NOT_MEASURED)}.",
        source(relative, art),
        "",
    ]
    return out


def feedback_section(root: Path) -> list[str]:
    out = ["## Feedback loop: planned vs simulated actuals", ""]
    relative = "feedback/synthetic.json"
    art = load(root, relative)
    if art is None:
        out += missing(relative)
    else:
        fc = art["forecast"]
        rows = [
            [
                label,
                num(fc[key]["overall"]["mae"]),
                num(fc[key]["overall"]["bias"]),
                num(fc[key]["overall"]["wape"]),
                num(fc[key]["overall"]["coverage"]) if key == "model" else "n/a",
            ]
            for key, label in (
                ("model", "LightGBM (served)"),
                ("moving_average_13", "13-week moving average"),
            )
        ]
        out += [
            f"Decision at {art['as_of']}: forecast {fc['horizons']} weeks for "
            f"{fc['series']} series, plan "
            f"with the MILP. Approval: {art['decision']['approval']}.",
            "",
        ]
        out += table(["Forecast vs actual demand", "MAE", "Bias", "WAPE", "80% coverage"], rows)
        planned, actual = art["inventory"]["planned"], art["inventory"]["actual"]
        out += [""] + table(
            ["Inventory over the plan horizon", "Planned", "Actual"],
            [
                ["demand units", num(planned["demand_units"], 1), num(actual["demand_units"], 1)],
                ["fill rate (weekly path)", num(planned["fill_rate"]), num(actual["fill_rate"])],
                ["unmet units", num(planned["unmet_units"], 1), num(actual["unmet_units"], 1)],
                [
                    "stockout cell-weeks",
                    num(planned["stockout_cell_weeks"]),
                    num(actual["stockout_cell_weeks"]),
                ],
            ],
        )
        orders = art["deliveries"]["plan_orders"]["overall"]
        out += [
            "",
            f"Supplier deliveries for the plan's {orders['orders']} orders: on-time rate "
            f"{num(orders['on_time_rate'])}, in-full rate {num(orders['in_full_rate'])}, "
            "unit fill rate "
            f"{num(orders['unit_fill_rate'])}.",
            "Actuals are simulated by continuing the synthetic world's own process past "
            "`as_of`; they "
            "are not real outcomes ([feedback-loop.md](feedback-loop.md)).",
            source(relative, art),
            "",
        ]

    relative = "feedback/retraining-synthetic.json"
    art = load(root, relative)
    out += ["### Retraining gate", ""]
    if art is None:
        return out + missing(relative)
    scores = art["scores"]
    rows = [
        [
            f"{label} `{scores[key].get('model_version', '')}`".replace(" ``", ""),
            num(scores[key]["mae"]),
            num(scores[key]["bias"]),
            num(scores[key].get("coverage")),
        ]
        for key, label in (
            ("current", "current model"),
            ("candidate", "retrained candidate"),
            ("moving_average_13", "13-week moving average"),
        )
        if key in scores
    ]
    out += table(["Held-out captured weeks", "MAE", "Bias", "80% coverage"], rows)
    out += [
        "",
        f"Gate status: `{art['status']}` "
        f"({'; '.join(art['gate'].get('reasons', [])) or 'passed'}). "
        "Nothing is deployed without the gate and a named approval.",
        source(relative, art),
        "",
    ]
    return out


def systems_section(root: Path) -> list[str]:
    out = ["## Systems: latency, throughput, worker scaling", ""]
    relative = "systems/api-latency.json"
    art = load(root, relative)
    out += ["### API latency", ""]
    if art is None:
        out += missing(relative)
    else:
        rows = [
            [
                f"`{name}`",
                num(r["samples"]),
                num(r["p50_ms"], 1),
                num(r["p95_ms"], 1),
                num(r["max_ms"], 1),
                num(r.get("rate_limited_retries")),
            ]
            for name, r in art["endpoints"].items()
        ]
        out += table(
            ["Call", "Samples", "p50 (ms)", "p95 (ms)", "max (ms)", "429s waited out"], rows
        )
        out += ["", f"Deployment: {art['deployment']}; {art['method']}.", source(relative, art), ""]

    relative = "systems/worker-scaling.json"
    art = load(root, relative)
    out += ["### Job throughput and worker scaling", ""]
    if art is None:
        return out + missing(relative)
    by_replicas: dict[int, list[Artifact]] = {}
    for run in art["runs"]:
        if not run.get("disrupted") and run["failed"] == 0 and not run.get("host_suspended"):
            by_replicas.setdefault(int(run["replicas"]), []).append(run)
    base: float | None = None
    rows = []
    for replicas in sorted(by_replicas):
        runs = by_replicas[replicas]
        throughput = sorted(r["throughput_jobs_per_min"] for r in runs)[len(runs) // 2]
        base = base if base is not None else throughput / replicas
        rows.append(
            [
                num(replicas),
                num(len(runs)),
                num(throughput, 1),
                f"{throughput / (base * replicas):.2f}",
                num(sorted(r["run_s"]["p50"] for r in runs)[len(runs) // 2], 2),
            ]
        )
    out += table(
        [
            "Workers",
            "Runs",
            "Median throughput (jobs/min)",
            "Scaling efficiency",
            "Median job run p50 (s)",
        ],
        rows,
    )
    out += [
        "",
        f"Workload: {art['workload']['jobs']} {art['workload']['type']} jobs "
        f"({art['workload']['plan']}) "
        f"on {art['cluster']['context']}; {art['cluster']['scaling_unit']}. Runs with an injected "
        "disruption are reported in [kubernetes.md](kubernetes.md).",
        source(relative, art),
        "",
    ]
    return out


SECTIONS: tuple[Callable[[Path], list[str]], ...] = (
    forecast_section,
    optimization_section,
    scenario_section,
    rag_section,
    agent_section,
    feedback_section,
    systems_section,
)


def render(root: Path) -> str:
    lines = [
        "# Benchmark results",
        "",
        "Generated by `uv run python -m scm_ml.benchmark.report` from the saved artifacts under "
        "`ml/experiments/` (regenerate everything with `bash scripts/benchmark.sh`). Do "
        "not edit by "
        f"hand. A metric without an artifact is shown as {NOT_MEASURED}.",
        "",
        "All planning results use the deterministic synthetic world (seed 42, as of 2024-12-30) "
        "unless a row says otherwise; they describe this simulated company, not real operations.",
        "",
    ]
    for section in SECTIONS:
        lines += section(root)
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the benchmark report from saved artifacts.")
    parser.add_argument("--experiments", type=Path, default=DEFAULT_EXPERIMENTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    args.out.write_text(render(args.experiments), encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
