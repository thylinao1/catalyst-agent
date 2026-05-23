"""SQLite storage layer.

All SQL lives here. Queries are parameterised (no string interpolation), and
writes are idempotent - re-running the pipeline never duplicates a row, because
`news_events.external_id` and `classifications.event_id` are UNIQUE.

SQLite is used so the project runs with zero setup, but the schema is plain
SQL and ports to Postgres / TimescaleDB unchanged (see schema.sql).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .config import ROOT
from .models import CatalystSignal, Classification, NewsEvent, utcnow_iso

SCHEMA_PATH = ROOT / "schema.sql"


class Storage:
    """Thin repository over a SQLite database."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # -- schema ------------------------------------------------------------
    def init_db(self) -> None:
        """Create tables from schema.sql if they do not already exist."""
        sql = Path(SCHEMA_PATH).read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(sql)

    # -- news_events -------------------------------------------------------
    def upsert_event(self, event: NewsEvent) -> int:
        """Insert an event (or leave it untouched if seen before).

        Returns the internal row id either way.
        """
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO news_events
                    (external_id, source, title, url, published_at,
                     kind, currencies, raw_json, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(external_id) DO UPDATE SET
                    fetched_at = excluded.fetched_at
                """,
                (
                    event.external_id,
                    event.source,
                    event.title,
                    event.url,
                    event.published_at,
                    event.kind,
                    json.dumps(event.currencies),
                    json.dumps(event.raw),
                    event.fetched_at,
                ),
            )
            row = conn.execute(
                "SELECT id FROM news_events WHERE external_id = ?",
                (event.external_id,),
            ).fetchone()
            return int(row["id"])

    def has_classification(self, event_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM classifications WHERE event_id = ?", (event_id,)
            ).fetchone()
            return row is not None

    # -- classifications ---------------------------------------------------
    def save_classification(self, event_id: int, c: Classification) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO classifications
                    (event_id, category, direction, severity, confidence,
                     cooldown_hours, affected_assets, rationale, model,
                     classified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    category        = excluded.category,
                    direction       = excluded.direction,
                    severity        = excluded.severity,
                    confidence      = excluded.confidence,
                    cooldown_hours  = excluded.cooldown_hours,
                    affected_assets = excluded.affected_assets,
                    rationale       = excluded.rationale,
                    model           = excluded.model,
                    classified_at   = excluded.classified_at
                """,
                (
                    event_id,
                    c.category,
                    c.direction,
                    c.severity,
                    c.confidence,
                    c.cooldown_hours,
                    json.dumps(c.affected_assets),
                    c.rationale,
                    c.model,
                    c.classified_at,
                ),
            )

    def recent_classifications(self, since_iso: str) -> list[Classification]:
        """All classifications made at or after `since_iso`, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, e.external_id AS event_external_id
                FROM classifications c
                JOIN news_events e ON e.id = c.event_id
                WHERE c.classified_at >= ?
                ORDER BY c.classified_at DESC
                """,
                (since_iso,),
            ).fetchall()
        return [self._row_to_classification(r) for r in rows]

    @staticmethod
    def _row_to_classification(r: sqlite3.Row) -> Classification:
        return Classification(
            event_external_id=r["event_external_id"],
            category=r["category"],
            direction=r["direction"],
            severity=r["severity"],
            confidence=r["confidence"],
            cooldown_hours=r["cooldown_hours"],
            affected_assets=json.loads(r["affected_assets"] or "[]"),
            rationale=r["rationale"] or "",
            model=r["model"] or "",
            classified_at=r["classified_at"],
        )

    # -- catalyst_signals --------------------------------------------------
    def save_signal(self, s: CatalystSignal) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO catalyst_signals
                    (asset, window_start, window_end, risk_score, recommendation,
                     active_categories, contributing_events, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    s.asset,
                    s.window_start,
                    s.window_end,
                    s.risk_score,
                    s.recommendation,
                    json.dumps(s.active_categories),
                    json.dumps(s.contributing_events),
                    s.computed_at,
                ),
            )

    def latest_signals(self) -> list[CatalystSignal]:
        """Signals from the most recent pipeline run, ordered by risk."""
        with self._connect() as conn:
            latest = conn.execute(
                "SELECT MAX(computed_at) AS t FROM catalyst_signals"
            ).fetchone()
            if not latest or latest["t"] is None:
                return []
            rows = conn.execute(
                """
                SELECT * FROM catalyst_signals
                WHERE computed_at = ?
                ORDER BY risk_score DESC
                """,
                (latest["t"],),
            ).fetchall()
        return [
            CatalystSignal(
                asset=r["asset"],
                window_start=r["window_start"],
                window_end=r["window_end"],
                risk_score=r["risk_score"],
                recommendation=r["recommendation"],
                active_categories=json.loads(r["active_categories"] or "[]"),
                contributing_events=json.loads(r["contributing_events"] or "[]"),
                computed_at=r["computed_at"],
            )
            for r in rows
        ]

    # -- knowledge-base embedding cache ------------------------------------
    def get_kb_embedding(self, text_hash: str) -> list[float] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT vector FROM kb_embeddings WHERE text_hash = ?",
                (text_hash,),
            ).fetchone()
            return json.loads(row["vector"]) if row else None

    def save_kb_embedding(
        self, text_hash: str, model: str, vector: list[float]
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO kb_embeddings (text_hash, model, vector, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(text_hash) DO UPDATE SET
                    model = excluded.model,
                    vector = excluded.vector,
                    created_at = excluded.created_at
                """,
                (text_hash, model, json.dumps(vector), utcnow_iso()),
            )

    def recent_classified_events(self, limit: int = 100) -> list[dict]:
        """Recent events joined with their classification, newest first.

        Used by the dashboard's classification-log view.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.title, e.source, e.url, e.published_at,
                       c.category, c.direction, c.severity, c.confidence,
                       c.rationale, c.classified_at
                FROM classifications c
                JOIN news_events e ON e.id = c.event_id
                ORDER BY c.classified_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- misc --------------------------------------------------------------
    def counts(self) -> dict[str, int]:
        """Row counts per table, for run summaries."""
        out: dict[str, int] = {}
        with self._connect() as conn:
            for table in ("news_events", "classifications", "catalyst_signals"):
                row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                out[table] = int(row["n"])
        return out
