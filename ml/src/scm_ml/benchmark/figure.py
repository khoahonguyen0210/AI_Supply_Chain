"""CLI: draw the README results card (SVG) from saved artifacts.

uv run python -m scm_ml.benchmark.figure
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from pathlib import Path

from .report import DEFAULT_EXPERIMENTS, load

DEFAULT_OUT = Path("docs/images/results.svg")

WIDTH = 960
TILE_W = 456
TILE_H = 132
GAP = 16
TOP = 70

STYLE = """
.surface { fill: #fcfcfb; }
.tile { fill: #f2f2ef; stroke: #e1e0d9; }
.title { fill: #0b0b0b; font: 600 15px system-ui, -apple-system, 'Segoe UI', sans-serif; }
.note { fill: #52514e; font: 12px system-ui, -apple-system, 'Segoe UI', sans-serif; }
.big { fill: #2a78d6; font: 700 40px system-ui, -apple-system, 'Segoe UI', sans-serif; }
.headline { fill: #0b0b0b; font: 600 15px system-ui, -apple-system, 'Segoe UI', sans-serif; }
.compare { fill: #52514e; font: 13px system-ui, -apple-system, 'Segoe UI', sans-serif; }
@media (prefers-color-scheme: dark) {
  .surface { fill: #1a1a19; }
  .tile { fill: #222220; stroke: #2c2c2a; }
  .title, .headline { fill: #ffffff; }
  .note, .compare { fill: #c3c2b7; }
  .big { fill: #3987e5; }
}
"""


@dataclass(frozen=True)
class Tile:
    big: str  # the headline number, e.g. "11%"
    headline: str  # what it means, in plain words
    compare: str  # what it was compared with


def forecast(root: Path) -> Tile | None:
    art = load(root, "forecast/synthetic.json")
    if art is None:
        return None
    ref = art["baselines"][art["selected_baseline"]]["test"]["overall"]["mae"]
    model = art["model"]["test"]["overall"]["mae"]
    return Tile(
        f"{100 * (1 - model / ref):.0f}%",
        "more accurate sales forecasts",
        f"than a simple 13-week average ({model:.1f} vs {ref:.1f} units off per week)",
    )


def cost(root: Path) -> Tile | None:
    art = load(root, "optimization/synthetic.json")
    if art is None:
        return None
    case = art["cases"]["base"]
    ours, cheapest = case["milp"]["objective"], case["heuristic_cheapest"]["objective"]
    return Tile(
        f"{100 * (1 - ours / cheapest):.0f}%",
        "cheaper purchase plans",
        "than always buying from the cheapest supplier"
        f" ({ours / 1000:,.0f}k vs {cheapest / 1000:,.0f}k)",
    )


def outage(root: Path) -> Tile | None:
    art = load(root, "scenario/synthetic.json")
    if art is None:
        return None
    scenario = next((s for s in art["scenarios"] if s["scenario_type"] == "SUPPLIER_OUTAGE"), None)
    if scenario is None:
        return None
    held, replanned = scenario["disrupted"]["fill_rate"], scenario["response"]["fill_rate"]
    return Tile(
        f"{100 * replanned:.0f}%",
        "of demand still covered when a supplier fails",
        f"after re-planning, vs {100 * held:.0f}% if you keep the old plan",
    )


def documents(root: Path) -> Tile | None:
    dense = load(root, "rag/synthetic-fastembed.json")
    keyword = load(root, "rag/synthetic-hashing.json")
    if dense is None or keyword is None:
        return None
    ours, ref = dense["retrieval"]["hit@1"], keyword["retrieval"]["hit@1"]
    return Tile(
        f"{100 * ours:.0f}%",
        "of policy questions find the right document first",
        f"vs {100 * ref:.0f}% with plain keyword matching",
    )


def assistant(root: Path) -> Tile | None:
    art = load(root, "agent/synthetic-rule-planner-v4-first-run.json")
    if art is None or "holdout-v4" not in art["by_split"]:
        return None
    split = art["by_split"]["holdout-v4"]
    solved = round(split["workflow_success"] * split["cases"])
    return Tile(
        f"{100 * split['workflow_success']:.0f}%",
        "of new, never-seen requests handled correctly",
        f"by the assistant ({solved} of {split['cases']}, scored once before any change)",
    )


def safety(root: Path) -> Tile | None:
    art = load(root, "agent/synthetic-rule-planner.json")
    if art is None:
        return None
    safe = art["dimensions"]["action_safety"]
    grounded = art["dimensions"]["grounded_numbers"]["pass_rate"]
    return Tile(
        f"{100 * safe['pass_rate']:.0f}%",
        "safe: never orders without approval",
        f"in {safe['applicable']} test requests; "
        f"{100 * grounded:.0f}% of answers use only real numbers",
    )


TILES: tuple[Callable[[Path], Tile | None], ...] = (
    forecast,
    cost,
    outage,
    documents,
    assistant,
    safety,
)


def _tile_svg(tile: Tile, x: int, y: int) -> list[str]:
    return [
        f'<rect class="tile" x="{x}" y="{y}" width="{TILE_W}" height="{TILE_H}" rx="12"/>',
        f'<text class="big" x="{x + 22}" y="{y + 56}">{escape(tile.big)}</text>',
        f'<text class="headline" x="{x + 22}" y="{y + 86}">{escape(tile.headline)}</text>',
        f'<text class="compare" x="{x + 22}" y="{y + 110}">{escape(tile.compare)}</text>',
    ]


def render(root: Path) -> str:
    tiles = [t for t in (make(root) for make in TILES) if t is not None]
    rows = max(1, -(-len(tiles) // 2))
    height = TOP + rows * (TILE_H + GAP) + 4
    body = [
        f'<rect class="surface" width="{WIDTH}" height="{height}" rx="12"/>',
        '<text class="title" x="16" y="32">What the app achieved</text>',
        '<text class="note" x="16" y="52">Tested on a made-up sample company; every number comes'
        " from a saved result in ml/experiments.</text>",
    ]
    for i, tile in enumerate(tiles):
        body += _tile_svg(tile, 16 + (i % 2) * (TILE_W + GAP), TOP + (i // 2) * (TILE_H + GAP))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" aria-label="What the app achieved">\n'
        f"<style>{STYLE}</style>\n" + "\n".join(body) + "\n</svg>\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draw the README results card.")
    parser.add_argument("--experiments", type=Path, default=DEFAULT_EXPERIMENTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(args.experiments), encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
