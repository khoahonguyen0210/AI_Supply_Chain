"""Parse a policy document into clauses and chunk it for embedding.

Documents are numbered clauses under a short preamble. Each chunk is one clause (or a window of a
very long clause) prefixed with the document title and preamble, so a clause such as "Invoices are
payable within 30 days" still names the supplier it belongs to once it is retrieved on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import Field

from scm_common.domain import DomainModel, PolicyDocument

MAX_CHUNK_TOKENS = 120
OVERLAP_TOKENS = 20
_CLAUSE_START = re.compile(r"(?m)^\s*\d+\.\s")
_INLINE_CLAUSE = re.compile(r"\s(?=\d+\.\s+[A-Z])")


class Chunk(DomainModel):
    document_id: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    context: str = Field(default="", description="Title and preamble prefix inside `content`.")
    token_count: int = Field(gt=0)
    metadata: dict[str, Any]

    @property
    def body(self) -> str:
        """The clause text without the context prefix."""
        return self.content.removeprefix(self.context).strip()


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    preamble: str
    clauses: tuple[str, ...]


def count_tokens(text: str) -> int:
    return len(text.split())


def parse_document(document: PolicyDocument) -> ParsedDocument:
    """Split content into a preamble and its numbered clauses (single-paragraph SOPs have none)."""
    text = document.content
    starts = [m.start() for m in _CLAUSE_START.finditer(text)]
    if not starts:
        flat = " ".join(text.split())
        pieces = _INLINE_CLAUSE.split(flat)
        if len(pieces) < 2:
            return ParsedDocument(document.title, "", (flat,))
        # "Stockout response. 1. Planners ..." - the first piece is the preamble
        return ParsedDocument(document.title, pieces[0], tuple(p.strip() for p in pieces[1:]))
    preamble = " ".join(text[: starts[0]].split())
    bounds = [*starts, len(text)]
    clauses = tuple(" ".join(text[a:b].split()) for a, b in zip(bounds, bounds[1:], strict=False))
    return ParsedDocument(document.title, preamble, clauses)


def _windows(text: str, size: int, overlap: int) -> list[str]:
    words = text.split()
    if len(words) <= size:
        return [text]
    step = size - overlap
    return [" ".join(words[i : i + size]) for i in range(0, len(words) - overlap, step)]


def chunk_document(
    document: PolicyDocument,
    *,
    max_tokens: int = MAX_CHUNK_TOKENS,
    overlap: int = OVERLAP_TOKENS,
) -> tuple[Chunk, ...]:
    """Chunk one document; metadata carries everything retrieval filters on."""
    parsed = parse_document(document)
    context = " ".join(part for part in (parsed.title + ".", parsed.preamble) if part.strip(". "))
    metadata: dict[str, Any] = {
        "doc_type": document.doc_type.value,
        "title": document.title,
        "supplier_id": document.supplier_id,
        "effective_date": document.effective_date.isoformat(),
        "expiry_date": document.expiry_date.isoformat() if document.expiry_date else None,
        "allowed_roles": list(document.allowed_roles),
    }
    budget = max(max_tokens - count_tokens(context), 20)
    chunks: list[Chunk] = []
    for clause in parsed.clauses:
        for window in _windows(clause, budget, min(overlap, budget // 2)):
            content = f"{context}\n{window}" if context else window
            chunks.append(
                Chunk(
                    document_id=document.document_id,
                    document_version=document.version,
                    chunk_index=len(chunks),
                    content=content,
                    context=context,
                    token_count=count_tokens(content),
                    metadata=metadata,
                )
            )
    return tuple(chunks)
