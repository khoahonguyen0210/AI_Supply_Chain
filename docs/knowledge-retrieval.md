# Knowledge retrieval

Code: `ml/src/scm_ml/knowledge/retrieval.py`. `Retriever(store, embedder).retrieve(query, role=, as_of=, k=5)` returns a
`RetrievalResult` with ranked `RetrievedChunk`s (chunk, validity status, vector score, lexical score, final score)
and a `restricted_hits` count.

## Pipeline

1. **Supplier detection.** Supplier ids (`SUP-002`) and supplier names taken from contract/SLA titles
   ("Supplier B") are recognised in the question and removed from the text that gets scored. Suppliers are matched on
   chunk metadata, not on text, so "Supplier B" cannot pull in every document that merely says "Supplier".
2. **Hybrid score.** Cosine similarity of the query embedding against chunk vectors and BM25 over the clause body
   (without the title/preamble prefix) are each min-max normalised and averaged 50/50.
3. **Rule-based rerank.** Subtract a validity penalty, then adjust for the named supplier.
4. **Role filter.** Chunks whose `allowed_roles` exclude the asking role are dropped last, after ranking.

## Rules

| Signal | Effect |
|---|---|
| Role not permitted | Hard filter: never returned. `restricted_hits` counts how many of the top 5 ranked chunks that are also relevant (coverage >= `MIN_COVERAGE`) were withheld, so the answer layer can say access is restricted without disclosing content. |
| Expired | -0.15, still returned and labelled `EXPIRED` (an expired contract must stay citable, with a qualification) |
| Superseded (a newer version is in force) | -0.30, labelled `SUPERSEDED` |
| Not yet effective | -0.30, labelled `NOT_YET_EFFECTIVE` |
| Chunk of a named supplier | +0.35 |
| Chunk of another supplier | excluded (never evidence about the named supplier) |
| Company-wide chunk when a supplier is named | -0.15 |

Validity is evaluated against the `as_of` date, not today's date, so the same store answers historical questions.

The company-wide penalty exists because generic chunks can win on lexical score alone: "All other terms follow the
Company approval policy" outranked Supplier B's payment clause for "payment terms for Supplier B" until it was added.

## Relevance signal

Each hit carries `coverage`: the share of the question's content terms (stemmed, minus stopwords and filler such as
"many"/"must") found in the chunk, supplier mentions excluded. The answer layer treats a hit below `MIN_COVERAGE`
(0.55) as no evidence. The threshold sits between the two groups in the fixed evaluation set: answerable questions
score at least 0.6 on their best chunk (one paraphrased question scores 0.33) and the unanswerable ones at most 0.5.
The margin is thin and was chosen on that set.

## Verification

`ml/tests/test_knowledge_retrieval.py` runs against the synthetic corpus with the offline hashing embedder: the
source document is in the top 5 for every answerable fact, restricted chunks never reach other roles, the current
version outranks the superseded one, expired and not-yet-effective documents are labelled, and a named supplier's
documents lead the results. These tests check the pipeline's behaviour. Retrieval quality with the real embedding
model is part of Task 7.5 and is `NOT YET MEASURED`.
