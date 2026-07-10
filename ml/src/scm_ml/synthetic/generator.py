"""Deterministic generation of the synthetic SCM company."""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from .config import SyntheticConfig
from .demand import generate_sales_orders
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


def generate_world(cfg: SyntheticConfig | None = None) -> SyntheticWorld:
    """Same config (including seed) always yields an identical world."""
    cfg = cfg or SyntheticConfig()
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

    sales_orders, weekly_units = generate_sales_orders(cfg, demand_rng, skus, regions)

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
    purchase_orders = generate_purchase_orders(cfg, ops_rng, as_of, skus, suppliers, offers, specs)
    inventory, warehouses = generate_inventory_and_warehouses(
        ops_rng, as_of, skus, specs, lanes, sales_orders, purchase_orders
    )
    return SyntheticWorld(
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
