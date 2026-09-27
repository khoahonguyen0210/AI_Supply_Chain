from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

import numpy as np

from scm_common.domain import (
    FulfillmentLane,
    InventoryPosition,
    PurchaseOrder,
    PurchaseOrderStatus,
    SalesOrder,
    Sku,
    Supplier,
    SupplierOffer,
    Warehouse,
)

from .config import SyntheticConfig
from .master_data import WarehouseSpec

PURCHASES_PER_SKU_YEAR = 24
RECENT_WEEKS = 8
TARGET_WAREHOUSE_FILL = 0.5


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def generate_purchase_orders(
    cfg: SyntheticConfig,
    rng: np.random.Generator,
    as_of: date,
    skus: list[Sku],
    suppliers: list[Supplier],
    offers: list[SupplierOffer],
    specs: list[WarehouseSpec],
    pending: dict[str, tuple[date, int]] | None = None,
) -> list[PurchaseOrder]:
    reliability = {s.supplier_id: s.reliability for s in suppliers}
    offers_by_sku: dict[str, list[SupplierOffer]] = defaultdict(list)
    for offer in offers:
        offers_by_sku[offer.sku_id].append(offer)

    horizon_days = cfg.n_weeks * 7
    expected = PURCHASES_PER_SKU_YEAR * cfg.n_weeks / 52
    drafts: list[tuple[datetime, Sku, SupplierOffer, str, int]] = []
    for sku in skus:
        for _ in range(int(rng.poisson(expected))):
            offer = offers_by_sku[sku.sku_id][int(rng.integers(0, len(offers_by_sku[sku.sku_id])))]
            created = _midnight(cfg.start_date) + timedelta(
                days=int(rng.integers(0, horizon_days)), hours=int(rng.integers(8, 18))
            )
            warehouse = specs[int(rng.integers(0, len(specs)))].warehouse_id
            quantity = offer.moq * int(rng.integers(1, 5))
            drafts.append((created, sku, offer, warehouse, quantity))
    drafts.sort(key=lambda d: (d[0], d[1].sku_id, d[2].offer_id))

    orders = []
    for n, (created, sku, offer, warehouse, quantity) in enumerate(drafts):
        on_time = rng.random() < reliability[offer.supplier_id]
        delay = 0 if on_time else int(rng.integers(1, 11))
        short = (not on_time) and rng.random() < 0.5
        delivered_quantity = int(quantity * rng.uniform(0.7, 0.95)) if short else quantity
        expected_delivery = created.date() + timedelta(days=offer.lead_time_days)
        delivered_at = expected_delivery + timedelta(days=delay)
        is_open = delivered_at > as_of
        if is_open and pending is not None:
            pending[f"PO-{n + 1:05d}"] = (delivered_at, delivered_quantity)
        orders.append(
            PurchaseOrder(
                po_id=f"PO-{n + 1:05d}",
                supplier_id=offer.supplier_id,
                sku_id=sku.sku_id,
                warehouse_id=warehouse,
                quantity=quantity,
                unit_price=round(offer.unit_price * float(rng.uniform(0.97, 1.03)), 2),
                status=PurchaseOrderStatus.PLACED if is_open else PurchaseOrderStatus.DELIVERED,
                created_at=created,
                expected_delivery=expected_delivery,
                delivered_at=None if is_open else delivered_at,
                delivered_quantity=None if is_open else delivered_quantity,
            )
        )
    return orders


def generate_inventory_and_warehouses(
    rng: np.random.Generator,
    as_of: date,
    skus: list[Sku],
    specs: list[WarehouseSpec],
    lanes: list[FulfillmentLane],
    sales_orders: list[SalesOrder],
    purchase_orders: list[PurchaseOrder],
) -> tuple[list[InventoryPosition], list[Warehouse]]:
    home: dict[str, str] = {}
    for region_id in {lane.region_id for lane in lanes}:
        best = min(
            (ln for ln in lanes if ln.region_id == region_id), key=lambda ln: ln.cost_per_unit
        )
        home[region_id] = best.warehouse_id

    cutoff = _midnight(as_of) - timedelta(weeks=RECENT_WEEKS)
    recent: dict[tuple[str, str], float] = defaultdict(float)
    for order in sales_orders:
        if order.ordered_at >= cutoff:
            recent[(order.sku_id, home[order.region_id])] += order.quantity / RECENT_WEEKS

    incoming: dict[tuple[str, str], int] = defaultdict(int)
    for po in purchase_orders:
        if po.status == PurchaseOrderStatus.PLACED:
            incoming[(po.sku_id, po.warehouse_id)] += po.quantity

    as_of_ts = _midnight(as_of)
    positions: list[InventoryPosition] = []
    volume: dict[str, float] = defaultdict(float)
    for spec in specs:
        for sku in skus:
            weekly = recent[(sku.sku_id, spec.warehouse_id)]
            on_hand = int(round(weekly * float(rng.uniform(1.5, 4.0))))
            inbound = incoming[(sku.sku_id, spec.warehouse_id)]
            positions.append(
                InventoryPosition(
                    sku_id=sku.sku_id,
                    warehouse_id=spec.warehouse_id,
                    as_of=as_of_ts,
                    on_hand=on_hand,
                    incoming=inbound,
                    safety_stock=int(round(weekly)),
                )
            )
            volume[spec.warehouse_id] += (on_hand + inbound) * sku.unit_volume

    warehouses = [
        Warehouse(
            warehouse_id=spec.warehouse_id,
            name=spec.name,
            region_id=spec.region_id,
            capacity_units=float(
                max(100, math.ceil(volume[spec.warehouse_id] / TARGET_WAREHOUSE_FILL / 100) * 100)
            ),
            holding_cost_per_unit_week=spec.holding_cost_per_unit_week,
        )
        for spec in specs
    ]
    return positions, warehouses
