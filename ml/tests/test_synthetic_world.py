from dataclasses import replace
from pathlib import Path

import pytest

from scm_common.domain import ContractStatus
from scm_ml.synthetic import (
    SyntheticConfig,
    SyntheticWorld,
    generate_world,
    read_manifest,
    read_world,
    validate_world,
    write_world,
)

SMALL = SyntheticConfig(seed=7, n_skus=10, n_suppliers=8, n_weeks=52, target_sales_orders=2_000)


@pytest.fixture(scope="module")
def default_world() -> SyntheticWorld:
    return generate_world()


def test_default_world_matches_locked_scale(default_world: SyntheticWorld) -> None:
    assert len(default_world.skus) == 40
    assert len(default_world.suppliers) == 10
    assert len(default_world.warehouses) == 3
    assert len(default_world.regions) == 5
    assert 19_000 <= len(default_world.sales_orders) <= 21_000
    span_days = (default_world.as_of - default_world.config.start_date).days
    assert 12 * 30 <= span_days <= 24 * 31  # 12-24 months of history


def test_default_world_passes_validation(default_world: SyntheticWorld) -> None:
    assert validate_world(default_world) == []


def test_constraints_are_encoded(default_world: SyntheticWorld) -> None:
    statuses = {c.status for c in default_world.contracts}
    assert statuses == {ContractStatus.ACTIVE, ContractStatus.EXPIRED, ContractStatus.SUSPENDED}
    assert len({o.moq for o in default_world.offers}) > 1
    assert len({o.lead_time_days for o in default_world.offers}) > 5
    assert any(sku.required_certifications for sku in default_world.skus)
    assert all(o.capacity_per_week >= o.moq for o in default_world.offers)
    assert any(po.status.value == "PLACED" for po in default_world.purchase_orders)
    assert any(
        po.delivered_quantity is not None and po.delivered_quantity < po.quantity
        for po in default_world.purchase_orders
    )


def test_same_seed_is_reproducible(tmp_path: Path) -> None:
    first, second = generate_world(SMALL), generate_world(SMALL)
    assert first == second
    manifest_a = write_world(first, tmp_path / "a")
    manifest_b = write_world(second, tmp_path / "b")
    assert manifest_a == manifest_b
    for name in manifest_a["files"]:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_different_seed_changes_data() -> None:
    other = generate_world(SMALL.model_copy(update={"seed": 8}))
    assert other.sales_orders != generate_world(SMALL).sales_orders


def test_round_trip_through_disk(tmp_path: Path) -> None:
    world = generate_world(SMALL)
    manifest = write_world(world, tmp_path)
    assert manifest["dataset_id"].startswith("synthetic-v1-")
    assert read_world(tmp_path) == world
    assert read_manifest(tmp_path)["config"]["seed"] == 7


def test_tampered_file_is_detected(tmp_path: Path) -> None:
    write_world(generate_world(SMALL), tmp_path)
    path = tmp_path / "offers.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        read_world(tmp_path)


def test_validation_reports_broken_references() -> None:
    world = generate_world(SMALL)
    broken_offer = world.offers[0].model_copy(update={"supplier_id": "SUP-999"})
    broken = replace(world, offers=[broken_offer, *world.offers[1:]])
    issues = validate_world(broken)
    assert any("unknown supplier" in issue for issue in issues)


def test_validation_reports_capacity_overflow() -> None:
    world = generate_world(SMALL)
    tiny = world.warehouses[0].model_copy(update={"capacity_units": 1.0})
    broken = replace(world, warehouses=[tiny, *world.warehouses[1:]])
    assert any("above capacity" in issue for issue in validate_world(broken))


def test_history_does_not_leak_past_as_of(default_world: SyntheticWorld) -> None:
    last_order = max(o.ordered_at for o in default_world.sales_orders)
    assert last_order.date() < default_world.as_of
    for po in default_world.purchase_orders:
        if po.delivered_at is not None:
            assert po.delivered_at <= default_world.as_of
