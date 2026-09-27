"""CLI: draw the README results figure (SVG) from saved artifacts.

uv run python -m scm_ml.benchmark.figure
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from pathlib import Path

from .report import DEFAULT_EXPERIMENTS, Artifact, load

DEFAULT_OUT = Path("docs/images/results.svg")

WIDTH = 960
COLUMNS = 3
PANEL_W = WIDTH // COLUMNS
PANEL_H = 210
HEADER_H = 64
LABEL_W = 118
BAR_H = 20
BAR_GAP = 14

STYLE = """
.surface { fill: #fcfcfb; }
.title { fill: #0b0b0b; font: 600 14px system-ui, -apple-system, 'Segoe UI', sans-serif; }
.note { fill: #52514e; font: 12px system-ui, -apple-system, 'Segoe UI', sans-serif; }
.label { fill: #52514e; font: 12px system-ui, -apple-system, 'Segoe UI', sans-serif; }
.value { fill: #0b0b0b; font: 600 12px system-ui, -apple-system, 'Segoe UI', sans-serif; }
.axis { stroke: #e1e0d9; stroke-width: 1; }
.ours { fill: #2a78d6; }
.reference { fill: #898781; }
@media (prefers-color-scheme: dark) {
  .surface { fill: #1a1a19; }
  .title, .value { fill: #ffffff; }
  .note, .label { fill: #c3c2b7; }
  .axis { stroke: #2c2c2a; }
  .ours { fill: #3987e5; }
}
"""


@dataclass(frozen=True)
class Bar:
    label: str
    value: float
    ours: bool
    text: str


@dataclass(frozen=True)
class Panel:
    title: str
    note: str
    bars: list[Bar]


def _forecast(art: Artifact, title: str) -> Panel:
    baseline = art["selected_baseline"]
    ref = art["baselines"][baseline]["test"]["overall"]["mae"]
    model = art["model"]["test"]["overall"]["mae"]
    return Panel(
        title,
        f"units off per week, lower is better ({100 * (1 - model / ref):.1f}% smaller error)",
        [
            Bar(
                "13-week average" if baseline == "moving_average_13" else baseline,
                ref,
                False,
                f"{ref:.1f}",
            ),
            Bar("this app", model, True, f"{model:.1f}"),
        ],
    )


def forecast_synthetic(root: Path) -> Panel | None:
    art = load(root, "forecast/synthetic.json")
    return None if art is None else _forecast(art, "Forecast error, sample company")


def forecast_real(root: Path) -> Panel | None:
    art = load(root, "forecast/real.json")
    return None if art is None else _forecast(art, "Forecast error, real store data")


def procurement(root: Path) -> Panel | None:
    art = load(root, "optimization/synthetic.json")
    if art is None:
        return None
    case = art["cases"]["base"]
    rows = (
        ("always cheapest", "heuristic_cheapest", False),
        ("always top-ranked", "heuristic_weighted", False),
        ("this app", "milp", True),
    )
    return Panel(
        "Cost of a 4-week purchase plan",
        "lower is better",
        [
            Bar(label, case[key]["objective"], ours, f"{case[key]['objective'] / 1000:,.0f}k")
            for label, key, ours in rows
        ],
    )


def outage(root: Path) -> Panel | None:
    art = load(root, "scenario/synthetic.json")
    if art is None:
        return None
    scenario = next((s for s in art["scenarios"] if s["scenario_type"] == "SUPPLIER_OUTAGE"), None)
    if scenario is None:
        return None
    held, reopt = scenario["disrupted"]["fill_rate"], scenario["response"]["fill_rate"]
    return Panel(
        "A supplier stops delivering",
        "share of demand covered, higher is better",
        [
            Bar("keep the plan", held, False, f"{100 * held:.1f}%"),
            Bar("re-plan", reopt, True, f"{100 * reopt:.1f}%"),
        ],
    )


def retrieval(root: Path) -> Panel | None:
    hashing = load(root, "rag/synthetic-hashing.json")
    dense = load(root, "rag/synthetic-fastembed.json")
    if hashing is None or dense is None:
        return None
    ref, ours = hashing["retrieval"]["hit@1"], dense["retrieval"]["hit@1"]
    return Panel(
        "Finding the right document",
        f"right document first, {dense['retrieval']['questions']} questions",
        [
            Bar("keyword match", ref, False, f"{100 * ref:.0f}%"),
            Bar("this app", ours, True, f"{100 * ours:.0f}%"),
        ],
    )


def scaling(root: Path) -> Panel | None:
    art = load(root, "systems/worker-scaling.json")
    if art is None:
        return None
    by_replicas: dict[int, list[float]] = {}
    for run in art["runs"]:
        if not run.get("disrupted") and run["failed"] == 0 and not run.get("host_suspended"):
            by_replicas.setdefault(int(run["replicas"]), []).append(run["throughput_jobs_per_min"])
    bars = []
    for replicas in sorted(by_replicas):
        runs = sorted(by_replicas[replicas])
        median = runs[len(runs) // 2]
        bars.append(
            Bar(f"{replicas} worker{'s' if replicas > 1 else ''}", median, True, f"{median:.1f}")
        )
    return Panel("More workers, more jobs done", "plan-building jobs per minute", bars)


PANELS: tuple[Callable[[Path], Panel | None], ...] = (
    forecast_synthetic,
    forecast_real,
    procurement,
    outage,
    retrieval,
    scaling,
)


def _panel_svg(panel: Panel, x: int, y: int) -> list[str]:
    out = [
        f'<text class="title" x="{x + 16}" y="{y + 24}">{escape(panel.title)}</text>',
        f'<text class="note" x="{x + 16}" y="{y + 42}">{escape(panel.note)}</text>',
    ]
    top = y + 62
    left = x + 16 + LABEL_W
    span = PANEL_W - 16 - LABEL_W - 64  # room for the value label at the bar tip
    peak = max(bar.value for bar in panel.bars)
    bottom = top + len(panel.bars) * (BAR_H + BAR_GAP) - BAR_GAP
    out.append(f'<line class="axis" x1="{left}" y1="{top - 6}" x2="{left}" y2="{bottom + 6}"/>')
    for i, bar in enumerate(panel.bars):
        by = top + i * (BAR_H + BAR_GAP)
        width = max(2.0, span * bar.value / peak)
        mark = "ours" if bar.ours else "reference"
        # square at the baseline, 4px rounded at the data end
        out.append(
            f'<path class="{mark}" d="M{left},{by} h{width - 4:.1f} a4,4 0 0 1 4,4 '
            f'v{BAR_H - 8} a4,4 0 0 1 -4,4 h{-(width - 4):.1f} z"/>'
        )
        out.append(
            f'<text class="label" x="{left - 8}" y="{by + 14}" text-anchor="end">'
            f"{escape(bar.label)}</text>"
        )
        out.append(
            f'<text class="value" x="{left + width + 6:.1f}" y="{by + 14}">'
            f"{escape(bar.text)}</text>"
        )
    return out


def render(root: Path) -> str:
    panels = [p for p in (make(root) for make in PANELS) if p is not None]
    rows = max(1, -(-len(panels) // COLUMNS))
    height = HEADER_H + rows * PANEL_H
    body = [
        f'<rect class="surface" width="{WIDTH}" height="{height}" rx="8"/>',
        '<text class="title" x="16" y="28">Measured results</text>',
        '<rect class="ours" x="16" y="40" width="12" height="12" rx="2"/>',
        '<text class="note" x="34" y="50">this app</text>',
        '<rect class="reference" x="130" y="40" width="12" height="12" rx="2"/>',
        '<text class="note" x="148" y="50">simple approach</text>',
        '<text class="note" x="944" y="50" text-anchor="end">'
        "sample company unless noted; from ml/experiments</text>",
    ]
    for i, panel in enumerate(panels):
        body += _panel_svg(panel, (i % COLUMNS) * PANEL_W, HEADER_H + (i // COLUMNS) * PANEL_H)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" aria-label="Measured results">\n'
        f"<style>{STYLE}</style>\n" + "\n".join(body) + "\n</svg>\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draw the README results figure.")
    parser.add_argument("--experiments", type=Path, default=DEFAULT_EXPERIMENTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(args.experiments), encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
