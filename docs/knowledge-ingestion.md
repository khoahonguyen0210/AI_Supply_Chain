# Knowledge ingestion

Code: `ml/src/scm_ml/knowledge/{chunking,embedding,store}.py`. Pipeline: document load -> parse -> chunk -> embed
-> store, run by `ingest(documents, embedder, store) -> IngestReport`.

## Parse and chunk

`parse_document` splits a document into a preamble and its numbered clauses. Multi-line documents are split at
line-start `N.` markers; single-paragraph SOPs are split at inline `N. Capital` markers; text with neither is one
clause.

`chunk_document` emits one chunk per clause, each prefixed with the document title and preamble. The prefix keeps
the supplier name attached to a clause such as "Invoices are payable within 30 days" once it is retrieved alone.
A clause longer than the token budget (120 whitespace tokens including the prefix) is split into overlapping
windows (20 tokens). Chunk metadata is what retrieval filters on: `doc_type`, `title`, `supplier_id`,
`effective_date`, `expiry_date`, `allowed_roles`.

## Embedding

| Embedder | Use |
|---|---|
| `FastEmbedEmbedder` | `BAAI/bge-small-en-v1.5` via fastembed (ONNX, 384-dim, L2-normalised), queries use the model's query prefix |
| `HashingEmbedder` | deterministic offline stand-in (signed hashed unigrams and bigrams) for tests and CI; lexical only |

Both are 384-dim, matching `knowledge_chunk.embedding vector(384)`. Retrieval quality is only ever reported for the
real model; the hashing embedder exists so the pipeline can be tested without a model download.

## Store

`KnowledgeStore` mirrors the `knowledge_document` and `knowledge_chunk` tables: a SHA-256 of each document version's
content, and chunks with embedding and metadata. Ingestion is idempotent. An unchanged `(document_id, version)` is
skipped, changed content replaces that version's chunks, and a wrong embedding shape or dimension is rejected.
Writing the same records to PostgreSQL is the backend's job (Phase 9).
