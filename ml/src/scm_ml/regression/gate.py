from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from scm_ml.agent.context import PlanningContext, build_planning_context
from scm_ml.agent.evaluation import run_agent_evaluation
from scm_ml.agent.planner import Planner, RulePlanner
from scm_ml.forecast.artifacts import provenance, read_json, write_json
from scm_ml.forecast.experiment import run_forecast_experiment
from scm_ml.forecast.panel import default_split, panel_from_world
from scm_ml.knowledge import Embedder, FastEmbedEmbedder, HashingEmbedder
from scm_ml.knowledge.answering import ExtractiveGenerator, GroundedAnswerer
from scm_ml.knowledge.corpus import build_corpus
from scm_ml.knowledge.embedding import EMBEDDING_DIM
from scm_ml.knowledge.evaluation import run_evaluation
from scm_ml.knowledge.retrieval import Retriever
from scm_ml.knowledge.store import KnowledgeStore, ingest
from scm_ml.optimization.benchmark import forecast_artifact_dirs
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticConfig, SyntheticWorld, generate_world

BASELINE_PATH = Path("ml/configs/ai-regression-baseline.json")
DEFAULT_OUT = Path("ml/artifacts/regression")
BASELINE_VERSION = 1

Better = Literal["higher", "lower"]

# Tracked metrics: dotted path into each evaluation result -> which direction is better.
TRACKED: dict[str, dict[str, Better]] = {
    "rag": {
        "retrieval.hit@1": "higher",
        "retrieval.hit@3": "higher",
        "retrieval.hit@5": "higher",
        "retrieval.mrr": "higher",
        "answers.status_accuracy": "higher",
        "answers.answer_accuracy": "higher",
        "answers.citation_accuracy": "higher",
        "answers.groundedness": "higher",
        "answers.over_refusal_rate": "lower",
        "answers.wrong_answer_rate": "lower",
        "answers.restricted_leaks": "lower",
    },
    "agent": {
        "workflow_success": "higher",
        "status_accuracy": "higher",
        **{
            f"dimensions.{name}.pass_rate": "higher"
            for name in (
                "tool_correctness",
                "sequence_correctness",
                "parameter_correctness",
                "constraint_compliance",
                "grounded_numbers",
                "permission_compliance",
                "appropriate_refusal",
                "replanning",
                "action_safety",
            )
        },
    },
}


@dataclass
class SuiteOutcome:
    suite: str
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.regressions


def lookup(result: dict[str, Any], path: str) -> float:
    node: Any = result
    for key in path.split("."):
        node = node[key]
    if not isinstance(node, int | float):
        raise TypeError(f"{path} is not a number: {node!r}")
    return float(node)


def failed_cases(suite: str, result: dict[str, Any]) -> list[str]:
    failures = result["failures"]
    ids = [row["case_id"] for row in failures] if suite == "rag" else list(failures)
    return sorted(ids)


def case_ids(result: dict[str, Any]) -> list[str]:
    return sorted(row["case_id"] for row in result["results"])


def snapshot(suite: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "cases": case_ids(result),
        "known_failures": failed_cases(suite, result),
        "metrics": {
            path: {"value": lookup(result, path), "better": better}
            for path, better in TRACKED[suite].items()
        },
    }


def compare(
    suite: str, result: dict[str, Any], baseline: dict[str, Any], tolerance: float
) -> SuiteOutcome:
    outcome = SuiteOutcome(suite)
    expected_cases, actual_cases = set(baseline["cases"]), set(case_ids(result))
    if expected_cases != actual_cases:
        added, removed = (
            sorted(actual_cases - expected_cases),
            sorted(expected_cases - actual_cases),
        )
        outcome.regressions.append(
            f"evaluation set changed (added {added}, removed {removed}); "
            "regenerate the baseline with --update-baseline if this is intended"
        )
    known, failing = set(baseline["known_failures"]), set(failed_cases(suite, result))
    outcome.regressions += [f"case {c} now fails" for c in sorted(failing - known)]
    outcome.improvements += [f"case {c} now passes" for c in sorted(known - failing)]
    for path, entry in baseline["metrics"].items():
        before, after, better = float(entry["value"]), lookup(result, path), entry["better"]
        worse = after < before - tolerance if better == "higher" else after > before + tolerance
        improved = after > before + tolerance if better == "higher" else after < before - tolerance
        outcome.metrics[path] = {
            "baseline": before,
            "current": after,
            "better": better,
            "status": "worse" if worse else "better" if improved else "same",
        }
        if worse:
            outcome.regressions.append(f"{path} {before:.3f} -> {after:.3f}")
        elif improved:
            outcome.improvements.append(f"{path} {before:.3f} -> {after:.3f}")
    return outcome


def make_embedder(name: str) -> Embedder:
    return FastEmbedEmbedder() if name == "fastembed" else HashingEmbedder()


def ensure_forecast_service(world: SyntheticWorld, artifact_root: Path) -> ForecastService:
    try:
        model_dir, dataset_dir = forecast_artifact_dirs(world, artifact_root)
    except FileNotFoundError:
        panel = panel_from_world(world)
        run_forecast_experiment(panel, default_split(panel), artifact_root)
        model_dir, dataset_dir = forecast_artifact_dirs(world, artifact_root)
    return ForecastService.from_directories(model_dir, dataset_dir)


def run_suites(embedder_name: str, artifact_root: Path, out_dir: Path) -> dict[str, Any]:
    world = generate_world(SyntheticConfig())
    embedder = make_embedder(embedder_name)

    corpus = build_corpus(world)
    store = KnowledgeStore(EMBEDDING_DIM)
    ingest(corpus.documents, embedder, store)
    retriever = Retriever(store, embedder)
    rag = run_evaluation(
        corpus,
        retriever,
        GroundedAnswerer(retriever, ExtractiveGenerator()),
        out_dir / "rag.json",
        embedder=embedder.name,
    )

    service = ensure_forecast_service(world, artifact_root)
    context = build_planning_context(world, service, embedder=embedder)

    def planner_factory(ctx: PlanningContext) -> Planner:
        return RulePlanner(ctx)

    agent = run_agent_evaluation(
        context, planner_factory, out_dir / "agent.json", planner_name="rule"
    )
    return {"rag": rag, "agent": agent}


def build_baseline(embedder_name: str, results: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": BASELINE_VERSION,
        "embedder": embedder_name,
        "planner": "rule",
        "rag_generator": "extractive-stub",
        **{suite: snapshot(suite, result) for suite, result in results.items()},
        "provenance": provenance(),
    }


def render_markdown(outcomes: list[SuiteOutcome], baseline: dict[str, Any]) -> str:
    lines = [
        "# AI regression suite",
        "",
        f"Baseline: embedder `{baseline['embedder']}`, planner `{baseline['planner']}`, "
        f"RAG generator `{baseline['rag_generator']}`, "
        f"recorded at `{baseline['provenance']['code_revision']}`.",
        "",
    ]
    for outcome in outcomes:
        verdict = "PASS" if outcome.passed else "FAIL"
        lines += [f"## {outcome.suite}: {verdict}", "", "| Metric | Baseline | Current | |"]
        lines.append("|---|---|---|---|")
        for path, row in outcome.metrics.items():
            lines.append(
                f"| {path} | {row['baseline']:.3f} | {row['current']:.3f} | {row['status']} |"
            )
        lines.append("")
        lines += [f"- regression: {item}" for item in outcome.regressions]
        lines += [f"- improvement: {item}" for item in outcome.improvements]
        lines.append("")
    return "\n".join(lines)


def run_gate(
    *,
    baseline_path: Path = BASELINE_PATH,
    artifact_root: Path,
    out_dir: Path = DEFAULT_OUT,
    tolerance: float = 1e-9,
    update_baseline: bool = False,
    embedder_name: str | None = None,
) -> tuple[bool, list[SuiteOutcome]]:
    baseline = read_json(baseline_path) if baseline_path.exists() else None
    if baseline is None and not update_baseline:
        raise FileNotFoundError(f"no baseline at {baseline_path}; create it with --update-baseline")
    name = embedder_name or (baseline["embedder"] if baseline else "fastembed")
    if baseline is not None and not update_baseline and name != baseline["embedder"]:
        raise ValueError(f"baseline was recorded with {baseline['embedder']}, not {name}")

    results = run_suites(name, artifact_root, out_dir)
    if update_baseline:
        baseline = build_baseline(name, results)
        write_json(baseline_path, baseline)
    assert baseline is not None
    outcomes = [compare(s, results[s], baseline[s], tolerance) for s in ("rag", "agent")]
    passed = all(o.passed for o in outcomes)
    report = {
        "passed": passed,
        "baseline": str(baseline_path),
        "baseline_revision": baseline["provenance"]["code_revision"],
        "suites": {
            o.suite: {
                "passed": o.passed,
                "regressions": o.regressions,
                "improvements": o.improvements,
                "metrics": o.metrics,
            }
            for o in outcomes
        },
        "provenance": provenance(),
    }
    write_json(out_dir / "report.json", report)
    (out_dir / "report.md").write_text(render_markdown(outcomes, baseline), encoding="utf-8")
    return passed, outcomes
