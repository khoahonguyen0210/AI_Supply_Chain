# Knowledge corpus

Code: `ml/src/scm_ml/knowledge/corpus.py`. Entry point: `build_corpus(world) -> Corpus`. The same world always
gives the same corpus (`CORPUS_VERSION = "1"`).

Text is generated from the synthetic world, so it agrees with the structured master data (payment terms,
order limits, contract status, certifications). Every document is a `PolicyDocument` with `version`,
`effective_date`, optional `expiry_date`, optional `supplier_id` and an `allowed_roles` list.

## Documents (default world: 69)

| Type | Id pattern | Notes |
|---|---|---|
| CONTRACT | `CTR-<supplier>` | master supply agreement per supplier; one is expired |
| CONTRACT | `NTC-<supplier>` | suspension notice for each suspended supplier |
| CONTRACT | `PRC-<supplier>` | confidential rebate agreement, finance and admin only |
| SLA | `SLA-<supplier>` | on-time-in-full target and committed lead time; one supplier has a superseded v1 |
| SHIPPING_TERMS | `SHP-<supplier>` | incoterm, freight payer, damage-claim window |
| CERTIFICATION | `CERT-<supplier>-<cert>` | validity window per certificate |
| POLICY | `POL-*` | approval (v1 superseded by v2), regional addendum, sourcing, budget (restricted), warehouse |
| SOP | `SOP-*` | stockout, supplier outage, receiving, safety stock |
| SPECIFICATION | `SPEC-<category>` | certification, storage, packaging, shelf life per product category |

## Ground truth

Each fact the generator writes is recorded as a `GroundTruth`: question, asking role, `Expectation`, expected
answer, source document and version, an optional `forbidden_answer` (a stale or restricted value that must not
be asserted) and, for conflicts, the other documents involved.

| Expectation | Case | Facts |
|---|---|---|
| `ANSWER` | normal question, including the current value where an older version exists | 32 |
| `QUALIFY_EXPIRED` | the answer comes from an expired contract and must say so | 1 |
| `FLAG_CONFLICT` | regional addendum vs company approval policy, both in effect | 1 |
| `DENY` | restricted document, asking role not permitted | 2 |

Missing-evidence questions have no source document by definition, so they are added with the evaluation set
(Task 7.5), not here.

Tests: `ml/tests/test_knowledge_corpus.py` check that expected answers appear in their source text, forbidden
values do not, superseded versions are expired, conflicting documents are both in effect and restricted
documents exclude the asking role.
