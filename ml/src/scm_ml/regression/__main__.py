from __future__ import annotations

import argparse
import os
from pathlib import Path

from scm_ml.forecast.artifacts import DEFAULT_ARTIFACT_ROOT

from .gate import BASELINE_PATH, DEFAULT_OUT, run_gate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AI regression suite.")
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--tolerance", type=float, default=1e-9)
    parser.add_argument("--embedder", choices=["fastembed", "hashing"], default=None)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="record this run as the new baseline (review the diff before committing it)",
    )
    args = parser.parse_args(argv)

    passed, outcomes = run_gate(
        baseline_path=args.baseline,
        artifact_root=args.artifacts,
        out_dir=args.out,
        tolerance=args.tolerance,
        update_baseline=args.update_baseline,
        embedder_name=args.embedder,
    )
    for outcome in outcomes:
        print(f"{outcome.suite}: {'PASS' if outcome.passed else 'FAIL'}")
        for item in outcome.regressions:
            print(f"  regression: {item}")
        for item in outcome.improvements:
            print(f"  improvement: {item}")
    report = (args.out / "report.md").read_text(encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report)
    print(f"artifacts in {args.out}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
