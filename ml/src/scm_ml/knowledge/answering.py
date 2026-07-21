"""Grounded answers: retrieval -> evidence gate -> generation -> deterministic grounding checks.

The language model only drafts the answer text from numbered sources. Everything that decides
whether the answer may be shown is plain code:

* No relevant evidence -> refuse (or say access is restricted); the model is never called.
* Two in-force documents that the question points at give different values -> report both verbatim
  as a conflict instead of letting the model pick one.
* A draft is accepted only if it cites provided sources and every number in it appears in a cited
  source. Anything else becomes "insufficient evidence" rather than an unsupported answer.
* Qualifications (expired, superseded, not yet effective, restricted material exists) are appended
  by code, so a generator cannot omit them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field

from scm_common.domain import DomainModel
from scm_ml.llm import JsonLlm, LlmError

from .retrieval import (
    MIN_COVERAGE,
    RetrievalResult,
    RetrievedChunk,
    Retriever,
    ValidityStatus,
    informative_terms,
)

_CLAUSE_NUMBER = re.compile(r"^\s*\d+\.\s*")
_MARKER = re.compile(r"\[S\d+\]")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_VALUE = re.compile(
    r"(?P<usd>USD\s*)?(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>%|days?|business hours|hours?)?",
    re.IGNORECASE,
)
MIN_SHARED_TERMS = 3
NO_EVIDENCE_TEXT = "The knowledge base does not contain evidence to answer this question."
RESTRICTED_TEXT = (
    "The documents that would answer this question are restricted for your role. "
    "Ask a colleague with access."
)
UNSUPPORTED_TEXT = "A supported answer could not be produced from the available evidence."


class AnswerStatus(StrEnum):
    ANSWERED = "ANSWERED"
    QUALIFIED = "QUALIFIED"
    CONFLICT = "CONFLICT"
    RESTRICTED = "RESTRICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class Source:
    source_id: str
    hit: RetrievedChunk

    @property
    def document_id(self) -> str:
        return self.hit.chunk.document_id

    @property
    def version(self) -> str:
        return self.hit.chunk.document_version

    @property
    def status(self) -> ValidityStatus:
        return self.hit.status

    @property
    def clause(self) -> str:
        return _CLAUSE_NUMBER.sub("", self.hit.chunk.body).strip()


@dataclass(frozen=True)
class Draft:
    answer: str
    cited_source_ids: tuple[str, ...]
    sufficient: bool = True


class AnswerGenerator(Protocol):
    name: str

    def generate(self, question: str, sources: Sequence[Source]) -> Draft: ...


class Citation(DomainModel):
    source_id: str
    document_id: str
    version: str
    chunk_index: int = Field(ge=0)
    status: ValidityStatus
    excerpt: str = Field(description="The cited clause.")
    text: str = Field(description="The cited chunk including its title and preamble.")


class GroundedAnswer(DomainModel):
    question: str
    role: str
    as_of: date
    status: AnswerStatus
    text: str = Field(description="Answer with qualifications appended; safe to show.")
    body: str = Field(description="The answer without appended qualifications.")
    caveats: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()
    generator: str
    violations: tuple[str, ...] = Field(
        default=(), description="Why a draft was rejected; empty when accepted."
    )


class ExtractiveGenerator:
    """Deterministic offline generator: quotes the best-matching clause of the best source."""

    name = "extractive-stub"

    def generate(self, question: str, sources: Sequence[Source]) -> Draft:
        if not sources:
            return Draft("", (), sufficient=False)
        best = max(sources, key=lambda s: (s.status == ValidityStatus.CURRENT, s.hit.coverage))
        return Draft(f"{best.clause} [{best.source_id}]", (best.source_id,))


_SYSTEM_PROMPT = """\
You answer questions about a company's supply-chain contracts, policies, SOPs and specifications \
using ONLY the numbered sources in the user message.

Rules:
- Answer in one or two sentences. Cite the source ids you rely on, e.g. [S1].
- Never state a number, date or party that is not in a source you cite.
- Prefer sources with status CURRENT. Sources marked EXPIRED, SUPERSEDED or NOT_YET_EFFECTIVE are \
shown for reference; if you rely on one, cite it (the system adds the qualification itself).
- If the sources do not contain the answer, set sufficient to false and leave answer empty. Do not \
guess and do not use outside knowledge.
"""
_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "cited_sources": {"type": "array", "items": {"type": "string"}},
        "sufficient": {"type": "boolean"},
    },
    "required": ["answer", "cited_sources", "sufficient"],
    "additionalProperties": False,
}


class ClaudeGenerator:
    """Drafts the answer with an LLM behind the `JsonLlm` protocol (Claude in production)."""

    def __init__(self, llm: JsonLlm) -> None:
        self._llm = llm
        self.name = llm.name

    def generate(self, question: str, sources: Sequence[Source]) -> Draft:
        blocks = [
            f'<source id="{s.source_id}" document="{s.document_id}" version="{s.version}" '
            f'status="{s.status.value}">\n{s.hit.chunk.content}\n</source>'
            for s in sources
        ]
        user = "\n".join(blocks) + f"\n\nQuestion: {question}"
        raw = self._llm.complete_json(
            system=_SYSTEM_PROMPT, user=user, schema=_DRAFT_SCHEMA, max_tokens=1024
        )
        return Draft(
            answer=str(raw["answer"]).strip(),
            cited_source_ids=tuple(str(i) for i in raw["cited_sources"]),
            sufficient=bool(raw["sufficient"]),
        )


def _numbers(text: str) -> set[str]:
    return {m.replace(",", "").rstrip(".") for m in _NUMBER.findall(text)}


def unsupported_text_numbers(answer: str, evidence: str) -> set[str]:
    """Numbers stated in the answer (citation markers aside) that do not appear in the evidence."""
    return _numbers(_MARKER.sub(" ", answer)) - _numbers(evidence)


def unsupported_numbers(answer: str, cited: Sequence[Source]) -> set[str]:
    """Numbers stated in the answer that appear in none of the cited sources."""
    return unsupported_text_numbers(answer, " ".join(s.hit.chunk.content for s in cited))


def _quantities(clause: str) -> dict[str, set[str]]:
    """Money, percentages and durations in a clause, keyed by kind."""
    found: dict[str, set[str]] = {}
    for m in _VALUE.finditer(clause):
        kind = "usd" if m.group("usd") else (m.group("unit") or "").lower().rstrip("s")
        if kind:
            found.setdefault(kind, set()).add(m.group("num").replace(",", ""))
    return found


def _disagree(a: Source, b: Source) -> bool:
    qa, qb = _quantities(a.clause), _quantities(b.clause)
    shared = qa.keys() & qb.keys()
    return any(qa[kind].isdisjoint(qb[kind]) for kind in shared)


class GroundedAnswerer:
    def __init__(self, retriever: Retriever, generator: AnswerGenerator, *, k: int = 5) -> None:
        self._retriever, self._generator, self._k = retriever, generator, k
        self._title_terms = self._distinctive_title_terms()

    @property
    def generator_name(self) -> str:
        return self._generator.name

    def _distinctive_title_terms(self) -> dict[str, frozenset[str]]:
        """Title terms that identify one document id among all documents."""
        titles: dict[str, frozenset[str]] = {}
        for document in self._retriever.store.documents:
            titles[document.document_id] = informative_terms(document.title)
        out: dict[str, frozenset[str]] = {}
        for document_id, terms in titles.items():
            others = frozenset().union(*(t for i, t in titles.items() if i != document_id))
            out[document_id] = terms - others
        return out

    def answer(self, question: str, *, role: str, as_of: date) -> GroundedAnswer:
        result = self._retriever.retrieve(question, role=role, as_of=as_of, k=self._k)
        relevant = [h for h in result.hits if h.coverage >= MIN_COVERAGE]
        sources = [Source(f"S{i}", h) for i, h in enumerate(relevant, start=1)]
        if not sources:
            return self._refusal(question, role, as_of, result)

        conflict = self._conflict(question, sources)
        if conflict:
            return self._conflict_answer(question, role, as_of, result, conflict)

        try:
            draft = self._generator.generate(question, sources)
        except LlmError as error:
            return self._rejected(question, role, as_of, f"generator failed: {error}")
        if not draft.sufficient:
            return self._refusal(question, role, as_of, result)
        by_id = {s.source_id: s for s in sources}
        violations = self._violations(draft, by_id)
        if violations:
            return self._rejected(question, role, as_of, *violations)

        cited = [by_id[i] for i in dict.fromkeys(draft.cited_source_ids)]
        caveats = self._caveats(cited, result)
        status = (
            AnswerStatus.QUALIFIED
            if any(s.status != ValidityStatus.CURRENT for s in cited)
            else AnswerStatus.ANSWERED
        )
        return GroundedAnswer(
            question=question,
            role=role,
            as_of=as_of,
            status=status,
            text=" ".join([draft.answer, *caveats]),
            body=draft.answer,
            caveats=tuple(caveats),
            citations=tuple(self._citation(s) for s in cited),
            generator=self._generator.name,
        )

    @staticmethod
    def _violations(draft: Draft, by_id: dict[str, Source]) -> list[str]:
        problems: list[str] = []
        if not draft.answer.strip():
            problems.append("empty answer")
        if not draft.cited_source_ids:
            problems.append("no citations")
        unknown = [i for i in draft.cited_source_ids if i not in by_id]
        if unknown:
            problems.append(f"cites unknown sources: {', '.join(unknown)}")
        if not problems:
            extra = unsupported_numbers(draft.answer, [by_id[i] for i in draft.cited_source_ids])
            if extra:
                problems.append(f"numbers not in cited sources: {', '.join(sorted(extra))}")
        return problems

    def _conflict(self, question: str, sources: list[Source]) -> tuple[Source, Source] | None:
        """Two in-force documents the question points at, with different values for one quantity."""
        asked = informative_terms(self._retriever.topic_of(question))
        current = [s for s in sources if s.status == ValidityStatus.CURRENT]
        for i, first in enumerate(current):
            for second in current[i + 1 :]:
                if first.document_id == second.document_id:
                    continue
                both_selected = all(
                    asked & self._title_terms.get(s.document_id, frozenset())
                    for s in (first, second)
                )
                shared = informative_terms(first.clause) & informative_terms(second.clause)
                if both_selected and len(shared) >= MIN_SHARED_TERMS and _disagree(first, second):
                    return first, second
        return None

    def _conflict_answer(
        self,
        question: str,
        role: str,
        as_of: date,
        result: RetrievalResult,
        pair: tuple[Source, Source],
    ) -> GroundedAnswer:
        quotes = " vs ".join(
            f'{s.document_id} v{s.version}: "{s.clause}" [{s.source_id}]' for s in pair
        )
        caveat = "Both documents are in force; confirm with procurement management before acting."
        caveats = [caveat, *self._caveats(list(pair), result, current_only=True)]
        return GroundedAnswer(
            question=question,
            role=role,
            as_of=as_of,
            status=AnswerStatus.CONFLICT,
            text=f"The sources disagree. {quotes}. {caveat}",
            body=f"The sources disagree. {quotes}.",
            caveats=tuple(caveats),
            citations=tuple(self._citation(s) for s in pair),
            generator="conflict-rule",
        )

    @staticmethod
    def _caveats(
        cited: Sequence[Source], result: RetrievalResult, *, current_only: bool = False
    ) -> list[str]:
        notes: list[str] = []
        for s in cited:
            document = s.hit.chunk.metadata
            label = f"{s.document_id} v{s.version}"
            if s.status == ValidityStatus.EXPIRED:
                notes.append(
                    f"Note: {label} expired on {document['expiry_date']}; this may no longer apply."
                )
            elif s.status == ValidityStatus.SUPERSEDED:
                notes.append(f"Note: {label} has been superseded by a newer version.")
            elif s.status == ValidityStatus.NOT_YET_EFFECTIVE:
                notes.append(f"Note: {label} takes effect on {document['effective_date']}.")
        if result.restricted_hits and not current_only:
            notes.append("Some related documents are restricted for your role.")
        return notes

    @staticmethod
    def _citation(source: Source) -> Citation:
        return Citation(
            source_id=source.source_id,
            document_id=source.document_id,
            version=source.version,
            chunk_index=source.hit.chunk.chunk_index,
            status=source.status,
            excerpt=source.clause,
            text=source.hit.chunk.content,
        )

    def _refusal(
        self, question: str, role: str, as_of: date, result: RetrievalResult
    ) -> GroundedAnswer:
        restricted = result.restricted_hits > 0
        return GroundedAnswer(
            question=question,
            role=role,
            as_of=as_of,
            status=AnswerStatus.RESTRICTED if restricted else AnswerStatus.INSUFFICIENT_EVIDENCE,
            text=RESTRICTED_TEXT if restricted else NO_EVIDENCE_TEXT,
            body=RESTRICTED_TEXT if restricted else NO_EVIDENCE_TEXT,
            generator="evidence-gate",
        )

    def _rejected(self, question: str, role: str, as_of: date, *violations: str) -> GroundedAnswer:
        return GroundedAnswer(
            question=question,
            role=role,
            as_of=as_of,
            status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            text=UNSUPPORTED_TEXT,
            body=UNSUPPORTED_TEXT,
            generator=self._generator.name,
            violations=violations,
        )
