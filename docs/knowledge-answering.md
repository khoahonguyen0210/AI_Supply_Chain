# Grounded answering

Code: `ml/src/scm_ml/knowledge/answering.py`, `ml/src/scm_ml/llm/`. `GroundedAnswerer(retriever, generator).answer(question,
role=, as_of=)` returns a `GroundedAnswer`: status, text safe to show, caveats, citations and (when a draft was
rejected) the violations.

The model only drafts text from numbered sources. Whether the answer may be shown is decided by code.

## Flow

1. Retrieve (see knowledge-retrieval.md). Keep hits whose term coverage is at least `MIN_COVERAGE`; they become sources
   `S1..Sn`.
2. **No relevant source** -> refuse without calling the generator. `RESTRICTED` if a relevant chunk was withheld by the
   role filter, otherwise `INSUFFICIENT_EVIDENCE`.
3. **Conflict rule.** Two CURRENT sources from different documents conflict when the question names a distinctive
   title term of each (so a regional addendum only counts when the question is about that region), they share at least
   three content terms, and a money/percent/duration quantity of the same kind differs. Both clauses are quoted
   verbatim as `CONFLICT`; the model does not pick a winner.
4. Generate a draft (`answer`, `cited_sources`, `sufficient`). A draft is rejected as `INSUFFICIENT_EVIDENCE` when it is
   empty, cites nothing, cites an unknown source, or states a number that is in none of its cited sources.
5. Append qualifications in code: expired (with the expiry date), superseded, not yet effective, and "some related
   documents are restricted". Any non-CURRENT cited source makes the status `QUALIFIED`.

| Status | Meaning |
|---|---|
| `ANSWERED` | supported by CURRENT sources |
| `QUALIFIED` | supported, but a cited source is expired, superseded or not yet effective |
| `CONFLICT` | in-force documents disagree; both quoted |
| `RESTRICTED` | the evidence exists but the role may not read it; nothing is disclosed |
| `INSUFFICIENT_EVIDENCE` | no relevant evidence, or the draft failed the grounding checks |

## Generators

| Generator | Use |
|---|---|
| `ExtractiveGenerator` | deterministic offline stub: quotes the best-matching clause of the best CURRENT source. Used by tests and CI. |
| `ClaudeGenerator(ClaudeJsonLlm())` | Claude drafts the answer with a JSON-schema constrained response |

`ClaudeJsonLlm` (`ml/src/scm_ml/llm/claude.py`) uses the Anthropic SDK with model `claude-opus-5-5`, adaptive thinking
(the default), `effort=medium` and structured outputs. Credentials come from `ANTHROPIC_API_KEY`. A refusal,
truncation or API error raises `LlmError`, which the answerer turns into `INSUFFICIENT_EVIDENCE`. No test calls the
API; the client is exercised with a fake. Claude-generated answer quality is `NOT YET MEASURED`.

## Limits

* The evidence gate is lexical, so a heavily paraphrased question can be refused (FACT-033: "defect rate" vs
  "defective"). The real embedder's similarity scores overlapped too much between answerable and unanswerable
  questions to use as a gate.
* The numeric check proves numbers come from cited sources, not that they answer the question.
