"""CLI: ``python -m scm_ml.agent`` runs the fixed agent evaluation and saves the artifact.

``--planner rule`` (default) is offline and deterministic. ``--planner claude`` plans and writes
RAG answers with Claude and needs ``ANTHROPIC_API_KEY``; it spends API credits, one run per case.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from scm_ml.forecast.artifacts import DEFAULT_ARTIFACT_ROOT
from scm_ml.knowledge import ClaudeGenerator, Embedder, FastEmbedEmbedder, HashingEmbedder
from scm_ml.llm import ClaudeJsonLlm
from scm_ml.optimization.benchmark import forecast_artifact_dirs
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticConfig, generate_world

from .context import PlanningContext, build_planning_context
from .evaluation import EXPERIMENT_DIR, run_agent_evaluation
from .planner import ClaudePlanner, Planner, RulePlanner
from .tools import default_registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the planning agent.")
    parser.add_argument("--planner", choices=["rule", "claude"], default="rule")
    parser.add_argument("--embedder", choices=["fastembed", "hashing"], default="fastembed")
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.planner == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; the Claude planner cannot run.", file=sys.stderr)
        return 2

    world = generate_world(SyntheticConfig())
    model_dir, dataset_dir = forecast_artifact_dirs(world, args.artifacts)
    service = ForecastService.from_directories(model_dir, dataset_dir)
    embedder: Embedder = FastEmbedEmbedder() if args.embedder == "fastembed" else HashingEmbedder()
    llm = ClaudeJsonLlm() if args.planner == "claude" else None
    context = build_planning_context(
        world, service, embedder=embedder, generator=ClaudeGenerator(llm) if llm else None
    )

    def planner_factory(ctx: PlanningContext) -> Planner:
        return ClaudePlanner(llm, default_registry()) if llm else RulePlanner(ctx)

    name = "claude" if llm else "rule"
    out = args.out or EXPERIMENT_DIR / f"synthetic-{name}-planner.json"
    result = run_agent_evaluation(context, planner_factory, out, planner_name=name)

    print(f"planner {name}  cases {result['cases']}  embedder {embedder.name}")
    print(
        f"workflow success {result['workflow_success']:.3f}  status {result['status_accuracy']:.3f}"
    )
    for dimension, stats in result["dimensions"].items():
        print(f"  {dimension:24s} {stats['pass_rate']:.3f}  ({stats['applicable']} cases)")
    for split, stats in result["by_split"].items():
        print(f"  split {split}: {stats['workflow_success']:.3f} ({stats['cases']} cases)")
    for case_id in result["failures"]:
        print(f"  FAIL {case_id}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
