#!/usr/bin/env python3
"""Offline end-to-end test — no API key, no network.

Runs the whole pipeline against the bundled sample feed with the deterministic
MockLLMClient, into a throwaway database. Verifies fetch -> classify -> store
-> signal, idempotency on re-run, and that non-catalyst "noise" never gates.

Run:  python tests/test_pipeline.py
"""
from __future__ import annotations

import os
import sys
import tempfile

# Make the project importable when run directly.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from catalyst.config import Config              # noqa: E402
from catalyst.pipeline import build_pipeline    # noqa: E402

PASSED = 0


def check(label: str, condition: bool) -> None:
    global PASSED
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}")
    if not condition:
        raise AssertionError(label)
    PASSED += 1


def main() -> int:
    tmp_db = os.path.join(tempfile.mkdtemp(), "test_catalyst.db")
    config = Config(db_path=tmp_db)

    print("Run 1 — fresh database, sample feed, mock LLM:")
    pipe = build_pipeline(config, source="sample", llm_backend="mock")
    r1 = pipe.run(max_items=50)

    check("fetched all 10 sample events", r1.fetched == 10)
    check("classified all 10 new events", r1.classified == 10)
    check("10 events persisted", r1.db_counts["news_events"] == 10)
    check("10 classifications persisted", r1.db_counts["classifications"] == 10)
    check("at least one catalyst signal produced", len(r1.signals) >= 1)
    check(
        "signals are risk-ranked (descending)",
        all(
            r1.signals[i].risk_score >= r1.signals[i + 1].risk_score
            for i in range(len(r1.signals) - 1)
        ),
    )

    by_asset = {s.asset: s for s in r1.signals}
    check("ARB has a signal (bridge exploit event)", "ARB" in by_asset)
    check(
        "ARB exploit is gated (CAUTION or SUPPRESS)",
        by_asset["ARB"].recommendation in ("CAUTION", "SUPPRESS"),
    )
    check(
        "ARB signal cites security_exploit",
        "security_exploit" in by_asset["ARB"].active_categories,
    )
    check("XRP 'noise' item produced no signal", "XRP" not in by_asset)

    print("\nRun 2 — same database, same feed (idempotency check):")
    pipe2 = build_pipeline(config, source="sample", llm_backend="mock")
    r2 = pipe2.run(max_items=50)
    check("no events re-classified on second run", r2.classified == 0)
    check("event count unchanged", r2.db_counts["news_events"] == 10)

    print(f"\nSignals from run 1 ({len(r1.signals)} assets):")
    for s in r1.signals:
        print(
            f"  {s.asset:<6} risk={s.risk_score:<5} {s.recommendation:<9}"
            f" {', '.join(s.active_categories)}"
        )

    print(f"\nAll {PASSED} checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
