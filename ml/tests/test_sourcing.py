from datetime import date, timedelta
from typing import Any

import pytest

from scm_common.domain import (
    ContractStatus,
    Sku,
    Supplier,
    SupplierContract,
    SupplierOffer,
    Warehouse,
)
from scm_ml.sourcing import (
    Criterion,
    RankingWeights,
    RejectionReason,
    SourcingCatalog,
    SourcingError,
    SourcingRequest,
    cheapest_first,
    eligible_offers,
    evaluate_eligibility,
    rank_offers,
    source_suppliers,
)
from scm_ml.synthetic import SyntheticConfig, generate_world

AS_OF = date(2025, 1, 6)


def _supplier(
    sid: str, *, reliability: float = 0.9, quality: float = 0.9, certs: tuple[str, ...] = ("ISO",)
) -> Supplier:
    return Supplier(
        supplier_id=sid,
        name=f"Supplier {sid}",
        region_id="R1",
        reliability=reliability,
        quality_score=quality,
        certifications=tuple(certs),
    )


def _contract(sid: str, **overrides: Any) -> SupplierContract:
    fields: dict[str, Any] = {
        "contract_id": f"C-{sid}",
        "supplier_id": sid,
        "status": ContractStatus.ACTIVE,
        "effective_from": AS_OF - timedelta(days=100),
        "effective_to": AS_OF + timedelta(days=100),
        "payment_terms_days": 60,
        "max_order_value": None,
    }
    fields.update(overrides)
    return SupplierContract(**fields)


def _offer(sid: str, **overrides: Any) -> SupplierOffer:
    fields: dict[str, Any] = {
        "offer_id": f"O-{sid}",
        "supplier_id": sid,
        "sku_id": "SKU-1",
        "unit_price": 10.0,
        "moq": 10,
        "capacity_per_week": 500,
        "lead_time_days": 10,
        "shipping_cost_per_unit": {"WH-1": 1.0},
        "valid_from": AS_OF - timedelta(days=30),
        "valid_to": AS_OF + timedelta(days=30),
    }
    fields.update(overrides)
    return SupplierOffer(**fields)


def _catalog(
    suppliers: list[Supplier], contracts: list[SupplierContract], offers: list[SupplierOffer]
) -> SourcingCatalog:
    sku = Sku(
        sku_id="SKU-1",
        name="Widget",
        category="c",
        unit_price=20.0,
        unit_volume=1.0,
        required_certifications=("ISO",),
    )
    warehouse = Warehouse(
        warehouse_id="WH-1",
        name="W",
        region_id="R1",
        capacity_units=10_000,
        holding_cost_per_unit_week=0.1,
    )
    return SourcingCatalog.build([sku], suppliers, [warehouse], contracts, offers)


def _request(**overrides: Any) -> SourcingRequest:
    fields: dict[str, Any] = {
        "sku_id": "SKU-1",
        "warehouse_id": "WH-1",
        "quantity": 100,
        "as_of": AS_OF,
        "max_lead_time_days": 20,
    }
    fields.update(overrides)
    return SourcingRequest(**fields)


def _reasons(catalog: SourcingCatalog, request: SourcingRequest, sid: str) -> set[RejectionReason]:
    decision = next(d for d in evaluate_eligibility(request, catalog) if d.supplier_id == sid)
    return {r.reason for r in decision.rejections}


def _single(
    offer: SupplierOffer, contract: SupplierContract | None = None, **supplier: Any
) -> SourcingCatalog:
    sid = offer.supplier_id
    contracts = [contract if contract is not None else _contract(sid)]
    return _catalog([_supplier(sid, **supplier)], contracts, [offer])


def test_clean_offer_is_eligible() -> None:
    catalog = _single(_offer("S1"))
    (decision,) = evaluate_eligibility(_request(), catalog)
    assert decision.eligible and decision.rejections == ()


@pytest.mark.parametrize(
    ("offer", "request_overrides", "expected"),
    [
        ({"moq": 200}, {}, RejectionReason.BELOW_MOQ),
        ({"capacity_per_week": 50}, {}, RejectionReason.EXCEEDS_CAPACITY),
        ({"lead_time_days": 30}, {}, RejectionReason.LEAD_TIME_TOO_LONG),
        ({"shipping_cost_per_unit": {"WH-9": 1.0}}, {}, RejectionReason.REGION_NOT_SERVED),
        (
            {"valid_to": AS_OF - timedelta(days=1)},
            {},
            RejectionReason.OFFER_NOT_VALID,
        ),
        ({}, {"allowed_supplier_regions": ("R9",)}, RejectionReason.SUPPLIER_REGION_EXCLUDED),
    ],
)
def test_each_offer_rule_rejects_with_its_reason(
    offer: dict[str, Any], request_overrides: dict[str, Any], expected: RejectionReason
) -> None:
    catalog = _single(_offer("S1", **offer))
    assert _reasons(catalog, _request(**request_overrides), "S1") == {expected}


def test_horizon_extends_available_capacity() -> None:
    catalog = _single(_offer("S1", capacity_per_week=50))
    assert _reasons(catalog, _request(horizon_weeks=1), "S1") == {RejectionReason.EXCEEDS_CAPACITY}
    assert _reasons(catalog, _request(horizon_weeks=2), "S1") == set()


def test_missing_certification_names_what_is_missing() -> None:
    catalog = _single(_offer("S1"), certs=())
    (decision,) = evaluate_eligibility(_request(), catalog)
    assert [r.reason for r in decision.rejections] == [RejectionReason.MISSING_CERTIFICATION]
    assert "ISO" in decision.rejections[0].detail


def test_supplier_without_offer_is_rejected_for_product() -> None:
    catalog = _catalog([_supplier("S1"), _supplier("S2")], [_contract("S1")], [_offer("S1")])
    assert _reasons(catalog, _request(), "S2") == {
        RejectionReason.NO_OFFER_FOR_SKU,
    }


@pytest.mark.parametrize(
    ("contract", "expected"),
    [
        ({"status": ContractStatus.EXPIRED}, RejectionReason.CONTRACT_EXPIRED),
        (
            {"effective_to": AS_OF - timedelta(days=1)},
            RejectionReason.CONTRACT_EXPIRED,
        ),
        ({"status": ContractStatus.SUSPENDED}, RejectionReason.CONTRACT_SUSPENDED),
        ({"max_order_value": 500.0}, RejectionReason.ORDER_VALUE_EXCEEDS_CONTRACT),
    ],
)
def test_contract_rules(contract: dict[str, Any], expected: RejectionReason) -> None:
    catalog = _single(_offer("S1"), _contract("S1", **contract))
    assert _reasons(catalog, _request(), "S1") == {expected}


def test_missing_contract_is_rejected() -> None:
    catalog = _catalog([_supplier("S1")], [], [_offer("S1")])
    assert _reasons(catalog, _request(), "S1") == {RejectionReason.NO_CONTRACT}


def test_all_failing_rules_are_reported() -> None:
    catalog = _single(_offer("S1", moq=200, lead_time_days=30), certs=())
    assert _reasons(catalog, _request(), "S1") == {
        RejectionReason.BELOW_MOQ,
        RejectionReason.LEAD_TIME_TOO_LONG,
        RejectionReason.MISSING_CERTIFICATION,
    }


def test_unknown_sku_or_warehouse_is_an_error() -> None:
    catalog = _single(_offer("S1"))
    with pytest.raises(SourcingError):
        evaluate_eligibility(_request(sku_id="NOPE"), catalog)
    with pytest.raises(SourcingError):
        evaluate_eligibility(_request(warehouse_id="NOPE"), catalog)


def _three_supplier_catalog() -> SourcingCatalog:
    suppliers = [
        _supplier("A", reliability=0.80, quality=0.70),
        _supplier("B", reliability=0.95, quality=0.90),
        _supplier("C", reliability=0.90, quality=0.80),
    ]
    contracts = [_contract(s.supplier_id) for s in suppliers]
    offers = [
        _offer("A", unit_price=9.0, lead_time_days=20),
        _offer("B", unit_price=11.0, lead_time_days=5),
        _offer("C", unit_price=10.0, lead_time_days=12),
    ]
    return _catalog(suppliers, contracts, offers)


def test_score_components_reproduce_the_score_exactly() -> None:
    catalog = _three_supplier_catalog()
    request = _request()
    ranking = rank_offers(eligible_offers(request, catalog), request, catalog)
    for ranked in ranking:
        assert ranked.score == pytest.approx(
            sum(c.weight * c.normalized for c in ranked.components)
        )
        assert {c.criterion for c in ranked.components} == set(Criterion)
    assert [r.rank for r in ranking] == [1, 2, 3]


def test_ranking_matches_hand_calculation() -> None:
    catalog = _three_supplier_catalog()
    request = _request()
    weights = RankingWeights(
        cost=0.5, lead_time=0.5, reliability=0, capacity=0, quality=0, contract_fit=0
    )
    ranking = {
        r.supplier_id: r.score
        for r in rank_offers(eligible_offers(request, catalog), request, catalog, weights)
    }
    # landed cost: A=10, B=12, C=11 -> normalized A=1, B=0, C=0.5
    # lead time:   A=20, B=5,  C=12 -> normalized A=0, B=1, C=8/15
    assert ranking["A"] == pytest.approx(0.5 * 1 + 0.5 * 0)
    assert ranking["B"] == pytest.approx(0.5 * 0 + 0.5 * 1)
    assert ranking["C"] == pytest.approx(0.5 * 0.5 + 0.5 * (8 / 15))


def test_weights_change_the_winner_and_cheapest_baseline_differs() -> None:
    catalog = _three_supplier_catalog()
    request = _request()
    offers = eligible_offers(request, catalog)
    cost_only = RankingWeights(
        cost=1, lead_time=0, reliability=0, capacity=0, quality=0, contract_fit=0
    )
    speed_only = RankingWeights(
        cost=0, lead_time=1, reliability=0, capacity=0, quality=0, contract_fit=0
    )
    assert rank_offers(offers, request, catalog, cost_only)[0].supplier_id == "A"
    assert rank_offers(offers, request, catalog, speed_only)[0].supplier_id == "B"
    assert cheapest_first(offers, "WH-1")[0].supplier_id == "A"


def test_ranking_is_deterministic_and_breaks_ties_by_supplier_id() -> None:
    suppliers = [_supplier("B"), _supplier("A")]
    catalog = _catalog(suppliers, [_contract("A"), _contract("B")], [_offer("B"), _offer("A")])
    request = _request()
    first = rank_offers(eligible_offers(request, catalog), request, catalog)
    second = rank_offers(list(reversed(eligible_offers(request, catalog))), request, catalog)
    assert [r.supplier_id for r in first] == ["A", "B"]
    assert first == second


def test_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        RankingWeights(cost=0.9)


def test_comparison_exposes_trade_offs() -> None:
    catalog = _three_supplier_catalog()
    request = _request()
    weights = RankingWeights(
        cost=0.2, lead_time=0.4, reliability=0.4, capacity=0, quality=0, contract_fit=0
    )
    result = source_suppliers(request, catalog, weights)
    top = result.comparison.rows[0]
    assert top.supplier_id == "B"
    assert top.cost_vs_cheapest_pct == pytest.approx(20.0)
    assert top.lead_time_vs_fastest_days == 0
    leaders = {leader.criterion: leader.supplier_id for leader in result.comparison.leaders}
    assert leaders[Criterion.COST] == "A"
    assert leaders[Criterion.LEAD_TIME] == "B"
    assert any("20.0% more than the cheapest" in t for t in result.comparison.trade_offs)


def test_result_summarises_rejections() -> None:
    suppliers = [_supplier("A"), _supplier("B", certs=())]
    catalog = _catalog(suppliers, [_contract("A"), _contract("B")], [_offer("A"), _offer("B")])
    result = source_suppliers(_request(), catalog)
    assert [r.supplier_id for r in result.ranking] == ["A"]
    assert result.rejection_counts == {"MISSING_CERTIFICATION": 1}


def test_no_eligible_supplier_yields_empty_comparison() -> None:
    catalog = _single(_offer("S1", moq=500))
    result = source_suppliers(_request(), catalog)
    assert result.ranking == () and result.comparison.rows == ()


def test_pipeline_on_synthetic_world_is_explicit_and_reproducible() -> None:
    world = generate_world(SyntheticConfig())
    catalog = SourcingCatalog.from_world(world)
    sku = next(s for s in world.skus if s.required_certifications)
    request = SourcingRequest(
        sku_id=sku.sku_id,
        warehouse_id=world.warehouses[0].warehouse_id,
        quantity=200,
        as_of=world.as_of,
        max_lead_time_days=30,
        horizon_weeks=2,
    )
    first = source_suppliers(request, catalog)
    assert first == source_suppliers(request, catalog)
    assert len(first.decisions) == len(world.suppliers)
    for decision in first.decisions:
        assert decision.eligible == (not decision.rejections)
    assert first.ranking, "default world should leave at least one eligible supplier"
    suspended = {c.supplier_id for c in world.contracts if c.status != ContractStatus.ACTIVE}
    assert suspended.isdisjoint(r.supplier_id for r in first.ranking)
