#!/usr/bin/env python3
"""Catalyst Agent - command-line entrypoint.

Examples:
    python run.py --init-db
    python run.py --source live --currencies BTC,ETH,SOL --max-items 40
    python run.py --source sample --llm mock        # offline, no keys needed
    python run.py --show-signals
"""
from __future__ import annotations

import argparse
import sys

from catalyst.config import Config
from catalyst.pipeline import build_pipeline
from catalyst.storage import Storage


def _print_signals(signals) -> None:
    if not signals:
        print("  (no live catalyst signals)")
        return
    print(f"  {'ASSET':<8} {'RISK':>6}  {'RECOMMENDATION':<14} CATEGORIES")
    print(f"  {'-' * 8} {'-' * 6}  {'-' * 14} {'-' * 30}")
    for s in signals:
        cats = ", ".join(s.active_categories)
        print(
            f"  {s.asset:<8} {s.risk_score:>6.2f}  "
            f"{s.recommendation:<14} {cats}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Catalyst Agent pipeline runner")
    parser.add_argument(
        "--source", choices=["live", "sample"], default="live",
        help="news source: live CryptoPanic feed, or bundled sample data",
    )
    parser.add_argument(
        "--llm", choices=["gemini", "mock"], default="gemini",
        help="LLM backend: Gemini API, or offline deterministic mock",
    )
    parser.add_argument(
        "--currencies", default="",
        help="comma-separated tickers to filter on, e.g. BTC,ETH,SOL",
    )
    parser.add_argument(
        "--max-items", type=int, default=15,
        help="max events per run (kept modest for the Gemini free-tier quota)",
    )
    parser.add_argument(
        "--init-db", action="store_true", help="create the database and exit",
    )
    parser.add_argument(
        "--show-signals", action="store_true",
        help="print the latest stored signals and exit",
    )
    args = parser.parse_args(argv)

    config = Config.from_env()

    if args.init_db:
        Storage(config.db_path).init_db()
        print(f"Database initialised at {config.db_path}")
        return 0

    if args.show_signals:
        signals = Storage(config.db_path).latest_signals()
        print("\nLatest catalyst signals:")
        _print_signals(signals)
        return 0

    currencies = [c.strip().upper() for c in args.currencies.split(",") if c.strip()]

    try:
        pipeline = build_pipeline(config, source=args.source, llm_backend=args.llm)
        result = pipeline.run(currencies=currencies or None, max_items=args.max_items)
    except Exception as exc:  # surface a clean message instead of a traceback
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("\n=== Catalyst Agent run ===")
    print(f"  source={args.source}  llm={args.llm}")
    print(f"  fetched={result.fetched}  new={result.new_events}  "
          f"classified={result.classified}")
    print(f"  database totals: {result.db_counts}")
    print("\nLive catalyst signals (risk-ranked):")
    _print_signals(result.signals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
