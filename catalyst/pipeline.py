"""Pipeline orchestration — wires the stages together.

    fetch news -> (per new event) RAG-classify -> store
               -> aggregate live classifications -> store gating signals

`build_pipeline()` is a factory that assembles a Pipeline from a Config,
choosing the news source (live / sample) and LLM backend (gemini / mock).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .catalyst_shield import CatalystShield
from .classifier import CatalystClassifier
from .config import ROOT, Config
from .knowledge_base import KnowledgeBase
from .llm_client import GeminiClient, LLMClient, MockLLMClient
from .models import CatalystSignal, NewsEvent
from .news_client import RSSNewsClient, SampleNewsSource
from .storage import Storage

KB_PATH = str(ROOT / "data" / "knowledge_base.json")
SAMPLE_PATH = str(ROOT / "data" / "sample_events.json")

# How far back to look when recomputing signals (covers the longest cooldown).
LOOKBACK_DAYS = 14


@dataclass
class PipelineResult:
    """Summary of one pipeline run."""

    fetched: int = 0
    new_events: int = 0
    classified: int = 0
    signals: list[CatalystSignal] = field(default_factory=list)
    db_counts: dict = field(default_factory=dict)


class Pipeline:
    """Runs one fetch -> classify -> aggregate cycle."""

    def __init__(
        self,
        storage: Storage,
        news_source,
        knowledge_base: KnowledgeBase,
        classifier: CatalystClassifier,
        shield: CatalystShield,
    ):
        self.storage = storage
        self.news = news_source
        self.kb = knowledge_base
        self.classifier = classifier
        self.shield = shield

    def run(
        self, currencies: list[str] | None = None, max_items: int = 40
    ) -> PipelineResult:
        self.storage.init_db()
        self.kb.build()  # embeds the RAG corpus once (cached thereafter)

        result = PipelineResult()

        # 1. Fetch, upsert all events, and collect the ones not yet classified.
        events = self.news.fetch(currencies=currencies, max_items=max_items)
        result.fetched = len(events)

        pending: list[tuple[int, NewsEvent]] = []
        for event in events:
            event_id = self.storage.upsert_event(event)
            if not self.storage.has_classification(event_id):
                pending.append((event_id, event))
        result.new_events = len(pending)

        # 2/3. Classify new events — RAG query embeddings are batched into one
        # request inside classify_batch, which matters under free-tier limits.
        classifications = self.classifier.classify_batch([e for _, e in pending])
        for (event_id, _), classification in zip(pending, classifications):
            self.storage.save_classification(event_id, classification)
            result.classified += 1

        # 4. Recompute gating signals from all classifications still in window.
        since = (
            datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
        ).isoformat()
        recent = self.storage.recent_classifications(since)
        signals = self.shield.compute_signals(recent, now=datetime.now(timezone.utc))
        for signal in signals:
            self.storage.save_signal(signal)

        result.signals = signals
        result.db_counts = self.storage.counts()
        return result


def build_pipeline(
    config: Config, source: str = "live", llm_backend: str = "gemini"
) -> Pipeline:
    """Assemble a Pipeline. `source`: live|sample. `llm_backend`: gemini|mock."""
    llm: LLMClient
    if llm_backend == "mock":
        llm = MockLLMClient()
    else:
        llm = GeminiClient(
            api_key=config.gemini_api_key,
            model=config.gemini_model,
            embed_model=config.gemini_embed_model,
        )

    if source == "sample":
        news_source = SampleNewsSource(SAMPLE_PATH)
    else:
        news_source = RSSNewsClient(feeds=config.rss_feeds or None)

    storage = Storage(config.db_path)
    knowledge_base = KnowledgeBase(KB_PATH, llm, storage)
    classifier = CatalystClassifier(llm, knowledge_base)
    shield = CatalystShield()
    return Pipeline(storage, news_source, knowledge_base, classifier, shield)
