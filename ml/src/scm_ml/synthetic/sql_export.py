"""Writes the synthetic world as an idempotent PostgreSQL seed script."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from scm_ml.forecast.panel import panel_from_world
from scm_ml.knowledge.corpus import build_corpus

from .config import SyntheticConfig
from .generator import generate_world
from .world import SyntheticWorld

DEFAULT_OUT = Path("data/seed/synthetic-seed.sql")
DEMAND_SOURCE = "synthetic"
BATCH_ROWS = 400


def literal(value: Any) -> str:
    """A SQL literal for a Python value."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, datetime):
        return f"'{value.isoformat()}'"
    if isinstance(value, date):
        return f"'{value.isoformat()}'"
    if isinstance(value, tuple | list):
        return "ARRAY[" + ", ".join(literal(v) for v in value) + "]::text[]"
    return "'" + str(value).replace("'", "''") + "'"


def insert(table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    """Multi-row INSERT statements (``ON CONFLICT DO NOTHING``), BATCH_ROWS rows at a time."""
    statements: list[str] = []
    batch: list[str] = []
    header = f"INSERT INTO {table} ({', '.join(columns)}) VALUES\n"
    for row in rows:
        batch.append("  (" + ", ".join(literal(v) for v in row) + ")")
        if len(batch) == BATCH_ROWS:
            statements.append(header + ",\n".join(batch) + "\nON CONFLICT DO NOTHING;")
            batch = []
    if batch:
        statements.append(header + ",\n".join(batch) + "\nON CONFLICT DO NOTHING;")
    return statements


def seed_statements(world: SyntheticWorld) -> list[str]:
    panel = panel_from_world(world)
    observed_at = datetime.combine(
        panel.weeks[-1] + timedelta(days=7), datetime.min.time()
    ).isoformat()
    statements: list[str] = []
    statements += insert(
        "region", ["region_id", "name"], [(r.region_id, r.name) for r in world.regions]
    )
    statements += insert(
        "sku",
        ["sku_id", "name", "category", "unit_price", "unit_volume", "required_certifications"],
        [
            (s.sku_id, s.name, s.category, s.unit_price, s.unit_volume, s.required_certifications)
            for s in world.skus
        ],
    )
    statements += insert(
        "supplier",
        ["supplier_id", "name", "region_id", "reliability", "quality_score", "certifications"],
        [
            (s.supplier_id, s.name, s.region_id, s.reliability, s.quality_score, s.certifications)
            for s in world.suppliers
        ],
    )
    statements += insert(
        "warehouse",
        ["warehouse_id", "name", "region_id", "capacity_units", "holding_cost_per_unit_week"],
        [
            (w.warehouse_id, w.name, w.region_id, w.capacity_units, w.holding_cost_per_unit_week)
            for w in world.warehouses
        ],
    )
    statements += insert(
        "fulfillment_lane",
        ["warehouse_id", "region_id", "cost_per_unit", "transit_days"],
        [(ln.warehouse_id, ln.region_id, ln.cost_per_unit, ln.transit_days) for ln in world.lanes],
    )
    statements += insert(
        "supplier_contract",
        [
            "contract_id",
            "supplier_id",
            "status",
            "effective_from",
            "effective_to",
            "payment_terms_days",
            "max_order_value",
        ],
        [
            (
                c.contract_id,
                c.supplier_id,
                c.status.value,
                c.effective_from,
                c.effective_to,
                c.payment_terms_days,
                c.max_order_value,
            )
            for c in world.contracts
        ],
    )
    statements += insert(
        "supplier_offer",
        [
            "offer_id",
            "supplier_id",
            "sku_id",
            "unit_price",
            "moq",
            "capacity_per_week",
            "lead_time_days",
            "valid_from",
            "valid_to",
        ],
        [
            (
                o.offer_id,
                o.supplier_id,
                o.sku_id,
                o.unit_price,
                o.moq,
                o.capacity_per_week,
                o.lead_time_days,
                o.valid_from,
                o.valid_to,
            )
            for o in world.offers
        ],
    )
    statements += insert(
        "supplier_offer_shipping",
        ["offer_id", "warehouse_id", "cost_per_unit"],
        [
            (o.offer_id, warehouse_id, cost)
            for o in world.offers
            for warehouse_id, cost in sorted(o.shipping_cost_per_unit.items())
        ],
    )
    statements += insert(
        "inventory_position",
        ["sku_id", "warehouse_id", "as_of", "on_hand", "incoming", "safety_stock"],
        [
            (p.sku_id, p.warehouse_id, p.as_of, p.on_hand, p.incoming, p.safety_stock)
            for p in world.inventory
        ],
    )
    statements += insert(
        "purchase_order",
        [
            "po_id",
            "supplier_id",
            "sku_id",
            "warehouse_id",
            "quantity",
            "unit_price",
            "status",
            "created_at",
            "expected_delivery",
            "delivered_at",
            "delivered_quantity",
        ],
        [
            (
                po.po_id,
                po.supplier_id,
                po.sku_id,
                po.warehouse_id,
                po.quantity,
                po.unit_price,
                po.status.value,
                po.created_at,
                po.expected_delivery,
                po.delivered_at,
                po.delivered_quantity,
            )
            for po in world.purchase_orders
        ],
    )
    statements += insert(
        "demand_observation",
        ["source", "sku_id", "region_id", "period_start", "quantity", "observed_at"],
        [
            (DEMAND_SOURCE, sku_id, region_id, week, float(panel.values[i][j]), observed_at)
            for i, (sku_id, region_id) in enumerate(panel.series)
            for j, week in enumerate(panel.weeks)
        ],
    )
    statements += insert(
        "knowledge_document",
        [
            "document_id",
            "version",
            "doc_type",
            "title",
            "effective_date",
            "expiry_date",
            "supplier_id",
            "allowed_roles",
            "content",
            "content_sha256",
        ],
        [
            (
                d.document_id,
                d.version,
                d.doc_type.value,
                d.title,
                d.effective_date,
                d.expiry_date,
                d.supplier_id,
                d.allowed_roles,
                d.content,
                _sha256(d.content),
            )
            for d in build_corpus(world).documents
        ],
    )
    return statements


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render(world: SyntheticWorld) -> str:
    header = (
        "-- Generated by `python -m scm_ml.synthetic.sql_export`; do not edit.\n"
        f"-- Synthetic world seed {world.config.seed}, as of {world.as_of.isoformat()}.\n"
        "BEGIN;\n"
    )
    return header + "\n".join(seed_statements(world)) + "\nCOMMIT;\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the synthetic world as a PostgreSQL seed.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=SyntheticConfig().seed)
    parser.add_argument(
        "--database-url",
        default=None,
        help="apply the seed to this (migrated) PostgreSQL database instead of writing a file",
    )
    args = parser.parse_args(argv)
    world = generate_world(SyntheticConfig(seed=args.seed))
    if args.database_url:
        import psycopg

        with psycopg.connect(args.database_url, autocommit=True) as connection:
            connection.execute(render(world).encode())
        print("seed applied")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(world), encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
