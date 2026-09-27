from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from pydantic import Field

from scm_common.domain import ContractStatus, DocumentType, DomainModel, PolicyDocument
from scm_ml.synthetic import SyntheticWorld

PLANNER = "planner"
PROCUREMENT_MANAGER = "procurement_manager"
FINANCE = "finance"
ADMIN = "admin"
ALL_ROLES = (PLANNER, PROCUREMENT_MANAGER, FINANCE, ADMIN)
CORPUS_VERSION = "1"

ENTERPRISE_START = date(2023, 1, 1)
FREIGHT_TERMS = (
    ("FOB Origin", "the buyer", 7),
    ("DAP Destination", "the supplier", 10),
    ("FCA Carrier", "the buyer", 14),
)
CATEGORY_SPECS = {
    "electronics": ("RoHS", "15-30 C, below 60% relative humidity", "anti-static sealed", "none"),
    "food": ("HACCP", "2-8 C cold chain", "food-grade sealed", "90 days"),
    "industrial": ("ISO9001", "ambient, dry storage", "palletised and strapped", "none"),
    "home": ("none", "ambient", "standard cartons", "none"),
    "apparel": ("none", "ambient, away from direct sunlight", "polybagged", "none"),
}


class Expectation(StrEnum):
    ANSWER = "ANSWER"
    QUALIFY_EXPIRED = "QUALIFY_EXPIRED"
    FLAG_CONFLICT = "FLAG_CONFLICT"
    DENY = "DENY"


class GroundTruth(DomainModel):
    fact_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    role: str = Field(description="Role of the person asking.")
    expectation: Expectation
    expected_answer: str = Field(description="Text the answer must state (empty for DENY).")
    document_id: str
    version: str
    forbidden_answer: str | None = Field(
        default=None, description="A stale or restricted value that must not be asserted."
    )
    conflicting_document_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Corpus:
    as_of: date
    documents: tuple[PolicyDocument, ...]
    facts: tuple[GroundTruth, ...]

    def get(self, document_id: str, version: str) -> PolicyDocument:
        return next(
            d for d in self.documents if d.document_id == document_id and d.version == version
        )


def _money(value: float) -> str:
    return f"{value:,.0f}"


class _Builder:
    def __init__(self, world: SyntheticWorld) -> None:
        self.world = world
        self.as_of = world.as_of
        self.documents: list[PolicyDocument] = []
        self.facts: list[GroundTruth] = []

    def doc(
        self,
        document_id: str,
        doc_type: DocumentType,
        title: str,
        version: str,
        effective: date,
        content: str,
        *,
        expiry: date | None = None,
        supplier_id: str | None = None,
        roles: tuple[str, ...] = ALL_ROLES,
    ) -> None:
        self.documents.append(
            PolicyDocument(
                document_id=document_id,
                doc_type=doc_type,
                title=title,
                version=version,
                effective_date=effective,
                expiry_date=expiry,
                supplier_id=supplier_id,
                allowed_roles=roles,
                content=content.strip(),
            )
        )

    def fact(
        self,
        question: str,
        answer: str,
        document_id: str,
        version: str,
        *,
        expectation: Expectation = Expectation.ANSWER,
        role: str = PLANNER,
        forbidden: str | None = None,
        conflicts: tuple[str, ...] = (),
    ) -> None:
        self.facts.append(
            GroundTruth(
                fact_id=f"FACT-{len(self.facts) + 1:03d}",
                question=question,
                role=role,
                expectation=expectation,
                expected_answer=answer,
                document_id=document_id,
                version=version,
                forbidden_answer=forbidden,
                conflicting_document_ids=conflicts,
            )
        )

    def supplier_documents(self) -> None:
        contracts = {c.supplier_id: c for c in self.world.contracts}
        for index, supplier in enumerate(self.world.suppliers):
            contract = contracts[supplier.supplier_id]
            sid, label = supplier.supplier_id, f"{supplier.name} ({supplier.supplier_id})"
            cap = (
                "No per-order value cap applies to purchase orders under this agreement."
                if contract.max_order_value is None
                else f"The maximum value of a single purchase order is USD "
                f"{_money(contract.max_order_value)}; larger requirements must be split or "
                f"separately approved."
            )
            body = f"""
Master Supply Agreement between the Company and {label}, shipping from region {supplier.region_id}.
Contract reference {contract.contract_id}. Term: {contract.effective_from.isoformat()} to
{contract.effective_to.isoformat()}.

1. Payment. Invoices are payable within {contract.payment_terms_days} days of delivery acceptance.
2. Order limits. {cap}
3. Quality. The supplier shall maintain the certifications listed in the certification register
({", ".join(supplier.certifications) or "none required"}).
4. Price validity. Offer prices remain valid for the period stated on each offer; changes require
30 days written notice.
5. Termination. Either party may terminate for material breach after a 30 day cure period.
""".strip()
            self.doc(
                f"CTR-{sid}",
                DocumentType.CONTRACT,
                f"Master supply agreement - {supplier.name}",
                "1",
                contract.effective_from,
                body,
                expiry=contract.effective_to,
                supplier_id=sid,
            )
            if contract.status == ContractStatus.EXPIRED:
                self.fact(
                    f"What are the payment terms in the contract with {label}?",
                    f"{contract.payment_terms_days} days",
                    f"CTR-{sid}",
                    "1",
                    expectation=Expectation.QUALIFY_EXPIRED,
                )
            elif contract.status == ContractStatus.ACTIVE:
                self.fact(
                    f"What are the payment terms for {label}?",
                    f"{contract.payment_terms_days} days",
                    f"CTR-{sid}",
                    "1",
                )
                if contract.max_order_value is not None and index % 2 == 0:
                    self.fact(
                        f"What is the maximum value of a single purchase order with {label}?",
                        _money(contract.max_order_value),
                        f"CTR-{sid}",
                        "1",
                    )
            if contract.status == ContractStatus.SUSPENDED:
                suspended_on = self.as_of - timedelta(days=21)
                self.doc(
                    f"NTC-{sid}",
                    DocumentType.CONTRACT,
                    f"Suspension notice - {supplier.name}",
                    "1",
                    suspended_on,
                    f"""
Notice of suspension. Effective {suspended_on.isoformat()} the supply agreement with {label} is
suspended following repeated quality escapes. No new purchase orders may be placed with this
supplier until procurement management lifts the suspension in writing. Open orders continue to be
received and inspected under the receiving SOP.
""",
                    supplier_id=sid,
                )
                self.fact(
                    f"Can we place new purchase orders with {label}?",
                    "No",
                    f"NTC-{sid}",
                    "1",
                )

            offers = [o for o in self.world.offers if o.supplier_id == sid]
            commit = round(statistics.median(o.lead_time_days for o in offers)) if offers else 14
            target = round(max(0.80, supplier.reliability - 0.03), 2)
            sla_current = f"""
Service level agreement with {label}.
1. On-time-in-full. The supplier commits to an on-time-in-full delivery rate of at least
{target:.0%} measured monthly.
2. Lead time. The committed lead time is {commit} days from purchase order confirmation.
3. Credits. Late deliveries earn a service credit of 2% of the order value per week of delay,
capped at 10% of the order value.
4. Reporting. The supplier provides a monthly performance report within 5 business days.
"""
            if index == 2:  # a superseded SLA version for one supplier
                old_target = round(target - 0.05, 2)
                amended = date(2024, 4, 1)
                self.doc(
                    f"SLA-{sid}",
                    DocumentType.SLA,
                    f"Service level agreement - {supplier.name}",
                    "1",
                    ENTERPRISE_START,
                    sla_current.replace(f"{target:.0%}", f"{old_target:.0%}"),
                    expiry=amended - timedelta(days=1),
                    supplier_id=sid,
                )
                self.doc(
                    f"SLA-{sid}",
                    DocumentType.SLA,
                    f"Service level agreement - {supplier.name}",
                    "2",
                    amended,
                    sla_current,
                    supplier_id=sid,
                )
                self.fact(
                    f"What on-time-in-full rate does {label} commit to?",
                    f"{target:.0%}",
                    f"SLA-{sid}",
                    "2",
                    forbidden=f"{old_target:.0%}",
                )
            else:
                self.doc(
                    f"SLA-{sid}",
                    DocumentType.SLA,
                    f"Service level agreement - {supplier.name}",
                    "1",
                    ENTERPRISE_START,
                    sla_current,
                    supplier_id=sid,
                )
                if index in (0, 4):
                    self.fact(
                        f"What is the committed lead time for {label}?",
                        f"{commit} days",
                        f"SLA-{sid}",
                        "1",
                    )

            incoterm, payer, claims_days = FREIGHT_TERMS[index % len(FREIGHT_TERMS)]
            self.doc(
                f"SHP-{sid}",
                DocumentType.SHIPPING_TERMS,
                f"Shipping terms - {supplier.name}",
                "1",
                ENTERPRISE_START,
                f"""
Shipping terms with {label}.
1. Incoterm. Deliveries are made {incoterm}.
2. Freight. Freight is paid by {payer}.
3. Damage claims. Transit damage must be reported within {claims_days} days of receipt;
later claims are not accepted.
4. Documentation. Each shipment carries a packing list and a certificate of conformance.
""",
                supplier_id=sid,
            )
            if index in (1, 5):
                self.fact(
                    f"Within how many days must transit damage be reported for {label}?",
                    f"{claims_days} days",
                    f"SHP-{sid}",
                    "1",
                )
            if index == 3:
                self.fact(
                    f"Who pays freight on shipments from {label}?",
                    payer.replace("the ", ""),
                    f"SHP-{sid}",
                    "1",
                )

            for cert in supplier.certifications:
                valid_to = date(self.as_of.year + 1, 6, 30)
                self.doc(
                    f"CERT-{sid}-{cert}",
                    DocumentType.CERTIFICATION,
                    f"{cert} certificate - {supplier.name}",
                    "1",
                    date(self.as_of.year - 1, 7, 1),
                    f"""
Certificate of conformity. {label} is certified to {cert}. The certificate is valid until
{valid_to.isoformat()} and is subject to annual surveillance audit.
""",
                    expiry=valid_to,
                    supplier_id=sid,
                )
            if index == 6:
                self.fact(
                    f"Until when is the ISO9001 certificate of {label} valid?",
                    date(self.as_of.year + 1, 6, 30).isoformat(),
                    f"CERT-{sid}-ISO9001",
                    "1",
                )

        top = self.world.suppliers[0]
        self.doc(
            f"PRC-{top.supplier_id}",
            DocumentType.CONTRACT,
            f"Pricing and rebate agreement - {top.name}",
            "1",
            date(2024, 1, 1),
            f"""
Confidential pricing and rebate agreement with {top.name} ({top.supplier_id}).
1. Volume rebate. A rebate of 3% of annual spend is paid on spend above USD 500,000 per
calendar year.
2. Confidentiality. This agreement is restricted to finance and administration roles.
""",
            supplier_id=top.supplier_id,
            roles=(FINANCE, ADMIN),
        )
        question = f"What volume rebate does {top.name} ({top.supplier_id}) pay on annual spend?"
        self.fact(
            question,
            "3%",
            f"PRC-{top.supplier_id}",
            "1",
            role=FINANCE,
        )
        self.fact(
            question,
            "",
            f"PRC-{top.supplier_id}",
            "1",
            expectation=Expectation.DENY,
            role=PLANNER,
            forbidden="3%",
        )

    def policy_documents(self) -> None:
        approval_v1 = (10_000, 50_000)
        approval_v2 = (15_000, 75_000)
        switch = date(2024, 7, 1)

        def approval(thresholds: tuple[int, int]) -> str:
            return f"""
Purchase order approval policy.
1. Orders up to USD {_money(thresholds[0])} may be approved by the buyer.
2. Orders above USD {_money(thresholds[0])} require procurement manager approval.
3. Orders above USD {_money(thresholds[1])} additionally require finance approval.
4. Splitting an order to stay under a threshold is prohibited.
"""

        self.doc(
            "POL-APPROVAL",
            DocumentType.POLICY,
            "Purchase order approval policy",
            "1",
            ENTERPRISE_START,
            approval(approval_v1),
            expiry=switch - timedelta(days=1),
        )
        self.doc(
            "POL-APPROVAL",
            DocumentType.POLICY,
            "Purchase order approval policy",
            "2",
            switch,
            approval(approval_v2),
        )
        self.fact(
            "Above what order value is procurement manager approval required?",
            _money(approval_v2[0]),
            "POL-APPROVAL",
            "2",
            forbidden=_money(approval_v1[0]),
        )
        self.fact(
            "Above what order value is finance approval also required?",
            _money(approval_v2[1]),
            "POL-APPROVAL",
            "2",
            forbidden=_money(approval_v1[1]),
        )

        east = next(r for r in self.world.regions if r.region_id == "R3")
        regional = 12_000
        self.doc(
            "POL-APPROVAL-R3",
            DocumentType.POLICY,
            f"{east.name} region procurement addendum",
            "1",
            date(2024, 9, 1),
            f"""
Regional addendum for the {east.name} region ({east.region_id}).
1. Orders delivered to the {east.name} region require procurement manager approval above
USD {_money(regional)}.
2. All other terms follow the Company approval policy.
""",
        )
        self.fact(
            f"Above what order value is manager approval required for deliveries to the "
            f"{east.name} region?",
            f"{_money(regional)}",
            "POL-APPROVAL-R3",
            "1",
            expectation=Expectation.FLAG_CONFLICT,
            conflicts=("POL-APPROVAL",),
        )

        self.doc(
            "POL-SOURCING",
            DocumentType.POLICY,
            "Supplier selection policy",
            "1",
            ENTERPRISE_START,
            """
Supplier selection policy.
1. Every critical SKU must have at least 2 qualified suppliers.
2. No single supplier may receive more than 60% of the spend on one SKU in a quarter.
3. Only suppliers with an active contract and all certifications required by the SKU may
be selected.
""",
        )
        self.fact(
            "What share of one SKU's spend may go to a single supplier in a quarter?",
            "60%",
            "POL-SOURCING",
            "1",
        )
        self.doc(
            "POL-BUDGET",
            DocumentType.POLICY,
            "Quarterly procurement budget",
            "1",
            date(2024, 10, 1),
            """
Quarterly procurement budget policy. The approved procurement budget is USD 1,200,000 per
quarter. This policy is restricted to finance and administration roles.
""",
            roles=(FINANCE, ADMIN),
        )
        self.fact(
            "What is the quarterly procurement budget?",
            "1,200,000",
            "POL-BUDGET",
            "1",
            role=FINANCE,
        )
        self.fact(
            "What is the quarterly procurement budget?",
            "",
            "POL-BUDGET",
            "1",
            expectation=Expectation.DENY,
            role=PROCUREMENT_MANAGER,
            forbidden="1,200,000",
        )
        self.doc(
            "POL-WAREHOUSE",
            DocumentType.POLICY,
            "Warehouse operating policy",
            "1",
            ENTERPRISE_START,
            """
Warehouse operating policy.
1. Storage utilisation must not exceed 90% of rated capacity.
2. Food products are stored segregated from industrial goods.
3. Inventory is cycle counted every quarter.
""",
        )
        self.fact(
            "What is the maximum storage utilisation allowed in a warehouse?",
            "90%",
            "POL-WAREHOUSE",
            "1",
        )

        sops = {
            "SOP-STOCKOUT": (
                "Stockout response SOP",
                "Stockout response. 1. Planners escalate a projected stockout to procurement "
                "within 24 hours. 2. Procurement requests expedited delivery from qualified "
                "suppliers. 3. Customer service is notified of any delay beyond 5 days.",
                ("How soon must a projected stockout be escalated to procurement?", "24 hours"),
            ),
            "SOP-OUTAGE": (
                "Supplier outage SOP",
                "Supplier outage response. 1. Procurement is notified within 4 business hours. "
                "2. Backup suppliers are activated for affected SKUs. 3. Planning re-runs the "
                "procurement plan using the disruption scenario.",
                (
                    "Within what time must procurement be notified of a supplier outage?",
                    "4 business hours",
                ),
            ),
            "SOP-RECEIVING": (
                "Receiving and inspection SOP",
                "Receiving and inspection. 1. Inspect every delivery within 48 hours of "
                "arrival. 2. Quarantine a lot when more than 2% of sampled units are defective. "
                "3. Record the result against the supplier scorecard.",
                ("Above what defect rate is a delivered lot quarantined?", "2%"),
            ),
            "SOP-SAFETY": (
                "Safety stock review SOP",
                "Safety stock review. 1. Review safety stock monthly. 2. The service-level "
                "target for safety stock sizing is 95%. 3. Changes above 20% need manager "
                "sign-off.",
                ("What service-level target is used to size safety stock?", "95%"),
            ),
        }
        for document_id, (title, text, (question, answer)) in sops.items():
            self.doc(document_id, DocumentType.SOP, title, "1", ENTERPRISE_START, text)
            self.fact(question, answer, document_id, "1")

        for category, (cert, storage, packaging, shelf) in CATEGORY_SPECS.items():
            self.doc(
                f"SPEC-{category.upper()}",
                DocumentType.SPECIFICATION,
                f"{category.capitalize()} product specification",
                "1",
                ENTERPRISE_START,
                f"""
Product specification for the {category} category.
1. Required certification: {cert}.
2. Storage: {storage}.
3. Packaging: {packaging}.
4. Maximum shelf life before receipt: {shelf}.
""",
            )
        self.fact(
            "What certification do electronics products require?",
            "RoHS",
            "SPEC-ELECTRONICS",
            "1",
        )
        self.fact(
            "What storage temperature do food products require?",
            "2-8 C",
            "SPEC-FOOD",
            "1",
        )


def build_corpus(world: SyntheticWorld) -> Corpus:
    builder = _Builder(world)
    builder.supplier_documents()
    builder.policy_documents()
    return Corpus(world.as_of, tuple(builder.documents), tuple(builder.facts))
