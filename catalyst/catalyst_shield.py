"""The Catalyst Shield — turns individual classifications into a gating signal.

Each classified event stays "live" for its category's cooldown window. The
Shield collects every live catalyst per asset and condenses them into one
risk score and a recommendation (CLEAR / CAUTION / SUPPRESS) — the structured
output a downstream model would consume to decide whether to act on an asset.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .config import CAUTION_THRESHOLD, SUPPRESS_THRESHOLD
from .models import CatalystSignal, Classification, parse_iso, utcnow_iso


def _recommendation(risk: float) -> str:
    if risk >= SUPPRESS_THRESHOLD:
        return "SUPPRESS"
    if risk >= CAUTION_THRESHOLD:
        return "CAUTION"
    return "CLEAR"


class CatalystShield:
    """Aggregates live classifications into per-asset gating signals."""

    def compute_signals(
        self, classifications: list[Classification], now: datetime | None = None
    ) -> list[CatalystSignal]:
        now = now or datetime.now().astimezone()
        # One timestamp for the whole run, so all signals share a computed_at
        # and `Storage.latest_signals()` returns the complete set.
        run_ts = utcnow_iso()

        # Keep only catalysts still inside their cooldown window.
        live: list[tuple[Classification, datetime]] = []
        for c in classifications:
            if c.cooldown_hours <= 0:
                continue  # noise / non-catalysts never gate anything
            started = parse_iso(c.classified_at)
            if started is None:
                continue
            active_until = started + timedelta(hours=c.cooldown_hours)
            if now < active_until:
                live.append((c, active_until))

        # Bucket live catalysts by the asset(s) they affect.
        by_asset: dict[str, list[tuple[Classification, datetime]]] = {}
        for c, until in live:
            for asset in c.affected_assets or []:
                by_asset.setdefault(asset.upper(), []).append((c, until))

        signals: list[CatalystSignal] = []
        for asset, items in by_asset.items():
            # Noisy-OR: independent catalysts compound but the score stays in [0,1].
            survive = 1.0
            for c, _ in items:
                survive *= 1.0 - (c.severity * c.confidence)
            risk = round(1.0 - survive, 4)

            starts = [parse_iso(c.classified_at) for c, _ in items]
            starts = [s for s in starts if s is not None]
            window_start = min(starts).isoformat() if starts else utcnow_iso()
            window_end = max(until for _, until in items).isoformat()

            signals.append(
                CatalystSignal(
                    asset=asset,
                    window_start=window_start,
                    window_end=window_end,
                    risk_score=risk,
                    recommendation=_recommendation(risk),
                    active_categories=sorted({c.category for c, _ in items}),
                    contributing_events=[c.event_external_id for c, _ in items],
                    computed_at=run_ts,
                )
            )

        signals.sort(key=lambda s: s.risk_score, reverse=True)
        return signals
