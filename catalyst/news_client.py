"""News sources — the perception stage of the pipeline.

Two sources, both exposing the same `.fetch()` method so the pipeline does not
care which is used:

  * RSSNewsClient   — live crypto news from public RSS feeds (no API key).
  * SampleNewsSource — a bundled JSON fixture, for offline development/testing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import requests

from .models import NewsEvent

# Public RSS feeds — free, no key, no quota. Override via RSS_FEEDS in .env.
DEFAULT_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
]

_USER_AGENT = "catalyst-agent/0.1 (research project)"


class NewsClientError(RuntimeError):
    """Raised when a news source cannot return data."""


def _struct_time_to_iso(parsed) -> str:
    """Convert a feedparser time.struct_time into an ISO-8601 UTC string."""
    if not parsed:
        return ""
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


class RSSNewsClient:
    """Fetches live crypto news from public RSS feeds.

    RSS items are not tagged with coin tickers, so `currencies` on each event is
    left empty — the LLM agent infers affected assets from the headline. If a
    `currencies` filter is passed to `fetch()`, a best-effort title match is
    applied (RSS has no structured coin field, so this is approximate).
    """

    def __init__(self, feeds: list[str] | None = None, timeout: int = 20):
        self.feeds = feeds or list(DEFAULT_FEEDS)
        self.timeout = timeout

    def fetch(
        self,
        currencies: list[str] | None = None,
        max_items: int = 50,
        kind: str = "news",
    ) -> list[NewsEvent]:
        try:
            import feedparser
        except ImportError as exc:
            raise NewsClientError(
                "feedparser is not installed. Run: pip install -r requirements.txt"
            ) from exc

        wanted = {c.upper() for c in currencies} if currencies else None
        events: list[NewsEvent] = []
        seen: set[str] = set()
        errors: list[str] = []

        for feed_url in self.feeds:
            if len(events) >= max_items:
                break
            try:
                resp = requests.get(
                    feed_url,
                    timeout=self.timeout,
                    headers={"User-Agent": _USER_AGENT},
                )
                resp.raise_for_status()
            except requests.RequestException as exc:
                errors.append(f"{feed_url}: {exc}")
                continue

            parsed = feedparser.parse(resp.content)
            feed_title = parsed.feed.get("title", feed_url)

            for entry in parsed.entries:
                if len(events) >= max_items:
                    break
                event = self._to_event(entry, feed_title)
                if not event.title or event.external_id in seen:
                    continue
                if wanted and not self._mentions(event.title, wanted):
                    continue
                seen.add(event.external_id)
                events.append(event)

        # Only error out if every feed failed; otherwise carry on with what we got.
        if not events and errors:
            raise NewsClientError("all RSS feeds failed: " + "; ".join(errors))
        return events

    @staticmethod
    def _mentions(title: str, wanted: set[str]) -> bool:
        """Approximate ticker filter — does the headline contain a wanted code?"""
        tokens = {t.strip(".,:;!?()[]'\"").upper() for t in title.split()}
        return bool(tokens.intersection(wanted))

    @staticmethod
    def _to_event(entry, feed_title: str) -> NewsEvent:
        """Map one RSS entry into a NewsEvent."""
        external_id = (
            entry.get("id") or entry.get("link") or entry.get("title", "")
        )
        published = _struct_time_to_iso(
            entry.get("published_parsed") or entry.get("updated_parsed")
        )
        return NewsEvent(
            external_id=str(external_id),
            title=entry.get("title", "").strip(),
            source=feed_title,
            url=entry.get("link", ""),
            published_at=published,
            kind="news",
            currencies=[],  # RSS feeds carry no structured coin tags
            raw={
                "summary": entry.get("summary", ""),
                "author": entry.get("author", ""),
            },
        )


class SampleNewsSource:
    """Reads a local JSON fixture instead of hitting the network.

    Used for offline development and the test suite. The fixture is a list of
    simplified objects; see data/sample_events.json.
    """

    def __init__(self, path: str):
        self.path = path

    def fetch(
        self,
        currencies: list[str] | None = None,
        max_items: int = 50,
        kind: str = "news",
    ) -> list[NewsEvent]:
        try:
            with open(self.path, encoding="utf-8") as fh:
                raw_items = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise NewsClientError(f"Cannot read sample data {self.path}: {exc}") from exc

        events: list[NewsEvent] = []
        wanted = {c.upper() for c in currencies} if currencies else None
        for raw in raw_items:
            tickers = [t.upper() for t in raw.get("currencies", [])]
            if wanted and not wanted.intersection(tickers):
                continue
            events.append(
                NewsEvent(
                    external_id=str(raw["external_id"]),
                    title=raw["title"].strip(),
                    source=raw.get("source", "sample"),
                    url=raw.get("url", ""),
                    published_at=raw.get("published_at", ""),
                    kind=raw.get("kind", "news"),
                    currencies=tickers,
                    raw=raw,
                )
            )
            if len(events) >= max_items:
                break
        return events
