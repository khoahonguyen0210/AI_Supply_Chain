"""Text embedders behind one protocol.

`FastEmbedEmbedder` is the real model (BAAI/bge-small-en-v1.5, ONNX, 384-dim, matching the pgvector
column). `HashingEmbedder` is a deterministic offline stand-in (signed hashed unigrams and
bigrams) so tests and CI need no model download; it captures lexical overlap only and is never
used to report retrieval quality of the real model.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

EMBEDDING_DIM = 384
FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
_TOKEN = re.compile(r"[a-z0-9%$]+(?:[-.,][a-z0-9]+)*")

Matrix = NDArray[np.float32]


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> Matrix: ...

    def embed_query(self, text: str) -> Matrix: ...


def _normalise(matrix: Matrix) -> Matrix:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


class HashingEmbedder:
    name = "hashing-384"
    dim = EMBEDDING_DIM

    def _vector(self, text: str) -> Matrix:
        tokens = _TOKEN.findall(text.lower())
        features = tokens + [f"{a} {b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        vector = np.zeros(self.dim, dtype=np.float32)
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            vector[value % self.dim] += 1.0 if (value >> 32) & 1 else -1.0
        return vector

    def embed_documents(self, texts: list[str]) -> Matrix:
        return _normalise(np.stack([self._vector(t) for t in texts]))

    def embed_query(self, text: str) -> Matrix:
        return self.embed_documents([text])[0:1]


class FastEmbedEmbedder:
    name = FASTEMBED_MODEL
    dim = EMBEDDING_DIM

    def __init__(self, model_name: str = FASTEMBED_MODEL) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)

    def embed_documents(self, texts: list[str]) -> Matrix:
        return _normalise(np.asarray(list(self._model.embed(texts)), dtype=np.float32))

    def embed_query(self, text: str) -> Matrix:
        return _normalise(np.asarray(list(self._model.query_embed(text)), dtype=np.float32))
