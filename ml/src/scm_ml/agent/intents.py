from __future__ import annotations

import re
from dataclasses import dataclass

from scm_ml.knowledge.embedding import Embedder

# Several wordings per intent, ids and numbers generic, so new phrasings match by meaning.
EXAMPLES: dict[str, tuple[str, ...]] = {
    "FORECAST": (
        "what is the demand forecast for the product",
        "how much of the product will we sell in the next weeks",
        "what sales do we expect for the product next month",
        "projected demand for the product",
        "how many units of the product are customers likely to buy",
        "what is the sales outlook for the product",
        "predict upcoming sales of the product",
        "what volume of the product do we expect to sell",
        "expected customer orders for the product over the coming weeks",
        "give me the demand projection for the product",
    ),
    "INVENTORY": (
        "how much of the product do we have in stock",
        "current inventory level of the product",
        "stock on hand for the product",
        "how many units of the product are in our warehouses",
        "do we have enough of the product to cover demand",
        "are we going to run out of the product",
        "is the product running low",
        "what is our stock position for the product",
        "check inventory for the product",
        "how long will our stock of the product last",
    ),
    "SOURCING": (
        "which suppliers can provide the product",
        "list the vendors for the product",
        "who sells us the product",
        "find a supplier that can ship the product to the warehouse",
        "compare suppliers for the product",
        "best source for some units of the product",
        "who can deliver the product quickly",
        "supplier options for the product",
        "where can we buy the product from",
        "alternative vendors for the product",
    ),
    "PERFORMANCE": (
        "how reliable is the supplier",
        "is the supplier dependable",
        "what is the on-time delivery record of the supplier",
        "how has the supplier performed recently",
        "can we trust the supplier to deliver on time",
        "track record of the supplier",
        "is the supplier good at delivering",
        "delivery performance of the supplier",
    ),
    "PLAN": (
        "what should we order for the product",
        "how much of the product should we buy",
        "prepare a purchase plan for the product",
        "we need to restock the product",
        "demand for the product is growing, what should we purchase",
        "sales of the product are up, should we buy more",
        "work out an order for the product",
        "replenish the product",
        "customers want more of the product, plan our purchases",
        "build a purchase order for the product",
    ),
    "SCENARIO": (
        "what happens if the supplier stops delivering",
        "how would a delivery delay affect the product",
        "what is the impact of higher shipping costs on the product",
        "what if purchase prices go up",
        "suppose demand for the product falls",
        "stress test the plan for the product",
        "how would losing the supplier hit the product",
        "what if suppliers can only deliver part of their usual volume",
        "impact of less warehouse space on the product",
        "freight gets more expensive, what does it mean for the product",
    ),
    "POLICY": (
        "what are the payment terms in the contract",
        "who needs to approve a large purchase order",
        "when does the contract with the supplier expire",
        "what does the procurement policy say",
        "is there a limit on order value",
        "what certifications does the supplier hold",
        "what is the penalty for late delivery in the service level agreement",
        "what are the rebate terms with the supplier",
        "what lead time has the supplier committed to",
    ),
}

MIN_SIMILARITY = 0.6  # below this the request is not like any example
MIN_MARGIN = 0.02  # best intent must beat the runner-up by this much


def generic(text: str, supplier_names: tuple[str, ...] = ()) -> str:
    """Replace ids, names and numbers so only the wording is compared."""
    text = text.lower()
    text = re.sub(r"\bsku[-\s]?\d+\b", "the product", text)
    text = re.sub(r"\bsup[-\s]?\d+\b", "the supplier", text)
    for name in supplier_names:
        text = text.replace(name.lower(), "the supplier")
    text = re.sub(r"\bwh[-\s]?\d+\b", "the warehouse", text)
    return re.sub(r"\d[\d,.]*\s*%?", "some", text)


@dataclass(frozen=True)
class Match:
    intent: str
    similarity: float
    margin: float


class IntentMatcher:
    def __init__(self, embedder: Embedder, supplier_names: tuple[str, ...] = ()) -> None:
        self._embedder = embedder
        self._names = supplier_names
        self._labels = [intent for intent, texts in EXAMPLES.items() for _ in texts]
        self._vectors = embedder.embed_documents(
            [text for texts in EXAMPLES.values() for text in texts]
        )

    def match(self, text: str) -> Match | None:
        query = self._embedder.embed_query(generic(text, self._names))[0]
        scores = self._vectors @ query
        best: dict[str, float] = {}
        for label, score in zip(self._labels, scores, strict=True):
            best[label] = max(best.get(label, -1.0), float(score))
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        (intent, top), (_, second) = ranked[0], ranked[1]
        if top < MIN_SIMILARITY or top - second < MIN_MARGIN:
            return None
        return Match(intent, top, top - second)
