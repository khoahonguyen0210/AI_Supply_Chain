"""Hybrid retrieval: vector + lexical scoring -> metadata filtering -> rule-based reranking.

Filtering and ranking follow the document lifecycle rules:

* Role permission is a hard filter. A chunk the asking role may not read is never returned; the
  result only counts how many restricted chunks would have ranked among the top hits, so the answer
  layer can say access is restricted without disclosing content.
* Validity is a soft signal. Expired, superseded and not-yet-effective documents stay retrievable
  (an expired contract must still be citable, with a qualification) but are labelled and ranked
  below current ones.
* A supplier named in the question boosts that supplier's chunks and demotes other suppliers' and
  company-wide chunks (the question is about that supplier's own terms).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

import numpy as np

from .chunking import Chunk
from .embedding import Embedder
from .store import KnowledgeStore

_WORD = re.compile(r"[a-z0-9%]+")
_SUPPLIER_ID = re.compile(r"\bSUP-\d+\b", re.IGNORECASE)
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "we",
        "what",
        "when",
        "which",
        "who",
        "with",
        "within",
    ]
)

_QUESTION_WORDS = frozenset(
    [
        "about",
        "also",
        "any",
        "could",
        "many",
        "may",
        "much",
        "must",
        "our",
        "should",
        "there",
        "their",
        "would",
        "you",
        "your",
    ]
)
_IRREGULAR = {"paid": "pay", "pays": "pay", "paying": "pay"}

VECTOR_WEIGHT = 0.5
LEXICAL_WEIGHT = 0.5
SUPPLIER_MATCH_BONUS = 0.35
SUPPLIER_MISMATCH_PENALTY = 0.25
GENERIC_DOCUMENT_PENALTY = 0.15
TOP_K = 5
RESTRICTED_PROBE_K = 5
# Calibrated on the fixed evaluation set: answerable questions score >= 0.6 on their best chunk and
# questions the corpus cannot answer score <= 0.5 (docs/knowledge-retrieval.md).
MIN_COVERAGE = 0.55


class ValidityStatus(StrEnum):
    CURRENT = "CURRENT"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    NOT_YET_EFFECTIVE = "NOT_YET_EFFECTIVE"


STATUS_PENALTY = {
    ValidityStatus.CURRENT: 0.0,
    ValidityStatus.EXPIRED: 0.15,
    ValidityStatus.SUPERSEDED: 0.30,
    ValidityStatus.NOT_YET_EFFECTIVE: 0.30,
}


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    status: ValidityStatus
    vector_score: float
    lexical_score: float
    coverage: float
    score: float


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    role: str
    as_of: date
    hits: tuple[RetrievedChunk, ...]
    restricted_hits: int


def tokenize(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOPWORDS]


def stem(token: str) -> str:
    """Crude suffix stripping so "quarterly"/"quarter" and "pays"/"paid" meet; not a stemmer."""
    if token in _IRREGULAR:
        return _IRREGULAR[token]
    for suffix in ("ly", "ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            token = token[: -len(suffix)]
            break
    return token[:-1] if len(token) > 4 and token.endswith("e") else token


def informative_terms(text: str) -> frozenset[str]:
    """Stemmed content words, without stopwords, question filler and one-letter tokens."""
    return frozenset(stem(t) for t in tokenize(text) if t not in _QUESTION_WORDS and len(t) > 1)


def term_coverage(topic_terms: frozenset[str], chunk_terms: frozenset[str]) -> float:
    """Share of the question's content terms found in the chunk (1.0 for an empty question)."""
    if not topic_terms:
        return 1.0
    return len(topic_terms & chunk_terms) / len(topic_terms)


def _minmax(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    low, high = float(values.min()), float(values.max())
    if high - low < 1e-12:
        return np.zeros_like(values) if high <= 0 else np.ones_like(values)
    return (values - low) / (high - low)


class Bm25Index:
    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self._k1, self._b = k1, b
        self._tf = [Counter(tokenize(t)) for t in texts]
        self._len = np.array([sum(tf.values()) for tf in self._tf], dtype=np.float64)
        self._avg = float(self._len.mean()) if len(texts) else 0.0
        document_frequency: Counter[str] = Counter()
        for tf in self._tf:
            document_frequency.update(tf.keys())
        n = len(texts)
        self._idf = {
            term: math.log(1 + (n - df + 0.5) / (df + 0.5))
            for term, df in document_frequency.items()
        }

    def scores(self, query: str) -> np.ndarray:
        terms = set(tokenize(query))
        out = np.zeros(len(self._tf), dtype=np.float64)
        for i, tf in enumerate(self._tf):
            norm = self._k1 * (1 - self._b + self._b * self._len[i] / (self._avg or 1.0))
            for term in terms & tf.keys():
                out[i] += self._idf[term] * tf[term] * (self._k1 + 1) / (tf[term] + norm)
        return out


class Retriever:
    def __init__(self, store: KnowledgeStore, embedder: Embedder) -> None:
        self._store, self._embedder = store, embedder
        self._chunks = store.chunks
        self._vectors = store.vectors
        self._bm25 = Bm25Index([c.body for c in self._chunks])
        self._chunk_terms = [informative_terms(c.content) for c in self._chunks]
        self._supplier_names = self._names_by_supplier()

    @property
    def store(self) -> KnowledgeStore:
        return self._store

    def _names_by_supplier(self) -> dict[str, str]:
        names: dict[str, str] = {}
        for document in self._store.documents:
            if document.supplier_id and " - " in document.title:
                names.setdefault(document.supplier_id, document.title.split(" - ", 1)[1].lower())
        return names

    def mentioned_suppliers(self, query: str) -> frozenset[str]:
        found = {m.upper() for m in _SUPPLIER_ID.findall(query)}
        lowered = query.lower()
        found |= {sid for sid, name in self._supplier_names.items() if name in lowered}
        return frozenset(found)

    def topic_of(self, query: str) -> str:
        """The query text that is scored, without supplier mentions."""
        return self.topic(query, self.mentioned_suppliers(query))

    def topic(self, query: str, suppliers: frozenset[str]) -> str:
        """The query without supplier mentions: suppliers are matched on metadata, not text."""
        topic = _SUPPLIER_ID.sub(" ", query)
        for supplier_id in suppliers:
            name = self._supplier_names.get(supplier_id)
            if name:
                topic = re.sub(re.escape(name), " ", topic, flags=re.IGNORECASE)
        topic = re.sub(r"\(\s*\)", " ", topic)
        return " ".join(topic.split()) or query

    def status_of(self, chunk: Chunk, as_of: date) -> ValidityStatus:
        document = self._store.document(chunk.document_id, chunk.document_version)
        if document.is_effective_on(as_of):
            return ValidityStatus.CURRENT
        if document.effective_date > as_of:
            return ValidityStatus.NOT_YET_EFFECTIVE
        newer_in_force = any(
            d.document_id == document.document_id
            and d.version != document.version
            and d.is_effective_on(as_of)
            for d in self._store.documents
        )
        return ValidityStatus.SUPERSEDED if newer_in_force else ValidityStatus.EXPIRED

    def retrieve(self, query: str, *, role: str, as_of: date, k: int = TOP_K) -> RetrievalResult:
        if not self._chunks:
            return RetrievalResult(query, role, as_of, (), 0)
        suppliers = self.mentioned_suppliers(query)
        topic = self.topic(query, suppliers)
        vector = (self._vectors @ self._embedder.embed_query(topic)[0]).astype(np.float64)
        lexical = self._bm25.scores(topic)
        topic_terms = informative_terms(topic)
        coverage = np.array([term_coverage(topic_terms, t) for t in self._chunk_terms])

        allowed = np.array([role in c.metadata["allowed_roles"] for c in self._chunks])
        base = VECTOR_WEIGHT * _minmax(vector) + LEXICAL_WEIGHT * _minmax(lexical)
        final = base.copy()
        statuses: list[ValidityStatus] = []
        by_document: dict[tuple[str, str], ValidityStatus] = {}
        for i, chunk in enumerate(self._chunks):
            key = (chunk.document_id, chunk.document_version)
            if key not in by_document:
                by_document[key] = self.status_of(chunk, as_of)
            status = by_document[key]
            statuses.append(status)
            final[i] -= STATUS_PENALTY[status]
            owner = chunk.metadata["supplier_id"]
            if suppliers:
                if owner is None:
                    final[i] -= GENERIC_DOCUMENT_PENALTY
                elif owner in suppliers:
                    final[i] += SUPPLIER_MATCH_BONUS
                else:
                    final[i] -= SUPPLIER_MISMATCH_PENALTY

        order = np.argsort(-final, kind="stable")
        permitted = [int(i) for i in order if allowed[i]]
        hits = tuple(
            RetrievedChunk(
                chunk=self._chunks[i],
                status=statuses[i],
                vector_score=float(vector[i]),
                lexical_score=float(lexical[i]),
                coverage=float(coverage[i]),
                score=float(final[i]),
            )
            for i in permitted[:k]
        )
        restricted = sum(
            1 for i in order[:RESTRICTED_PROBE_K] if not allowed[i] and coverage[i] >= MIN_COVERAGE
        )
        return RetrievalResult(query, role, as_of, hits, restricted)
