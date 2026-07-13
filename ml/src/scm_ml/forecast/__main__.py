from __future__ import annotations

import argparse
from pathlib import Path

from scm_ml.synthetic import SyntheticConfig, generate_world

from .artifacts import DEFAULT_ARTIFACT_ROOT, write_json
from .experiment import EXPERIMENT_ROOT, run_forecast_experiment
from .panel import ForecastPanel, default_split, panel_from_real, panel_from_world


def load_panel(source: str, real_dir: Path) -> ForecastPanel:
    if source == "synthetic":
        return panel_from_world(generate_world(SyntheticConfig()))
    return panel_from_real(real_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the forecasting experiment.")
    parser.add_argument("--source", choices=["synthetic", "real"], default="synthetic")
    parser.add_argument("--real-dir", type=Path, default=Path("data/real_demand"))
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    args = parser.parse_args(argv)

    panel = load_panel(args.source, args.real_dir)
    split = default_split(panel)
    result = run_forecast_experiment(panel, split, args.artifacts)
    print(f"dataset {panel.dataset_id}  model {result['model_version']}")
    rows = {
        **{n: m["test"] for n, m in result["baselines"].items()},
        "lightgbm": result["model"]["test"],
    }
    for name, per_window in rows.items():
        overall = per_window["overall"]
        mae, rmse, bias = overall["mae"], overall["rmse"], overall["bias"]
        print(f"  {name:18s} test MAE {mae:.3f}  RMSE {rmse:.3f}  bias {bias:+.3f}")
    print(f"selected baseline (validation MAE): {result['selected_baseline']}")
    print(
        "test MAE improvement vs selected baseline: "
        f"{result['test_mae_improvement_vs_selected_baseline']:+.1%}"
    )
    for window in ("validation", "test"):
        for label, cover in result["intervals"][window].items():
            overall = cover["overall"]
            coverage, width = overall["coverage"], overall["mean_width"]
            print(f"  80% interval [{window}, {label}]: coverage {coverage:.3f}  width {width:.1f}")
    write_json(EXPERIMENT_ROOT / f"{args.source}.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
