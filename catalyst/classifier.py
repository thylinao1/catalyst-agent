"""The classification agent - RAG-augmented LLM event classification.

For one news event the agent:
  1. retrieves the nearest labelled examples from the knowledge base (RAG),
  2. builds a structured prompt: taxonomy + retrieved examples + the event,
  3. asks the LLM for a strict-JSON classification,
  4. validates the result and attaches the deterministic cooldown window.
"""
from __future__ import annotations

from .config import (
    CATALYST_CATEGORIES,
    VALID_CATEGORIES,
    VALID_DIRECTIONS,
    cooldown_for,
)
from .knowledge_base import KnowledgeBase
from .llm_client import LLMClient
from .models import Classification, NewsEvent

# JSON schema handed to the LLM so it can only return well-formed output.
# Uppercase types are the form expected by Gemini's responseSchema field.
RESPONSE_SCHEMA: dict = {
    "type": "OBJECT",
    "properties": {
        "category": {"type": "STRING", "enum": list(VALID_CATEGORIES)},
        "direction": {"type": "STRING", "enum": list(VALID_DIRECTIONS)},
        "severity": {"type": "NUMBER"},
        "confidence": {"type": "NUMBER"},
        "affected_assets": {"type": "ARRAY", "items": {"type": "STRING"}},
        "rationale": {"type": "STRING"},
    },
    "required": ["category", "direction", "severity", "confidence", "rationale"],
}


def _clamp(value, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return lo


def event_query_text(event: NewsEvent) -> str:
    """The text used to retrieve similar examples for an event (title + tickers)."""
    query = event.title
    if event.currencies:
        query += " " + " ".join(event.currencies)
    return query


class CatalystClassifier:
    """Wraps an LLM client + knowledge base into an event classifier."""

    def __init__(self, llm_client: LLMClient, knowledge_base: KnowledgeBase):
        self.llm = llm_client
        self.kb = knowledge_base

    # -- prompt construction ----------------------------------------------
    @staticmethod
    def _taxonomy_block() -> str:
        lines = []
        for name, meta in CATALYST_CATEGORIES.items():
            lines.append(
                f"- {name}: {meta['definition']} "
                f"(typical severity {meta['typical_severity']})"
            )
        return "\n".join(lines)

    @staticmethod
    def _examples_block(examples: list[dict]) -> str:
        if not examples:
            return "(no similar prior examples found)"
        lines = []
        for ex in examples:
            lines.append(
                f'- "{ex["title"]}" -> category={ex["category"]}, '
                f'direction={ex["direction"]}'
            )
        return "\n".join(lines)

    def _build_prompt(self, event: NewsEvent, examples: list[dict]) -> str:
        tickers = ", ".join(event.currencies) if event.currencies else "unspecified"
        return f"""You are a catalyst-classification agent in a crypto research \
pipeline. Classify ONE news item into exactly one category from the taxonomy.

TAXONOMY:
{self._taxonomy_block()}

SIMILAR PRIOR EXAMPLES (retrieved for context - use them to stay consistent):
{self._examples_block(examples)}

NEWS ITEM TO CLASSIFY:
  Title:      {event.title}
  Source:     {event.source}
  Tickers:    {tickers}

INSTRUCTIONS:
- category: the single best-fitting taxonomy category.
- direction: likely price impact on the affected assets (bullish/bearish/neutral).
- severity: 0.0-1.0 - how market-moving this specific item is for those assets.
- confidence: 0.0-1.0 - how certain you are of this classification.
- affected_assets: ticker symbols this item concerns (use the tickers above if \
they are correct; otherwise infer from the title).
- rationale: one concise sentence explaining the call.
Return JSON only, matching the required schema."""

    # -- classification ----------------------------------------------------
    def classify_batch(self, events: list[NewsEvent]) -> list[Classification]:
        """Classify many events, embedding all RAG queries in one batched call.

        This keeps embedding to a single API request regardless of how many
        events are processed - important under free-tier rate limits.
        """
        if not events:
            return []
        query_vectors = self.llm.embed_batch(
            [event_query_text(e) for e in events]
        )
        return [
            self.classify(event, query_vector=vec)
            for event, vec in zip(events, query_vectors)
        ]

    def classify(
        self, event: NewsEvent, query_vector: list[float] | None = None
    ) -> Classification:
        """Classify a single event into a Classification record.

        If `query_vector` is supplied (precomputed by `classify_batch`), the
        RAG lookup reuses it instead of making a per-event embedding call.
        """
        if query_vector is not None:
            examples = self.kb.retrieve_by_vector(query_vector, k=3)
        else:
            examples = self.kb.retrieve(event_query_text(event), k=3)

        prompt = self._build_prompt(event, examples)
        result = self.llm.classify(prompt, RESPONSE_SCHEMA)

        # Validate the model output; fall back safely rather than trusting it.
        category = result.get("category", "noise")
        if category not in VALID_CATEGORIES:
            category = "noise"
        direction = result.get("direction", "neutral")
        if direction not in VALID_DIRECTIONS:
            direction = "neutral"

        # Prefer the model's asset list; fall back to the feed's tickers.
        assets = [a.upper() for a in result.get("affected_assets", []) if a]
        if not assets:
            assets = list(event.currencies)

        return Classification(
            event_external_id=event.external_id,
            category=category,
            direction=direction,
            severity=_clamp(result.get("severity", 0.0)),
            confidence=_clamp(result.get("confidence", 0.0)),
            cooldown_hours=cooldown_for(category),
            affected_assets=assets,
            rationale=str(result.get("rationale", "")).strip(),
            model=self.llm.name,
        )
