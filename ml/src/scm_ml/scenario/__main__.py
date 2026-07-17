from __future__ import annotations

import argparse
from pathlib import Path

from scm_ml.forecast.artifacts import DEFAULT_ARTIFACT_ROOT
from scm_ml.optimization.benchmark import forecast_artifact_dirs
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticConfig, generate_world

from .suite import EXPERIMENT_PATH, run_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the standard disruption scenarios.")
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--out", type=Path, default=EXPERIMENT_PATH)
    args = parser.parse_args(argv)

    world = generate_world(SyntheticConfig())
    model_dir, dataset_dir = forecast_artifact_dirs(world, args.artifacts)
    result = run_suite(
        world, ForecastService.from_directories(model_dir, dataset_dir), None, args.out
    )
    print(f"baseline objective {result['baseline_objective']:,.0f}")
    header = (
        f"{'scenario':32s} {'disrupted':>10s} {'response':>10s} {'resil.cost':>11s} {'fill d':>8s}"
    )
    print(header)
    for item in result["scenarios"]:
        print(
            f"{item['name']:32s} {item['objective_delta_disrupted']['absolute']:>+10,.0f}"
            f" {item['objective_delta_response']['absolute']:>+10,.0f}"
            f" {item['resilience_cost']:>+11,.0f} {item['service_level_delta_response']:>+8.4f}"
        )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
