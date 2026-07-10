from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from scm_common.domain import (
    Citation,
    ContractStatus,
    Decision,
    DecisionOutcome,
    DemandObservation,
    DocumentType,
    DomainModel,
    InventoryPosition,
    PolicyDocument,
    PurchaseLine,
    PurchaseOrder,
    PurchaseOrderStatus,
    Recommendation,
    Region,
    SalesOrder,
    Scenario,
    ScenarioType,
    Sku,
    Supplier,
    SupplierContract,
    SupplierOffer,
    Warehouse,
)

NOW = datetime(2025, 3, 1, 12, 0, tzinfo=UTC)
D = date(2025, 3, 1)

SAMPLES: list[DomainModel] = [
    Region(region_id="R1", name="North"),
    Sku(
        sku_id="S1",
        name="Widget",
        category="hardware",
        unit_price=9.5,
        unit_volume=0.2,
        required_certifications=("ISO9001",),
    ),
    Supplier(
        supplier_id="SUP1",
        name="Acme",
        region_id="R1",
        reliability=0.95,
        quality_score=0.9,
        certifications=("ISO9001",),
    ),
    Warehouse(
        warehouse_id="W1",
        name="Hub",
        region_id="R1",
        capacity_units=1000,
        holding_cost_per_unit_week=0.05,
    ),
    SupplierContract(
        contract_id="C1",
        supplier_id="SUP1",
        status=ContractStatus.ACTIVE,
        effective_from=D,
        effective_to=date(2026, 3, 1),
        payment_terms_days=30,
    ),
    SupplierOffer(
        offer_id="O1",
        supplier_id="SUP1",
        sku_id="S1",
        unit_price=5.0,
        moq=50,
        capacity_per_week=500,
        lead_time_days=14,
        shipping_cost_per_unit={"W1": 0.4},
        valid_from=D,
        valid_to=date(2026, 3, 1),
    ),
    SalesOrder(order_id="SO1", sku_id="S1", region_id="R1", ordered_at=NOW, quantity=12),
    DemandObservation(
        sku_id="S1",
        region_id="R1",
        period_start=D,
        quantity=120.0,
        source="synthetic-v1",
        observed_at=NOW,
    ),
    InventoryPosition(
        sku_id="S1", warehouse_id="W1", as_of=NOW, on_hand=100, incoming=20, safety_stock=30
    ),
    PurchaseOrder(
        po_id="PO1",
        supplier_id="SUP1",
        sku_id="S1",
        warehouse_id="W1",
        quantity=100,
        unit_price=5.0,
        status=PurchaseOrderStatus.PLACED,
        created_at=NOW,
        expected_delivery=date(2025, 3, 15),
    ),
    PolicyDocument(
        document_id="D1",
        doc_type=DocumentType.CONTRACT,
        title="Acme MSA",
        version="2",
        effective_date=D,
        supplier_id="SUP1",
        allowed_roles=("planner",),
        content="Payment within 30 days.",
    ),
    Scenario(
        scenario_id="SC1",
        name="Demand +20%",
        scenario_type=ScenarioType.DEMAND_SHOCK,
        parameters={"factor": 1.2},
        created_at=NOW,
    ),
    Recommendation(
        recommendation_id="REC1",
        created_at=NOW,
        summary="Buy from Acme",
        lines=(
            PurchaseLine(
                supplier_id="SUP1",
                sku_id="S1",
                warehouse_id="W1",
                quantity=100,
                unit_price=5.0,
                shipping_cost=40.0,
            ),
        ),
        objective_value=540.0,
        expected_service_level=0.97,
        citations=(Citation(document_id="D1", version="2", excerpt="Payment within 30 days."),),
        horizon_start=D,
        horizon_end=date(2025, 4, 1),
    ),
    Decision(
        decision_id="DEC1",
        recommendation_id="REC1",
        decided_by="planner-1",
        outcome=DecisionOutcome.APPROVED,
        decided_at=NOW,
    ),
]


@pytest.mark.parametrize("model", SAMPLES, ids=lambda m: type(m).__name__)
def test_json_round_trip(model: DomainModel) -> None:
    restored = type(model).model_validate_json(model.model_dump_json())
    assert restored == model


@pytest.mark.parametrize("model", SAMPLES, ids=lambda m: type(m).__name__)
def test_unknown_fields_are_rejected(model: DomainModel) -> None:
    payload = model.model_dump(mode="json") | {"unexpected": 1}
    with pytest.raises(ValidationError):
        type(model).model_validate(payload)


def test_models_are_immutable() -> None:
    region = Region(region_id="R1", name="North")
    with pytest.raises(ValidationError):
        region.name = "South"  # type: ignore[misc]


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SalesOrder(
            order_id="SO1",
            sku_id="S1",
            region_id="R1",
            ordered_at=datetime(2025, 3, 1, 12, 0),
            quantity=1,
        )


def test_timestamp_is_normalised_to_utc() -> None:
    plus7 = timezone(timedelta(hours=7))
    order = SalesOrder(
        order_id="SO1",
        sku_id="S1",
        region_id="R1",
        ordered_at=datetime(2025, 3, 1, 19, 0, tzinfo=plus7),
        quantity=1,
    )
    assert order.ordered_at == NOW
    assert order.ordered_at.utcoffset() == timedelta(0)


def test_offer_validity_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        SupplierOffer(
            offer_id="O",
            supplier_id="SUP1",
            sku_id="S1",
            unit_price=1,
            moq=1,
            capacity_per_week=1,
            lead_time_days=1,
            valid_from=date(2025, 2, 1),
            valid_to=date(2025, 1, 1),
        )


def test_invalid_numeric_ranges_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Supplier(supplier_id="X", name="X", region_id="R1", reliability=1.2, quality_score=0.5)
    with pytest.raises(ValidationError):
        SalesOrder(order_id="SO1", sku_id="S1", region_id="R1", ordered_at=NOW, quantity=0)


def test_document_effectiveness_window() -> None:
    doc = PolicyDocument(
        document_id="D",
        doc_type=DocumentType.POLICY,
        title="t",
        version="1",
        effective_date=date(2025, 1, 1),
        expiry_date=date(2025, 6, 30),
        allowed_roles=("planner",),
        content="c",
    )
    assert doc.is_effective_on(date(2025, 3, 1))
    assert not doc.is_effective_on(date(2025, 7, 1))
    assert not doc.is_effective_on(date(2024, 12, 31))
