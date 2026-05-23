"""LLM clients - the reasoning stage of the pipeline.

`LLMClient` is the interface the rest of the code depends on. Two implementations:

  * GeminiClient - calls Google's Gemini API over plain REST. REST (rather than
    an SDK) keeps the dependency surface tiny and makes the provider trivial to
    swap: a new provider is just another LLMClient subclass.
  * MockLLMClient - deterministic, offline. Lets the whole pipeline (and the
    test suite) run with no API key and no network.

Both expose:
    classify(prompt, schema) -> dict   # structured JSON classification
    embed(text)              -> list[float]   # vector for RAG retrieval
"""
from __future__ import annotations

import abc
import hashlib
import json
import math
import time

import requests

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"


class LLMError(RuntimeError):
    """Raised when the LLM provider cannot return a usable response."""


class LLMClient(abc.ABC):
    """Interface every LLM backend must implement."""

    name: str = "abstract"

    @abc.abstractmethod
    def classify(self, prompt: str, schema: dict) -> dict:
        """Return a JSON object matching `schema`."""

    @abc.abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return an embedding vector for `text`."""

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts. Default loops `embed`; batch-capable backends
        override this to do it in a single request."""
        return [self.embed(t) for t in texts]


class GeminiClient(LLMClient):
    """Google Gemini backend (REST, free tier compatible)."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        embed_model: str = "gemini-embedding-001",
        timeout: int = 30,
        max_retries: int = 5,
        min_interval: float = 7.0,
    ):
        if not api_key:
            raise LLMError(
                "No Gemini API key. Put GEMINI_API_KEY in your .env "
                "(free key: https://aistudio.google.com/apikey)."
            )
        self.api_key = api_key
        self.model = model
        self.embed_model = embed_model
        self.timeout = timeout
        self.max_retries = max_retries
        # Minimum seconds between API calls - paces requests under the Gemini
        # free-tier limit (~10 requests/min). Lower this on a paid tier.
        self.min_interval = min_interval
        self._last_call = 0.0
        self.name = f"gemini::{model}"

    def _throttle(self) -> None:
        """Sleep so consecutive calls stay under the free-tier rate limit."""
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _post(self, url: str, body: dict) -> dict:
        """POST with throttling + backoff on rate-limit / transient errors."""
        last_err = "unknown error"
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                resp = requests.post(url, json=body, timeout=self.timeout)
            except requests.RequestException as exc:
                last_err = str(exc)
                time.sleep(min(64, 8 * 2 ** attempt))
                continue

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code in (429, 500, 503):
                # Rate-limited or transient - honour Retry-After, else back off.
                retry_after = (resp.headers.get("Retry-After") or "").strip()
                delay = (
                    int(retry_after)
                    if retry_after.isdigit()
                    else min(64, 8 * 2 ** attempt)
                )
                last_err = f"HTTP {resp.status_code} (rate limit / transient)"
                time.sleep(delay)
                continue

            # Anything else (404 bad model, 403 bad key, ...) is not retryable.
            raise LLMError(f"Gemini HTTP {resp.status_code}: {resp.text[:200]}")

        raise LLMError(
            f"Gemini request failed after {self.max_retries} retries: {last_err}"
        )

    def classify(self, prompt: str, schema: dict) -> dict:
        url = f"{GEMINI_ENDPOINT}/{self.model}:generateContent?key={self.api_key}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,                       # deterministic labelling
                "responseMimeType": "application/json",  # force structured output
                "responseSchema": schema,
            },
        }
        data = self._post(url, body)
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMError(f"Unparseable Gemini response: {exc}; raw={data}") from exc

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str], chunk: int = 100) -> list[list[float]]:
        """Embed many texts via the batchEmbedContents endpoint - one request
        per chunk of 100 - so the knowledge-base build costs a single call."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), chunk):
            batch = texts[start : start + chunk]
            url = (
                f"{GEMINI_ENDPOINT}/{self.embed_model}"
                f":batchEmbedContents?key={self.api_key}"
            )
            body = {
                "requests": [
                    {
                        "model": f"models/{self.embed_model}",
                        "content": {"parts": [{"text": t}]},
                    }
                    for t in batch
                ]
            }
            data = self._post(url, body)
            try:
                vectors.extend(
                    [float(x) for x in e["values"]] for e in data["embeddings"]
                )
            except (KeyError, TypeError) as exc:
                raise LLMError(f"Unparseable Gemini batch embedding: {exc}") from exc
        return vectors


class MockLLMClient(LLMClient):
    """Offline, deterministic backend - keyword rules + hashed embeddings.

    Not a real model: it exists so the pipeline and tests run without a key.
    The keyword map below is intentionally simple and only used for testing.
    """

    name = "mock"

    _RULES: list[tuple[tuple[str, ...], str, str]] = [
        # (keywords, category, direction)
        (("exploit", "hack", "drain", "stolen", "breach"), "security_exploit", "bearish"),
        (("unlock", "vesting", "cliff release"), "token_unlock", "bearish"),
        (("sec ", "lawsuit", "ban", "regulat", "court", "fined"), "regulatory", "bearish"),
        (("upgrade", "hard fork", "mainnet", "migration"), "protocol_upgrade", "neutral"),
        (("delist",), "delisting", "bearish"),
        (("lists ", "listing", "will list"), "listing", "bullish"),
        (("partner", "integrat", "collaborat"), "partnership", "bullish"),
        (("burn", "buyback", "emission", "tokenomic"), "tokenomic_change", "neutral"),
        (("rate", "fed", "inflation", "macro", "inflow"), "macro", "neutral"),
    ]

    def classify(self, prompt: str, schema: dict) -> dict:
        # Match only against the news-item section of the prompt - the taxonomy
        # and example blocks contain category keywords that would match falsely.
        segment = prompt
        if "NEWS ITEM TO CLASSIFY:" in prompt and "INSTRUCTIONS:" in prompt:
            segment = prompt.split("NEWS ITEM TO CLASSIFY:")[1].split("INSTRUCTIONS:")[0]
        text = segment.lower()
        for keywords, category, direction in self._RULES:
            if any(k in text for k in keywords):
                severity = {
                    "security_exploit": 0.9,
                    "regulatory": 0.7,
                    "tokenomic_change": 0.6,
                    "delisting": 0.8,
                }.get(category, 0.5)
                return {
                    "category": category,
                    "direction": direction,
                    "severity": severity,
                    "confidence": 0.8,
                    "affected_assets": [],
                    "rationale": f"[mock] matched keyword rule for {category}",
                }
        return {
            "category": "noise",
            "direction": "neutral",
            "severity": 0.05,
            "confidence": 0.6,
            "affected_assets": [],
            "rationale": "[mock] no operational catalyst keyword found",
        }

    def embed(self, text: str, dim: int = 64) -> list[float]:
        """Deterministic hashed bag-of-words vector (stable across runs)."""
        vec = [0.0] * dim
        for word in text.lower().split():
            digest = hashlib.md5(word.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
