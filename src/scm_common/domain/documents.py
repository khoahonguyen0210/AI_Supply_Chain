from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from .base import DomainModel


class DocumentType(StrEnum):
    CONTRACT = "CONTRACT"
    SLA = "SLA"
    POLICY = "POLICY"
    SOP = "SOP"
    CERTIFICATION = "CERTIFICATION"
    SPECIFICATION = "SPECIFICATION"
    SHIPPING_TERMS = "SHIPPING_TERMS"


class PolicyDocument(DomainModel):
    document_id: str = Field(min_length=1)
    doc_type: DocumentType
    title: str = Field(min_length=1)
    version: str = Field(min_length=1)
    effective_date: date
    expiry_date: date | None = None
    supplier_id: str | None = None
    allowed_roles: tuple[str, ...] = Field(min_length=1, description="Roles permitted to read it.")
    content: str = Field(min_length=1)

    @model_validator(mode="after")
    def _expiry_after_effective(self) -> PolicyDocument:
        if self.expiry_date is not None and self.expiry_date < self.effective_date:
            raise ValueError("expiry_date must not precede effective_date")
        return self

    def is_effective_on(self, on: date) -> bool:
        return self.effective_date <= on and (self.expiry_date is None or on <= self.expiry_date)
