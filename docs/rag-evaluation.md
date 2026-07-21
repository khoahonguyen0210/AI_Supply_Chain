# RAG evaluation

Code: `ml/src/scm_ml/knowledge/evaluation.py`. Run: `uv run python -m scm_ml.knowledge --embedder fastembed|hashing`.
Artifacts: `ml/experiments/rag/synthetic-{fastembed,hashing}.json` (configuration, per-category and per-case results,
failures, provenance). Every figure below is read from those files.

## Fixed evaluation set (56 cases)

| Category | Cases | Expected behaviour |
|---|---|---|
| normal | 29 | answered, correct value, correct source cited |
| superseded | 3 | answered with the current value; the stale value must not appear |
| expired | 1 | answered and qualified as expired |
| conflict | 1 | both in-force documents reported, none chosen |
| restricted | 2 | refused as restricted, nothing disclosed |
| missing | 20 | refused as insufficient evidence |

Missing-evidence questions are split into 12 `calibration` questions (used while choosing the evidence-gate
threshold) and 8 `holdout` questions written afterwards. The conflict and expired categories have one case each, so
their rates are 0 or 1 and prove the path works, not that it is reliable.

## Metrics

Retrieval is scored on the 34 questions that have evidence (hit@k: every gold document version is in the top k; a
conflict case needs both documents). Answer metrics use the offline `ExtractiveGenerator`, so they measure retrieval,
the evidence gate and the grounding checks. They are not a measure of Claude-written answers: **LLM generator metrics:
NOT YET MEASURED** (needs `ANTHROPIC_API_KEY`).

| Metric | bge-small (fastembed) | hashing (offline) |
|---|---|---|
| hit@1 | 0.941 | 0.824 |
| hit@3 | 1.000 | 1.000 |
| hit@5 | 1.000 | 1.000 |
| MRR | 0.971 | 0.907 |
| status accuracy (all 56) | 0.982 | 0.982 |
| answer accuracy (34 with evidence) | 0.971 | 0.971 |
| over-refusal rate | 0.029 | 0.029 |
| wrong-answer rate (of answers given) | 0.000 | 0.000 |
| citation accuracy | 1.000 | 1.000 |
| groundedness (numbers in cited text) | 1.000 | 1.000 |
| restricted-document leaks | 0 | 0 |
| missing-evidence refusal, calibration / holdout | 1.000 / 1.000 | 1.000 / 1.000 |

The only failure is FACT-033 ("Above what defect rate is a delivered lot quarantined?"): the source says "more than 2%
of sampled units are defective", the lexical evidence gate scores it 0.33 and refuses. It is reported, not hidden.

## Reading the numbers

* Groundedness and citation accuracy are 1.0 largely by construction for the extractive stub, which quotes a source.
  They become informative with an LLM generator, where the same checks can reject drafts.
* The evidence gate was calibrated on the 12 calibration questions plus the answerable facts; the holdout result is the
  less biased estimate, and 8 questions is a small sample.
* The corpus is synthetic and template-generated, so phrasing is far more regular than real contracts.
