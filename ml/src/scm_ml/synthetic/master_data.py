"""Master data: regions, SKUs, suppliers, offers, contracts and fulfillment lanes."""

from __future__ import annotations

from datetime import date, timedelta
from typing import NamedTuple

import numpy as np

from scm_common.domain import (
    ContractStatus,
    FulfillmentLane,
    Region,
    Sku,
    Supplier,
    SupplierContract,
    SupplierOffer,
)

from .config import SyntheticConfig

REGION_NAMES = ("North", "South", "East", "West", "Central")
CATEGORIES: tuple[tuple[str, str | None], ...] = (
    ("electronics", "RoHS"),
    ("apparel", None),
    ("home", None),
    ("food", "HACCP"),
    ("industrial", "ISO9001"),
)
CERTIFICATIONS = ("RoHS", "HACCP", "ISO9001")
COST_TO_PRICE_RATIO = 0.55
MOQ_CHOICES = (10, 25, 50, 100)
OFFER_PROBABILITY = 0.6
RELIABLE_CERT_HOLDERS = 7


class WarehouseSpec(NamedTuple):
    warehouse_id: str
    name: str
    region_id: str
    region_index: int
    holding_cost_per_unit_week: float


def build_regions(cfg: SyntheticConfig) -> list[Region]:
    return [Region(region_id=f"R{i + 1}", name=REGION_NAMES[i]) for i in range(cfg.n_regions)]


def build_warehouse_specs(
    cfg: SyntheticConfig, rng: np.random.Generator, regions: list[Region]
) -> list[WarehouseSpec]:
    specs = []
    for w in range(cfg.n_warehouses):
        region_index = w * cfg.n_regions // cfg.n_warehouses
        specs.append(
            WarehouseSpec(
                warehouse_id=f"WH-{w + 1}",
                name=f"{regions[region_index].name} Hub",
                region_id=regions[region_index].region_id,
                region_index=region_index,
                holding_cost_per_unit_week=round(float(rng.uniform(0.03, 0.08)), 3),
            )
        )
    return specs


def build_lanes(
    rng: np.random.Generator, specs: list[WarehouseSpec], regions: list[Region]
) -> list[FulfillmentLane]:
    lanes = []
    for spec in specs:
        for r, region in enumerate(regions):
            distance = abs(spec.region_index - r)
            lanes.append(
                FulfillmentLane(
                    warehouse_id=spec.warehouse_id,
                    region_id=region.region_id,
                    cost_per_unit=round(0.8 + 0.6 * distance + float(rng.uniform(0, 0.2)), 3),
                    transit_days=1 + distance,
                )
            )
    return lanes


def build_skus(cfg: SyntheticConfig, rng: np.random.Generator) -> list[Sku]:
    skus = []
    for i in range(cfg.n_skus):
        category, certification = CATEGORIES[i % len(CATEGORIES)]
        price = float(np.clip(rng.lognormal(np.log(40), 0.7), 5, 400))
        volume = float(np.clip(rng.lognormal(np.log(0.4), 0.6), 0.05, 2.0))
        skus.append(
            Sku(
                sku_id=f"SKU-{i + 1:03d}",
                name=f"{category.title()} item {i + 1:02d}",
                category=category,
                unit_price=round(price, 2),
                unit_volume=round(volume, 3),
                required_certifications=(certification,) if certification else (),
            )
        )
    return skus


def build_suppliers(
    cfg: SyntheticConfig, rng: np.random.Generator, regions: list[Region]
) -> tuple[list[Supplier], dict[str, float]]:
    """Cheaper suppliers are slower and less reliable, which creates real trade-offs."""
    n = cfg.n_suppliers
    price_factor = np.linspace(0.85, 1.15, n)
    rng.shuffle(price_factor)
    holders = {
        cert: set(rng.choice(n, size=min(RELIABLE_CERT_HOLDERS, n), replace=False).tolist())
        for cert in CERTIFICATIONS
    }
    suppliers = []
    factors: dict[str, float] = {}
    for i in range(n):
        position = (float(price_factor[i]) - 0.85) / 0.30  # 0 = cheapest, 1 = priciest
        supplier_id = f"SUP-{i + 1:03d}"
        factors[supplier_id] = float(price_factor[i])
        suppliers.append(
            Supplier(
                supplier_id=supplier_id,
                name=f"Supplier {chr(ord('A') + i)}",
                region_id=regions[int(rng.integers(0, len(regions)))].region_id,
                reliability=round(
                    float(np.clip(0.82 + 0.16 * position + rng.normal(0, 0.02), 0.75, 0.99)), 3
                ),
                quality_score=round(
                    float(np.clip(0.72 + 0.25 * position + rng.normal(0, 0.03), 0.6, 0.99)), 3
                ),
                certifications=tuple(c for c in CERTIFICATIONS if i in holders[c]),
            )
        )
    return suppliers, factors


def build_contracts(suppliers: list[Supplier], as_of: date) -> list[SupplierContract]:
    """All contracts are active except the last two suppliers (expired, suspended)."""
    contracts = []
    for i, supplier in enumerate(suppliers):
        status = ContractStatus.ACTIVE
        effective_to = as_of + timedelta(days=365)
        if i == len(suppliers) - 2:
            status, effective_to = ContractStatus.EXPIRED, as_of - timedelta(days=30)
        elif i == len(suppliers) - 1:
            status = ContractStatus.SUSPENDED
        contracts.append(
            SupplierContract(
                contract_id=f"CTR-{i + 1:03d}",
                supplier_id=supplier.supplier_id,
                status=status,
                effective_from=as_of - timedelta(days=730),
                effective_to=effective_to,
                payment_terms_days=(30, 45, 60)[i % 3],
                max_order_value=None if i % 2 else 250_000.0,
            )
        )
    return contracts


def build_offers(
    cfg: SyntheticConfig,
    rng: np.random.Generator,
    as_of: date,
    skus: list[Sku],
    suppliers: list[Supplier],
    price_factor: dict[str, float],
    contracts: list[SupplierContract],
    specs: list[WarehouseSpec],
    regions: list[Region],
    weekly_units: dict[str, float],
) -> list[SupplierOffer]:
    active = {c.supplier_id for c in contracts if c.status == ContractStatus.ACTIVE}
    region_index = {r.region_id: i for i, r in enumerate(regions)}
    offers: list[SupplierOffer] = []
    for sku in skus:
        eligible = [
            s for s in suppliers if set(sku.required_certifications) <= set(s.certifications)
        ]
        chosen = [s for s in eligible if rng.random() < OFFER_PROBABILITY]
        active_chosen = [s for s in chosen if s.supplier_id in active]
        pool = [s for s in eligible if s.supplier_id in active and s not in chosen]
        while len(active_chosen) < cfg.min_offers_per_sku and pool:
            extra = pool.pop(int(rng.integers(0, len(pool))))
            chosen.append(extra)
            active_chosen.append(extra)
        for supplier in chosen:
            factor = price_factor[supplier.supplier_id]
            position = (factor - 0.85) / 0.30
            moq = int(rng.choice(MOQ_CHOICES))
            capacity = max(moq, int(np.ceil(weekly_units[sku.sku_id] * rng.uniform(0.35, 0.9))))
            lead = int(np.clip(round(28 - 16 * position + rng.normal(0, 2)), 3, 45))
            shipping = {
                spec.warehouse_id: round(
                    (0.3 + 0.25 * abs(region_index[supplier.region_id] - spec.region_index))
                    * (0.5 + sku.unit_volume),
                    3,
                )
                for spec in specs
            }
            offers.append(
                SupplierOffer(
                    offer_id=f"OFR-{len(offers) + 1:04d}",
                    supplier_id=supplier.supplier_id,
                    sku_id=sku.sku_id,
                    unit_price=round(
                        sku.unit_price
                        * COST_TO_PRICE_RATIO
                        * factor
                        * float(rng.uniform(0.95, 1.05)),
                        2,
                    ),
                    moq=moq,
                    capacity_per_week=capacity,
                    lead_time_days=lead,
                    shipping_cost_per_unit=shipping,
                    valid_from=as_of - timedelta(days=180),
                    valid_to=as_of + timedelta(days=365),
                )
            )
    return offers
