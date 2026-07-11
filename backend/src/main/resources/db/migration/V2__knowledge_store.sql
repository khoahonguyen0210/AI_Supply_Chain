-- pgvector knowledge store for RAG: documents, chunks, embeddings and filterable metadata.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE knowledge_document (
    document_id    text NOT NULL,
    version        text NOT NULL,
    doc_type       text NOT NULL CHECK (doc_type IN (
        'CONTRACT', 'SLA', 'POLICY', 'SOP', 'CERTIFICATION', 'SPECIFICATION', 'SHIPPING_TERMS')),
    title          text NOT NULL,
    source         text NOT NULL DEFAULT 'synthetic-corpus',
    effective_date date NOT NULL,
    expiry_date    date,
    supplier_id    text REFERENCES supplier (supplier_id),
    allowed_roles  text[] NOT NULL CHECK (cardinality(allowed_roles) > 0),
    content        text NOT NULL,
    content_sha256 char(64) NOT NULL,
    ingested_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, version),
    CHECK (expiry_date IS NULL OR expiry_date >= effective_date)
);
CREATE INDEX knowledge_document_validity ON knowledge_document (effective_date, expiry_date);
CREATE INDEX knowledge_document_roles_gin ON knowledge_document USING gin (allowed_roles);
CREATE INDEX knowledge_document_supplier ON knowledge_document (supplier_id);

-- vector(384): output size of the local sentence-embedding model used by the ingestion pipeline.
CREATE TABLE knowledge_chunk (
    chunk_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id      text NOT NULL,
    document_version text NOT NULL,
    chunk_index      integer NOT NULL CHECK (chunk_index >= 0),
    content          text NOT NULL,
    token_count      integer NOT NULL CHECK (token_count > 0),
    embedding        vector(384) NOT NULL,
    metadata         jsonb NOT NULL DEFAULT '{}',
    content_tsv      tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    UNIQUE (document_id, document_version, chunk_index),
    FOREIGN KEY (document_id, document_version)
        REFERENCES knowledge_document (document_id, version) ON DELETE CASCADE
);
CREATE INDEX knowledge_chunk_embedding_hnsw
    ON knowledge_chunk USING hnsw (embedding vector_cosine_ops);
CREATE INDEX knowledge_chunk_tsv_gin ON knowledge_chunk USING gin (content_tsv);
CREATE INDEX knowledge_chunk_metadata_gin ON knowledge_chunk USING gin (metadata jsonb_path_ops);
