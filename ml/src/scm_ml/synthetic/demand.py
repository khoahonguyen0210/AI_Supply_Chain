from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import numpy as np
from numpy.typing import NDArray

from scm_common.domain import Region, SalesOrder, Sku

from .config import SyntheticConfig

QUANTITY_SIGMA = 0.6
SEASON_PERIOD_WEEKS = 52

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class DemandProcess:
    n_weeks: int  # length of the generated history
    sku_weight: FloatArray  # (skus,)
    region_weight: FloatArray  # (regions,)
    amplitude: FloatArray  # (skus,) seasonal amplitude of the SKU's category
    phase: FloatArray  # (skus,)
    growth: FloatArray  # (skus,) trend over the history length
    promo: FloatArray  # (skus, n_weeks) promotional lift inside the history
    median_qty: NDArray[np.int64]  # (skus,) median units per order line
    scale: float = 1.0  # expected order lines per unit of unscaled rate

    def unscaled_rate(self, weeks: NDArray[np.int64]) -> FloatArray:
        season = 1 + self.amplitude[:, None] * np.sin(
            2 * np.pi * (weeks[None, :] + self.phase[:, None]) / SEASON_PERIOD_WEEKS
        )
        trend = 1 + self.growth[:, None] * weeks[None, :] / self.n_weeks
        inside = weeks < self.n_weeks
        promo = np.ones((len(self.sku_weight), len(weeks)))
        promo[:, inside] = self.promo[:, weeks[inside]]
        rate: FloatArray = (self.sku_weight[:, None] * season * trend * promo)[
            :, None, :
        ] * self.region_weight[None, :, None]
        return rate

    def rate(self, weeks: NDArray[np.int64]) -> FloatArray:
        scaled: FloatArray = self.unscaled_rate(weeks) * self.scale
        return scaled


def draw_demand_process(
    cfg: SyntheticConfig, rng: np.random.Generator, skus: list[Sku], regions: list[Region]
) -> DemandProcess:
    """Consumes `rng` exactly as the original generator did."""
    n_s, n_r, n_t = len(skus), len(regions), cfg.n_weeks

    sku_weight = np.arange(1, n_s + 1, dtype=np.float64) ** -0.7
    rng.shuffle(sku_weight)
    sku_weight /= sku_weight.sum()
    region_weight = rng.dirichlet(np.full(n_r, 4.0))

    categories = sorted({s.category for s in skus})
    cat_index = np.array([categories.index(s.category) for s in skus])
    amplitude = rng.uniform(0.15, 0.40, size=len(categories))[cat_index]
    phase = rng.uniform(0, SEASON_PERIOD_WEEKS, size=len(categories))[cat_index]
    growth = rng.uniform(-0.2, 0.5, size=n_s)
    promo = np.ones((n_s, n_t))
    for s in range(n_s):
        promo[s, rng.choice(n_t, size=2, replace=False)] = 1.8
    median_qty = rng.integers(8, 61, size=n_s)

    process = DemandProcess(
        n_weeks=n_t,
        sku_weight=sku_weight,
        region_weight=region_weight,
        amplitude=amplitude,
        phase=phase,
        growth=growth,
        promo=promo,
        median_qty=median_qty,
    )
    history_total = float(process.unscaled_rate(np.arange(n_t)).sum())
    return replace(process, scale=cfg.target_sales_orders / history_total)


def generate_sales_orders(
    cfg: SyntheticConfig,
    rng: np.random.Generator,
    skus: list[Sku],
    regions: list[Region],
) -> tuple[list[SalesOrder], dict[str, float], DemandProcess]:
    n_t = cfg.n_weeks
    process = draw_demand_process(cfg, rng, skus, regions)
    rate = process.rate(np.arange(n_t))  # expected order lines per (sku, region, week)
    median_qty = process.median_qty

    mean_qty = np.exp(np.log(median_qty) + QUANTITY_SIGMA**2 / 2) + 0.5  # ceil adds ~0.5
    weekly_units = rate.sum(axis=(1, 2)) * mean_qty / n_t

    counts = rng.poisson(rate)
    cells = np.argwhere(counts > 0)
    reps = counts[cells[:, 0], cells[:, 1], cells[:, 2]]
    s_idx = np.repeat(cells[:, 0], reps)
    r_idx = np.repeat(cells[:, 1], reps)
    t_idx = np.repeat(cells[:, 2], reps)
    n_lines = len(s_idx)
    seconds = (
        t_idx.astype(np.int64) * 7 * 86_400
        + rng.integers(0, 7, size=n_lines) * 86_400
        + rng.integers(0, 86_400, size=n_lines)
    )
    quantity = np.maximum(
        1, np.ceil(rng.lognormal(np.log(median_qty[s_idx]), QUANTITY_SIGMA, n_lines))
    )

    order = np.lexsort((r_idx, s_idx, seconds))
    origin = datetime(cfg.start_date.year, cfg.start_date.month, cfg.start_date.day, tzinfo=UTC)
    orders = [
        SalesOrder(
            order_id=f"SO-{n + 1:06d}",
            sku_id=skus[int(s_idx[i])].sku_id,
            region_id=regions[int(r_idx[i])].region_id,
            ordered_at=origin + timedelta(seconds=int(seconds[i])),
            quantity=int(quantity[i]),
        )
        for n, i in enumerate(order)
    ]
    return orders, {sku.sku_id: float(weekly_units[i]) for i, sku in enumerate(skus)}, process


def continue_demand(
    process: DemandProcess, rng: np.random.Generator, weeks: NDArray[np.int64]
) -> NDArray[np.int64]:
    counts = rng.poisson(process.rate(weeks))
    units = np.zeros(counts.shape, dtype=np.int64)
    cells = np.argwhere(counts > 0)
    reps = counts[cells[:, 0], cells[:, 1], cells[:, 2]]
    s_idx = np.repeat(cells[:, 0], reps)
    quantity = np.maximum(
        1, np.ceil(rng.lognormal(np.log(process.median_qty[s_idx]), QUANTITY_SIGMA, len(s_idx)))
    ).astype(np.int64)
    line_cell = np.repeat(np.arange(len(cells)), reps)
    per_cell = np.bincount(line_cell, weights=quantity, minlength=len(cells)).astype(np.int64)
    units[cells[:, 0], cells[:, 1], cells[:, 2]] = per_cell
    return units
