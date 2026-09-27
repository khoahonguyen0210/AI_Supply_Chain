from __future__ import annotations

import sqlite3
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import Field

from scm_common.domain import Decision, DomainModel, Recommendation
from scm_common.domain.base import UtcDatetime

from .models import TaskStatus, TraceStep

_SCHEMA = """
CREATE TABLE IF NOT EXISTS task (
    task_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, role TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approval (
    approval_id TEXT PRIMARY KEY, status TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision (
    decision_id TEXT PRIMARY KEY, approval_id TEXT NOT NULL, recommendation_id TEXT NOT NULL,
    role TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS decision_no_update BEFORE UPDATE ON decision
BEGIN SELECT RAISE(ABORT, 'decision is append-only'); END;
CREATE TRIGGER IF NOT EXISTS decision_no_delete BEFORE DELETE ON decision
BEGIN SELECT RAISE(ABORT, 'decision is append-only'); END;
"""


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TaskRecord(DomainModel):
    task_id: str
    user_id: str
    role: str
    text: str
    status: TaskStatus | None = None
    steps: tuple[TraceStep, ...] = ()
    answer: str = ""
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ApprovalRecord(DomainModel):
    approval_id: str
    task_id: str
    recommendation: Recommendation
    requested_by: str
    requester_role: str
    required_roles: tuple[str, ...]
    approved_roles: tuple[str, ...] = ()
    approvers: tuple[str, ...] = ()
    order_value: float = Field(ge=0)
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: UtcDatetime

    @property
    def remaining_roles(self) -> tuple[str, ...]:
        return tuple(r for r in self.required_roles if r not in self.approved_roles)


class SqliteStateStore:
    def __init__(self, path: Path | str = ":memory:") -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def save_task(self, task: TaskRecord) -> None:
        self._db.execute(
            "INSERT INTO task (task_id, user_id, role, body) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(task_id) DO UPDATE SET body = excluded.body",
            (task.task_id, task.user_id, task.role, task.model_dump_json()),
        )
        self._db.commit()

    def load_task(self, task_id: str) -> TaskRecord | None:
        row = self._db.execute("SELECT body FROM task WHERE task_id = ?", (task_id,)).fetchone()
        return TaskRecord.model_validate_json(row[0]) if row else None

    def next_task_number(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM task").fetchone()[0]) + 1

    def next_approval_number(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM approval").fetchone()[0]) + 1

    def save_approval(self, approval: ApprovalRecord) -> None:
        self._db.execute(
            "INSERT INTO approval (approval_id, status, body) VALUES (?, ?, ?)"
            " ON CONFLICT(approval_id) DO UPDATE SET"
            " status = excluded.status, body = excluded.body",
            (approval.approval_id, approval.status.value, approval.model_dump_json()),
        )
        self._db.commit()

    def load_approval(self, approval_id: str) -> ApprovalRecord | None:
        row = self._db.execute(
            "SELECT body FROM approval WHERE approval_id = ?", (approval_id,)
        ).fetchone()
        return ApprovalRecord.model_validate_json(row[0]) if row else None

    def approvals(self, status: ApprovalStatus | None = None) -> list[ApprovalRecord]:
        query = "SELECT body FROM approval"
        args: tuple[str, ...] = ()
        if status is not None:
            query, args = query + " WHERE status = ?", (status.value,)
        rows = self._db.execute(query + " ORDER BY approval_id", args).fetchall()
        return [ApprovalRecord.model_validate_json(r[0]) for r in rows]

    def append_decision(self, decision: Decision, approval_id: str, role: str) -> None:
        self._db.execute(
            "INSERT INTO decision (decision_id, approval_id, recommendation_id, role, body)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                decision.decision_id,
                approval_id,
                decision.recommendation_id,
                role,
                decision.model_dump_json(),
            ),
        )
        self._db.commit()

    def decisions_for(self, recommendation_id: str) -> list[Decision]:
        rows = self._db.execute(
            "SELECT body FROM decision WHERE recommendation_id = ? ORDER BY decision_id",
            (recommendation_id,),
        ).fetchall()
        return [Decision.model_validate_json(r[0]) for r in rows]

    def decision_count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM decision").fetchone()[0])


def now_utc() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
