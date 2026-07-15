from __future__ import annotations

import argparse
from pathlib import Path

from scm_ml.forecast.artifacts import DEFAULT_ARTIFACT_ROOT
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticConfig, generate_world

from .benchmark import EXPERIMENT_PATH, forecast_artifact_dirs, run_benchmark


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark procurement and allocation optimization."
    )
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--out", type=Path, default=EXPERIMENT_PATH)
    args = parser.parse_args(argv)

    world = generate_world(SyntheticConfig())
    model_dir, dataset_dir = forecast_artifact_dirs(world, args.artifacts)
    service = ForecastService.from_directories(model_dir, dataset_dir)
    result = run_benchmark(world, service, out_path=args.out)
    for case, methods in result["cases"].items():
        print(case)
        for name, row in methods.items():
            if not isinstance(row, dict):
                continue
            violations = row["constraint_violations"]["count"]
            print(
                f"  {name:20s} objective {row['objective']:>12,.0f}  fill {row['fill_rate']:.3f}"
                f"  violations {violations:>3d}  {row['runtime_seconds']:.2f}s"
            )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
