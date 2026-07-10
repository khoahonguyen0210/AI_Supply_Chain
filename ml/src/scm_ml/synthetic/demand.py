"""Customer demand: seasonal, trending, promotional compound-Poisson order lines."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from scm_common.domain import Region, SalesOrder, Sku

from .config import SyntheticConfig

QUANTITY_SIGMA = 0.6
SEASON_PERIOD_WEEKS = 52


def generate_sales_orders(
    cfg: SyntheticConfig,
    rng: np.random.Generator,
    skus: list[Sku],
    regions: list[Region],
) -> tuple[list[SalesOrder], dict[str, float]]:
    """Return order lines plus the expected weekly unit demand per SKU (all regions)."""
    n_s, n_r, n_t = len(skus), len(regions), cfg.n_weeks
    weeks = np.arange(n_t)

    sku_weight = np.arange(1, n_s + 1, dtype=np.float64) ** -0.7
    rng.shuffle(sku_weight)
    sku_weight /= sku_weight.sum()
    region_weight = rng.dirichlet(np.full(n_r, 4.0))

    categories = sorted({s.category for s in skus})
    cat_index = np.array([categories.index(s.category) for s in skus])
    amplitude = rng.uniform(0.15, 0.40, size=len(categories))[cat_index]
    phase = rng.uniform(0, SEASON_PERIOD_WEEKS, size=len(categories))[cat_index]
    season = 1 + amplitude[:, None] * np.sin(
        2 * np.pi * (weeks[None, :] + phase[:, None]) / SEASON_PERIOD_WEEKS
    )
    growth = rng.uniform(-0.2, 0.5, size=n_s)
    trend = 1 + growth[:, None] * weeks[None, :] / n_t
    promo = np.ones((n_s, n_t))
    for s in range(n_s):
        promo[s, rng.choice(n_t, size=2, replace=False)] = 1.8

    rate = (sku_weight[:, None] * season * trend * promo)[:, None, :] * region_weight[None, :, None]
    rate *= cfg.target_sales_orders / rate.sum()  # expected order lines per (sku, region, week)

    median_qty = rng.integers(8, 61, size=n_s)
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
    return orders, {sku.sku_id: float(weekly_units[i]) for i, sku in enumerate(skus)}
