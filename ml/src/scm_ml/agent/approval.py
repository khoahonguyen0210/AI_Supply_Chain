from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime

from scm_common.domain import (
    Decision,
    DecisionOutcome,
    PolicyDocument,
    Recommendation,
    RecommendationStatus,
)
from scm_ml.knowledge.corpus import ADMIN, FINANCE, PLANNER, PROCUREMENT_MANAGER

from .models import Actor
from .state import ApprovalRecord, ApprovalStatus, SqliteStateStore, now_utc

MANAGER_THRESHOLD = 15_000.0
FINANCE_THRESHOLD = 75_000.0
COVERS = {
    PLANNER: frozenset({PLANNER, PROCUREMENT_MANAGER, ADMIN}),
    PROCUREMENT_MANAGER: frozenset({PROCUREMENT_MANAGER, ADMIN}),
    FINANCE: frozenset({FINANCE}),
}


APPROVAL_POLICY_ID = "POL-APPROVAL"
_MANAGER_CLAUSE = re.compile(r"above USD ([\d,]+) require procurement manager approval", re.I)
_FINANCE_CLAUSE = re.compile(r"above USD ([\d,]+) additionally require finance approval", re.I)


class ApprovalError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class ApprovalPolicy:
    manager_threshold: float = MANAGER_THRESHOLD
    finance_threshold: float = FINANCE_THRESHOLD

    @classmethod
    def from_documents(cls, documents: Iterable[PolicyDocument], as_of: date) -> ApprovalPolicy:
        in_force = [
            d for d in documents if d.document_id == APPROVAL_POLICY_ID and d.is_effective_on(as_of)
        ]
        if not in_force:
            return cls()
        text = max(in_force, key=lambda d: d.effective_date).content
        manager, finance = _MANAGER_CLAUSE.search(text), _FINANCE_CLAUSE.search(text)
        return cls(
            manager_threshold=float(manager.group(1).replace(",", ""))
            if manager
            else MANAGER_THRESHOLD,
            finance_threshold=float(finance.group(1).replace(",", ""))
            if finance
            else FINANCE_THRESHOLD,
        )

    def required_roles(self, order_value: float) -> tuple[str, ...]:
        if order_value > self.finance_threshold:
            return (PROCUREMENT_MANAGER, FINANCE)
        if order_value > self.manager_threshold:
            return (PROCUREMENT_MANAGER,)
        return (PLANNER,)


class ApprovalService:
    def __init__(
        self,
        store: SqliteStateStore,
        policy: ApprovalPolicy | None = None,
        clock: Callable[[], datetime] = now_utc,
    ) -> None:
        self._store, self._policy, self._clock = store, policy or ApprovalPolicy(), clock

    @property
    def policy(self) -> ApprovalPolicy:
        return self._policy

    def request(
        self, task_id: str, recommendation: Recommendation, requester: Actor, order_value: float
    ) -> ApprovalRecord:
        """Opens a pending approval; nothing can act on the recommendation until approved."""
        pending = recommendation.model_copy(
            update={"status": RecommendationStatus.PENDING_APPROVAL}
        )
        record = ApprovalRecord(
            approval_id=f"APR-{self._store.next_approval_number():04d}",
            task_id=task_id,
            recommendation=pending,
            requested_by=requester.user_id,
            requester_role=requester.role,
            required_roles=self._policy.required_roles(order_value),
            order_value=order_value,
            created_at=self._clock(),
        )
        self._store.save_approval(record)
        return record

    def get(self, approval_id: str) -> ApprovalRecord:
        record = self._store.load_approval(approval_id)
        if record is None:
            raise ApprovalError("UNKNOWN_APPROVAL", f"no approval {approval_id}")
        return record

    def pending(self) -> list[ApprovalRecord]:
        return self._store.approvals(ApprovalStatus.PENDING)

    def decide(
        self,
        approval_id: str,
        approver: Actor,
        outcome: DecisionOutcome,
        rationale: str | None = None,
    ) -> ApprovalRecord:
        record = self.get(approval_id)
        if record.status != ApprovalStatus.PENDING:
            raise ApprovalError("ALREADY_DECIDED", f"approval {approval_id} is {record.status}")
        role = next((r for r in record.remaining_roles if approver.role in COVERS[r]), None)
        if role is None:
            raise ApprovalError(
                "NOT_AUTHORIZED",
                f"role {approver.role} cannot decide this approval; "
                f"needs {', '.join(record.remaining_roles)}",
            )
        if approver.user_id in record.approvers:
            raise ApprovalError("DUPLICATE_APPROVER", "one person cannot fill two approval roles")
        if approver.user_id == record.requested_by and record.order_value > (
            self._policy.manager_threshold
        ):
            raise ApprovalError("SELF_APPROVAL", "requesters cannot approve their own order")

        decision = Decision(
            decision_id=f"{approval_id}-D{self._store.decision_count() + 1:03d}",
            recommendation_id=record.recommendation.recommendation_id,
            decided_by=approver.user_id,
            outcome=outcome,
            decided_at=self._clock(),
            rationale=rationale,
        )
        self._store.append_decision(decision, approval_id, approver.role)
        if outcome == DecisionOutcome.REJECTED:
            updated = record.model_copy(
                update={
                    "status": ApprovalStatus.REJECTED,
                    "recommendation": record.recommendation.model_copy(
                        update={"status": RecommendationStatus.REJECTED}
                    ),
                }
            )
        else:
            approved_roles = (*record.approved_roles, role)
            done = all(r in approved_roles for r in record.required_roles)
            updated = record.model_copy(
                update={
                    "approved_roles": approved_roles,
                    "approvers": (*record.approvers, approver.user_id),
                    "status": ApprovalStatus.APPROVED if done else ApprovalStatus.PENDING,
                    "recommendation": record.recommendation.model_copy(
                        update={
                            "status": RecommendationStatus.APPROVED
                            if done
                            else RecommendationStatus.PENDING_APPROVAL
                        }
                    ),
                }
            )
        self._store.save_approval(updated)
        return updated
