from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scm_common.domain import (
    DomainModel,
    FulfillmentLane,
    InventoryPosition,
    PurchaseOrder,
    Region,
    SalesOrder,
    Sku,
    Supplier,
    SupplierContract,
    SupplierOffer,
    Warehouse,
)

from .config import GENERATOR_VERSION, SyntheticConfig
from .world import SyntheticWorld

MANIFEST = "manifest.json"
# file stem -> (SyntheticWorld attribute, model class)
TABLES: dict[str, tuple[str, type[DomainModel]]] = {
    "regions": ("regions", Region),
    "warehouses": ("warehouses", Warehouse),
    "lanes": ("lanes", FulfillmentLane),
    "skus": ("skus", Sku),
    "suppliers": ("suppliers", Supplier),
    "contracts": ("contracts", SupplierContract),
    "offers": ("offers", SupplierOffer),
    "sales_orders": ("sales_orders", SalesOrder),
    "purchase_orders": ("purchase_orders", PurchaseOrder),
    "inventory": ("inventory", InventoryPosition),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_lines(path: Path, rows: Sequence[DomainModel]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")


def write_world(world: SyntheticWorld, directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, Any]] = {}
    for stem, (attribute, _) in TABLES.items():
        rows: Sequence[DomainModel] = getattr(world, attribute)
        path = directory / f"{stem}.jsonl"
        _write_lines(path, rows)
        files[path.name] = {"rows": len(rows), "sha256": _sha256(path)}
    config = world.config.model_dump(mode="json")
    identity = hashlib.sha256(
        json.dumps({"files": files, "config": config}, sort_keys=True).encode()
    ).hexdigest()
    manifest: dict[str, Any] = {
        "dataset_id": f"synthetic-v{GENERATOR_VERSION}-{identity[:12]}",
        "generator_version": GENERATOR_VERSION,
        "as_of": world.as_of.isoformat(),
        "config": config,
        "files": files,
    }
    (directory / MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


def read_manifest(directory: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    return manifest


def read_world(directory: Path) -> SyntheticWorld:
    manifest = read_manifest(directory)
    tables: dict[str, list[Any]] = {}
    for stem, (attribute, model) in TABLES.items():
        path = directory / f"{stem}.jsonl"
        if _sha256(path) != manifest["files"][path.name]["sha256"]:
            raise ValueError(f"{path.name} does not match its manifest checksum")
        with path.open(encoding="utf-8") as handle:
            tables[attribute] = [model.model_validate_json(line) for line in handle if line.strip()]
    config = SyntheticConfig.model_validate(manifest["config"])
    return SyntheticWorld(
        config=config,
        as_of=config.start_date.fromisoformat(manifest["as_of"]),
        **tables,
    )
