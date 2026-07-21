from __future__ import annotations

import argparse
from pathlib import Path

from scm_ml.synthetic import SyntheticConfig, generate_world

from .answering import ExtractiveGenerator, GroundedAnswerer
from .corpus import build_corpus
from .embedding import EMBEDDING_DIM, Embedder, FastEmbedEmbedder, HashingEmbedder
from .evaluation import EXPERIMENT_DIR, run_evaluation
from .retrieval import Retriever
from .store import KnowledgeStore, ingest

EMBEDDERS = {"hashing": HashingEmbedder, "fastembed": FastEmbedEmbedder}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval and grounded answering.")
    parser.add_argument("--embedder", choices=sorted(EMBEDDERS), default="fastembed")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    corpus = build_corpus(generate_world(SyntheticConfig()))
    embedder: Embedder = EMBEDDERS[args.embedder]()
    store = KnowledgeStore(EMBEDDING_DIM)
    ingest(corpus.documents, embedder, store)
    retriever = Retriever(store, embedder)
    out = args.out or EXPERIMENT_DIR / f"synthetic-{args.embedder}.json"
    result = run_evaluation(
        corpus,
        retriever,
        GroundedAnswerer(retriever, ExtractiveGenerator()),
        out,
        embedder=embedder.name,
    )
    r, a = result["retrieval"], result["answers"]
    print(f"embedder {embedder.name}  cases {result['cases']}")
    print(
        f"retrieval  hit@1 {r['hit@1']:.3f}  hit@3 {r['hit@3']:.3f}  hit@5 {r['hit@5']:.3f}"
        f"  mrr {r['mrr']:.3f}"
    )
    print(
        f"answers    status {a['status_accuracy']:.3f}  accuracy {a['answer_accuracy']:.3f}"
        f"  wrong {a['wrong_answer_rate']:.3f}  over-refusal {a['over_refusal_rate']:.3f}"
    )
    print(
        f"grounding  citation {a['citation_accuracy']:.3f}  groundedness {a['groundedness']:.3f}"
        f"  leaks {a['restricted_leaks']}"
    )
    for row in result["failures"]:
        print(
            f"  FAIL {row['case_id']} {row['category']}: {row['status']}"
            f" (expected {row['expected_status']})"
        )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
