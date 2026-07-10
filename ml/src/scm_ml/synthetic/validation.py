from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from scm_common.domain import ContractStatus

from .world import SyntheticWorld

ORDER_COUNT_TOLERANCE = 0.05


def _duplicates(ids: Iterable[str]) -> list[str]:
    return [i for i, n in Counter(ids).items() if n > 1]


def validate_world(world: SyntheticWorld) -> list[str]:
    issues: list[str] = []
    cfg = world.config

    for name, ids in {
        "region": [r.region_id for r in world.regions],
        "warehouse": [w.warehouse_id for w in world.warehouses],
        "sku": [s.sku_id for s in world.skus],
        "supplier": [s.supplier_id for s in world.suppliers],
        "offer": [o.offer_id for o in world.offers],
        "sales order": [o.order_id for o in world.sales_orders],
        "purchase order": [p.po_id for p in world.purchase_orders],
    }.items():
        issues += [f"duplicate {name} id {d}" for d in _duplicates(ids)]

    region_ids = {r.region_id for r in world.regions}
    warehouse_ids = {w.warehouse_id for w in world.warehouses}
    sku_by_id = {s.sku_id: s for s in world.skus}
    supplier_by_id = {s.supplier_id: s for s in world.suppliers}

    for check, expected, actual in (
        ("regions", cfg.n_regions, len(world.regions)),
        ("warehouses", cfg.n_warehouses, len(world.warehouses)),
        ("skus", cfg.n_skus, len(world.skus)),
        ("suppliers", cfg.n_suppliers, len(world.suppliers)),
    ):
        if expected != actual:
            issues.append(f"expected {expected} {check}, found {actual}")

    target = cfg.target_sales_orders
    if abs(len(world.sales_orders) - target) > target * ORDER_COUNT_TOLERANCE:
        issues.append(f"sales order count {len(world.sales_orders)} too far from target {target}")

    for w in world.warehouses:
        if w.region_id not in region_ids:
            issues.append(f"warehouse {w.warehouse_id} references unknown region {w.region_id}")
    for s in world.suppliers:
        if s.region_id not in region_ids:
            issues.append(f"supplier {s.supplier_id} references unknown region {s.region_id}")
    for lane in world.lanes:
        if lane.warehouse_id not in warehouse_ids or lane.region_id not in region_ids:
            issues.append(f"lane {lane.warehouse_id}->{lane.region_id} has unknown endpoint")
    if len(world.lanes) != len(warehouse_ids) * len(region_ids):
        issues.append("every warehouse must have a lane to every region")

    for c in world.contracts:
        if c.supplier_id not in supplier_by_id:
            issues.append(f"contract {c.contract_id} references unknown supplier {c.supplier_id}")
    if {c.supplier_id for c in world.contracts} != set(supplier_by_id):
        issues.append("every supplier must have exactly one contract")

    active = {c.supplier_id for c in world.contracts if c.status == ContractStatus.ACTIVE}
    eligible_offers: Counter[str] = Counter()
    for o in world.offers:
        supplier, sku = supplier_by_id.get(o.supplier_id), sku_by_id.get(o.sku_id)
        if supplier is None or sku is None:
            issues.append(f"offer {o.offer_id} references unknown supplier/sku")
            continue
        if not set(sku.required_certifications) <= set(supplier.certifications):
            issues.append(f"offer {o.offer_id}: supplier lacks required certification")
        if o.capacity_per_week < o.moq:
            issues.append(f"offer {o.offer_id}: capacity below MOQ")
        if set(o.shipping_cost_per_unit) != warehouse_ids:
            issues.append(f"offer {o.offer_id}: shipping cost must cover every warehouse")
        if o.supplier_id in active:
            eligible_offers[o.sku_id] += 1
    for sku_id in sku_by_id:
        if eligible_offers[sku_id] < cfg.min_offers_per_sku:
            issues.append(f"sku {sku_id} has fewer than {cfg.min_offers_per_sku} active offers")

    start = datetime(cfg.start_date.year, cfg.start_date.month, cfg.start_date.day, tzinfo=UTC)
    end = start + timedelta(weeks=cfg.n_weeks)
    for so in world.sales_orders:
        if so.sku_id not in sku_by_id or so.region_id not in region_ids:
            issues.append(f"sales order {so.order_id} has unknown sku/region")
        if not start <= so.ordered_at < end:
            issues.append(f"sales order {so.order_id} outside the history window")

    offer_pairs = {(o.supplier_id, o.sku_id) for o in world.offers}
    for po in world.purchase_orders:
        if (po.supplier_id, po.sku_id) not in offer_pairs:
            issues.append(f"purchase order {po.po_id} has no matching supplier offer")
        if po.warehouse_id not in warehouse_ids:
            issues.append(f"purchase order {po.po_id} references unknown warehouse")

    if len(world.inventory) != len(world.skus) * len(world.warehouses):
        issues.append("inventory must cover every sku at every warehouse")
    used: defaultdict[str, float] = defaultdict(float)
    for inv in world.inventory:
        if inv.sku_id not in sku_by_id or inv.warehouse_id not in warehouse_ids:
            issues.append(f"inventory {inv.sku_id}@{inv.warehouse_id} has unknown sku/warehouse")
            continue
        used[inv.warehouse_id] += (inv.on_hand + inv.incoming) * sku_by_id[inv.sku_id].unit_volume
    for w in world.warehouses:
        if used[w.warehouse_id] > w.capacity_units:
            issues.append(f"warehouse {w.warehouse_id} stocked above capacity")
    return issues
