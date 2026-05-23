"""Export catalyst.db into a static JSON snapshot for the web dashboard.

The web front-end (web/index.html) is a fully static site: it reads a single
`web/data.js` file and renders everything client-side. This script is the
bridge between the pipeline's SQLite database and that data file.

The data is written as `window.CATALYST_DATA = {...};` (a JS file, not raw
JSON) so the dashboard opens by simply double-clicking index.html - browsers
block fetch() of local files, but a <script> tag always works.

Workflow:

    python run.py --source live --currencies BTC,ETH,SOL   # populate catalyst.db
    python export_data.py                                  # write web/data.js
    # then deploy / commit the web/ folder

It uses only the Python standard library, so it has no dependency on the
`catalyst` package and keeps working even if that code changes.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "catalyst.db"
DEFAULT_OUT = ROOT / "web" / "data.js"


def _loads(value: str | None, fallback):
    """Parse a JSON column, tolerating NULL / malformed values."""
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return fallback


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def build_payload(conn: sqlite3.Connection) -> dict:
    """Read every table the dashboard needs and assemble the JSON payload."""

    # -- classifications, joined to their source event ------------------
    class_rows = conn.execute(
        """
        SELECT e.external_id, e.title, e.source, e.url, e.published_at,
               c.category, c.direction, c.severity, c.confidence,
               c.cooldown_hours, c.affected_assets, c.rationale,
               c.classified_at
        FROM classifications c
        JOIN news_events e ON e.id = c.event_id
        ORDER BY c.classified_at DESC
        """
    ).fetchall()

    classifications = []
    by_external_id: dict[str, dict] = {}
    for r in class_rows:
        item = {
            "external_id": r["external_id"],
            "title": r["title"],
            "source": r["source"] or "",
            "url": r["url"] or "",
            "published_at": r["published_at"] or "",
            "category": r["category"],
            "direction": r["direction"],
            "severity": round(float(r["severity"] or 0.0), 4),
            "confidence": round(float(r["confidence"] or 0.0), 4),
            "cooldown_hours": int(r["cooldown_hours"] or 0),
            "affected_assets": _loads(r["affected_assets"], []),
            "rationale": (r["rationale"] or "").strip(),
            "classified_at": r["classified_at"],
        }
        classifications.append(item)
        by_external_id[r["external_id"]] = item

    # -- latest signal run ----------------------------------------------
    latest = conn.execute(
        "SELECT MAX(computed_at) AS t FROM catalyst_signals"
    ).fetchone()
    run_at = latest["t"] if latest else None

    signals = []
    if run_at:
        sig_rows = conn.execute(
            """
            SELECT asset, window_start, window_end, risk_score,
                   recommendation, active_categories, contributing_events,
                   computed_at
            FROM catalyst_signals
            WHERE computed_at = ?
            ORDER BY risk_score DESC
            """,
            (run_at,),
        ).fetchall()
        for r in sig_rows:
            contributing_ids = _loads(r["contributing_events"], [])
            contributing = [
                by_external_id[eid]
                for eid in contributing_ids
                if eid in by_external_id
            ]
            signals.append(
                {
                    "asset": r["asset"],
                    "window_start": r["window_start"],
                    "window_end": r["window_end"],
                    "risk_score": round(float(r["risk_score"] or 0.0), 4),
                    "recommendation": r["recommendation"],
                    "active_categories": _loads(r["active_categories"], []),
                    "computed_at": r["computed_at"],
                    "contributing": contributing,
                }
            )

    # -- aggregates ------------------------------------------------------
    cat_counter = Counter(c["category"] for c in classifications)
    dir_counter = Counter(c["direction"] for c in classifications)
    src_counter = Counter(c["source"] for c in classifications if c["source"])

    rec_counter = Counter(s["recommendation"] for s in signals)

    counts = {
        "news_events": conn.execute(
            "SELECT COUNT(*) AS n FROM news_events"
        ).fetchone()["n"],
        "classifications": len(classifications),
        "live_signals": len(signals),
        "suppressed": rec_counter.get("SUPPRESS", 0),
        "caution": rec_counter.get("CAUTION", 0),
        "clear": rec_counter.get("CLEAR", 0),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_computed_at": run_at,
        "counts": counts,
        "signals": signals,
        "classifications": classifications,
        "category_mix": [
            {"category": k, "count": v}
            for k, v in cat_counter.most_common()
        ],
        "direction_mix": [
            {"direction": k, "count": v}
            for k, v in dir_counter.most_common()
        ],
        "source_mix": [
            {"source": k, "count": v}
            for k, v in src_counter.most_common()
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export catalyst.db to data.json")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="path to catalyst.db (default: ./catalyst.db)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="output path (default: ./web/data.js)")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}\n"
                         f"Run the pipeline first (see README).")

    conn = _connect(args.db)
    try:
        payload = build_payload(conn)
    finally:
        conn.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2)
    args.out.write_text(
        f"/* Auto-generated by export_data.py - do not edit by hand. */\n"
        f"window.CATALYST_DATA = {body};\n",
        encoding="utf-8",
    )

    c = payload["counts"]
    print(f"Wrote {args.out}")
    print(f"  {c['news_events']} events  "
          f"{c['classifications']} classifications  "
          f"{c['live_signals']} signals "
          f"({c['suppressed']} suppressed, {c['caution']} caution)")


if __name__ == "__main__":
    main()
