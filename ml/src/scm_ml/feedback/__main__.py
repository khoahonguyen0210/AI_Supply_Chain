"""CLI for the feedback loop (see docs/feedback-loop.md).

python -m scm_ml.feedback evaluate                  # simulate actuals, evaluate the decision
python -m scm_ml.feedback retrain                   # candidate model + promotion report
python -m scm_ml.feedback promote --report R --approved-by USER
python -m scm_ml.feedback serving                   # which model is served
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scm_ml.forecast.artifacts import DEFAULT_ARTIFACT_ROOT, write_json
from scm_ml.forecast.model import load_model
from scm_ml.forecast.panel import load_dataset
from scm_ml.optimization.benchmark import forecast_artifact_dirs
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticConfig, generate_world

from .actuals import SIMULATED
from .experiment import EXPERIMENT_PATH, OUTCOME_DIR, run_feedback_experiment, sha256_file
from .retraining import (
    HOLDOUT_WEEKS,
    REPORT_PATH,
    SERVING_FILE,
    PromotionError,
    PromotionGate,
    promote,
    read_actuals,
    retrain,
    serving_directories,
)


def _evaluate(args: argparse.Namespace) -> int:
    world = generate_world(SyntheticConfig())
    service = ForecastService.from_directories(*forecast_artifact_dirs(world, args.artifacts))
    result = run_feedback_experiment(service, out_dir=args.outcomes)
    forecast = result["forecast"]["model"]["overall"]
    decision, inventory = result["decision"], result["inventory"]
    plan_deliveries = result["deliveries"]["plan_orders"]["overall"]
    print(f"actuals: {result['actuals_source']}  weeks {result['actuals']['weeks']}")
    print(
        f"forecast vs actual: MAE {forecast['mae']:.3f}  bias {forecast['bias']:+.3f}  "
        f"WAPE {forecast['wape']:.3f}  80% coverage {forecast['coverage']:.3f}"
    )
    print(
        f"plan: {decision['purchase_orders']} orders, planned fill rate "
        f"{decision['planned_fill_rate']:.3f}; actual fill rate {inventory['actual']['fill_rate']}"
    )
    print(
        f"plan deliveries: on time {plan_deliveries['on_time_rate']}  "
        f"unit fill {plan_deliveries['unit_fill_rate']}"
    )
    print(f"wrote {EXPERIMENT_PATH} and {args.outcomes}/")
    return 0


def _retrain(args: argparse.Namespace) -> int:
    root: Path = args.artifacts
    if args.model_dir and args.dataset_dir:
        model_dir, dataset_dir = args.model_dir, args.dataset_dir
    else:
        served = serving_directories(root)
        model_dir, dataset_dir = served or forecast_artifact_dirs(
            generate_world(SyntheticConfig()), root
        )
    history, _ = load_dataset(dataset_dir)
    report = retrain(
        load_model(model_dir),
        history,
        read_actuals(args.actuals),
        actuals_label=args.label,
        actuals_sha256=sha256_file(args.actuals),
        holdout_weeks=args.holdout_weeks,
        gate=PromotionGate(
            min_mae_improvement=args.min_improvement, max_coverage_error=args.max_coverage_error
        ),
        root=root,
    )
    if args.report is not None:
        write_json(args.report, report)
    scores = report["scores"]
    for name in ("current", "candidate"):
        s = scores[name]
        print(
            f"  {name:9s} {s['model_version']}  held-out MAE {s['mae']:.4f}  "
            f"coverage {s['coverage']:.3f}"
        )
    print(f"gate: {'PASSED' if report['gate']['passed'] else 'FAILED'} -> {report['status']}")
    for reason in report["gate"]["reasons"]:
        print(f"  - {reason}")
    print(f"report: {args.report or root / report['candidate']['artifact_dir']}")
    print("nothing was deployed; promotion needs `promote --approved-by <user>`")
    return 0


def _promote(args: argparse.Namespace) -> int:
    try:
        entry = promote(args.report, args.approved_by, root=args.artifacts, note=args.note)
    except PromotionError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    print(f"serving {entry['model_version']} (approved by {entry['approved_by']})")
    print("restart the engine to load it")
    return 0


def _serving(args: argparse.Namespace) -> int:
    path = args.artifacts / SERVING_FILE
    if not path.exists():
        print("no promotion recorded: the engine serves the model trained on the world's history")
        return 0
    print(json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Outcome evaluation and retraining.")
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)

    evaluate = commands.add_parser("evaluate", help="simulate actuals and evaluate the decision")
    evaluate.add_argument("--outcomes", type=Path, default=OUTCOME_DIR)
    evaluate.set_defaults(run=_evaluate)

    retraining = commands.add_parser("retrain", help="train and score a candidate model")
    retraining.add_argument("--actuals", type=Path, default=OUTCOME_DIR / "demand_actuals.csv")
    retraining.add_argument("--label", choices=[SIMULATED, "RECORDED"], default=SIMULATED)
    retraining.add_argument("--model-dir", type=Path)
    retraining.add_argument("--dataset-dir", type=Path)
    retraining.add_argument("--holdout-weeks", type=int, default=HOLDOUT_WEEKS)
    retraining.add_argument("--min-improvement", type=float, default=0.0)
    retraining.add_argument("--max-coverage-error", type=float, default=0.10)
    retraining.add_argument("--report", type=Path, default=REPORT_PATH)
    retraining.set_defaults(run=_retrain)

    promotion = commands.add_parser("promote", help="serve an approved, gate-passing candidate")
    promotion.add_argument("--report", type=Path, required=True)
    promotion.add_argument("--approved-by", required=True)
    promotion.add_argument("--note")
    promotion.set_defaults(run=_promote)

    serving = commands.add_parser("serving", help="show the promoted model, if any")
    serving.set_defaults(run=_serving)

    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
