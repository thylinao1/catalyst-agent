"""RAG knowledge base - retrieval over labelled example events.

This is the "retrieval" half of retrieval-augmented generation. A small corpus
of hand-labelled historical events is embedded once (vectors cached in SQLite);
for each incoming event the most similar examples are retrieved and injected
into the prompt as few-shot context. That grounds the model in concrete prior
cases instead of relying on the taxonomy definitions alone.
"""
from __future__ import annotations

import hashlib
import json
import math

from .llm_client import LLMClient
from .storage import Storage


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class KnowledgeBase:
    """Loads labelled examples, embeds them once, retrieves the nearest k."""

    def __init__(self, path: str, llm_client: LLMClient, storage: Storage):
        self.path = path
        self.llm = llm_client
        self.storage = storage
        self.examples: list[dict] = []
        self._vectors: list[list[float]] = []

    @staticmethod
    def _text(example: dict) -> str:
        """Text used both for embedding and for the few-shot prompt block."""
        return f"{example['title']} - {example.get('note', '')}".strip(" -")

    def _hash(self, text: str) -> str:
        """Cache key - namespaced by model so vectors are never mixed."""
        key = f"{self.llm.name}::{text}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def build(self) -> None:
        """Load the corpus and ensure every example has a cached embedding.

        Examples missing from the cache are embedded in a single batched
        request, so the whole knowledge-base build costs just one API call.
        """
        with open(self.path, encoding="utf-8") as fh:
            self.examples = json.load(fh)

        self._vectors = [[] for _ in self.examples]
        missing: list[tuple[int, str, str]] = []  # (index, text, text_hash)
        for i, example in enumerate(self.examples):
            text = self._text(example)
            text_hash = self._hash(text)
            cached = self.storage.get_kb_embedding(text_hash)
            if cached is not None:
                self._vectors[i] = cached
            else:
                missing.append((i, text, text_hash))

        if missing:
            vectors = self.llm.embed_batch([text for _, text, _ in missing])
            for (i, _, text_hash), vector in zip(missing, vectors):
                self._vectors[i] = vector
                self.storage.save_kb_embedding(text_hash, self.llm.name, vector)

    def retrieve_by_vector(self, query_vec: list[float], k: int = 3) -> list[dict]:
        """Return the k examples most similar to a precomputed query vector."""
        if not self.examples:
            return []
        scored = [
            (_cosine(query_vec, vec), ex)
            for vec, ex in zip(self._vectors, self.examples)
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [ex for _, ex in scored[:k]]

    def retrieve(self, query_text: str, k: int = 3) -> list[dict]:
        """Embed `query_text` and return the k most similar examples."""
        if not self.examples:
            return []
        return self.retrieve_by_vector(self.llm.embed(query_text), k)
