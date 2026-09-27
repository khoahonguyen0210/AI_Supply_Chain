from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from .config import SyntheticConfig
from .demand import DemandProcess, generate_sales_orders
from .master_data import (
    build_contracts,
    build_lanes,
    build_offers,
    build_regions,
    build_skus,
    build_suppliers,
    build_warehouse_specs,
)
from .operations import generate_inventory_and_warehouses, generate_purchase_orders
from .world import SyntheticWorld

STAGES = ("master", "demand", "operations")
OUTCOME_STREAM = len(STAGES)
"""Index of the random stream reserved for what happens after ``as_of`` (the feedback loop)."""


@dataclass(frozen=True)
class HiddenFuture:
    demand: DemandProcess
    pending_deliveries: dict[str, tuple[date, int]]
    """Open purchase order id -> the delivery date and quantity already drawn for it."""


def generate_world(cfg: SyntheticConfig | None = None) -> SyntheticWorld:
    return _generate(cfg or SyntheticConfig())[0]


def generate_world_with_future(
    cfg: SyntheticConfig | None = None,
) -> tuple[SyntheticWorld, HiddenFuture]:
    return _generate(cfg or SyntheticConfig())


def outcome_rng(cfg: SyntheticConfig) -> np.random.Generator:
    """Random stream for simulated outcomes, independent of the world streams."""
    return np.random.default_rng(
        np.random.SeedSequence(cfg.seed).spawn(OUTCOME_STREAM + 1)[OUTCOME_STREAM]
    )


def _generate(cfg: SyntheticConfig) -> tuple[SyntheticWorld, HiddenFuture]:
    master_rng, demand_rng, ops_rng = (
        np.random.default_rng(seq) for seq in np.random.SeedSequence(cfg.seed).spawn(len(STAGES))
    )
    as_of = cfg.start_date + timedelta(weeks=cfg.n_weeks)

    regions = build_regions(cfg)
    specs = build_warehouse_specs(cfg, master_rng, regions)
    lanes = build_lanes(master_rng, specs, regions)
    skus = build_skus(cfg, master_rng)
    suppliers, price_factor = build_suppliers(cfg, master_rng, regions)
    contracts = build_contracts(suppliers, as_of)

    sales_orders, weekly_units, process = generate_sales_orders(cfg, demand_rng, skus, regions)

    offers = build_offers(
        cfg,
        master_rng,
        as_of,
        skus,
        suppliers,
        price_factor,
        contracts,
        specs,
        regions,
        weekly_units,
    )
    pending: dict[str, tuple[date, int]] = {}
    purchase_orders = generate_purchase_orders(
        cfg, ops_rng, as_of, skus, suppliers, offers, specs, pending
    )
    inventory, warehouses = generate_inventory_and_warehouses(
        ops_rng, as_of, skus, specs, lanes, sales_orders, purchase_orders
    )
    world = SyntheticWorld(
        config=cfg,
        as_of=as_of,
        regions=regions,
        warehouses=warehouses,
        lanes=lanes,
        skus=skus,
        suppliers=suppliers,
        contracts=contracts,
        offers=offers,
        sales_orders=sales_orders,
        purchase_orders=purchase_orders,
        inventory=inventory,
    )
    return world, HiddenFuture(demand=process, pending_deliveries=pending)
