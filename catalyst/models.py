"""Plain data objects passed between pipeline stages.

Three records mirror the three SQL tables:
  NewsEvent      -> news_events       (raw, unclassified)
  Classification -> classifications   (after the LLM agent)
  CatalystSignal -> catalyst_signals  (after the Catalyst Shield)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow_iso() -> str:
    """Current UTC time as an ISO-8601 string (stable, sortable)."""
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 string into an aware UTC datetime, tolerating 'Z'."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class NewsEvent:
    """A single raw news item, before classification."""

    external_id: str                       # upstream id - used for dedup
    title: str
    source: str = ""
    url: str = ""
    published_at: str = ""                 # ISO-8601 UTC
    kind: str = "news"
    currencies: list[str] = field(default_factory=list)  # tickers, e.g. ["BTC"]
    raw: dict = field(default_factory=dict)
    fetched_at: str = field(default_factory=utcnow_iso)


@dataclass
class Classification:
    """The LLM agent's verdict on one event."""

    event_external_id: str
    category: str                          # one of config.VALID_CATEGORIES
    direction: str                         # one of config.VALID_DIRECTIONS
    severity: float                        # 0.0 - 1.0, model-judged
    confidence: float                      # 0.0 - 1.0, model-judged
    cooldown_hours: int                    # looked up from the category
    affected_assets: list[str] = field(default_factory=list)
    rationale: str = ""
    model: str = ""
    classified_at: str = field(default_factory=utcnow_iso)


@dataclass
class CatalystSignal:
    """The Catalyst Shield's per-asset gating output.

    `recommendation` is the structured flag a downstream model consumes:
      CLEAR    -> no live catalyst, model may act normally
      CAUTION  -> a moderate catalyst is live, reduce exposure
      SUPPRESS -> a strong catalyst is live, gate the model off for this asset
    """

    asset: str
    window_start: str
    window_end: str
    risk_score: float                      # 0.0 - 1.0
    recommendation: str                    # CLEAR | CAUTION | SUPPRESS
    active_categories: list[str] = field(default_factory=list)
    contributing_events: list[str] = field(default_factory=list)
    computed_at: str = field(default_factory=utcnow_iso)
