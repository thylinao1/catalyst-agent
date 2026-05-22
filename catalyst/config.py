"""Configuration and the catalyst taxonomy.

Two things live here:
  1. `Config` — runtime settings, loaded from environment / .env file.
  2. `CATALYST_CATEGORIES` — the fixed taxonomy the LLM agent classifies into.

Keeping the taxonomy in one place means the prompt, the storage layer and the
Catalyst Shield all agree on the same category names and cooldown windows.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional; env vars still work without it.
    pass

# Project root = the directory that contains this package.
ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Catalyst taxonomy
# ---------------------------------------------------------------------------
# Each event is classified into exactly one category. `cooldown_hours` is how
# long the catalyst is treated as "live" by the Catalyst Shield — it is fixed
# per category (deterministic) rather than left to the model. `typical_severity`
# is guidance shown to the model, not a hard rule; the model returns its own
# 0-1 severity for the specific event.
CATALYST_CATEGORIES: dict[str, dict] = {
    "security_exploit": {
        "definition": "A hack, exploit, smart-contract bug, bridge drain, validator "
        "failure, or any loss/freezing of user funds.",
        "cooldown_hours": 168,
        "typical_severity": "0.8-1.0",
    },
    "tokenomic_change": {
        "definition": "A change to a token's supply schedule, emissions, burn, "
        "buyback, staking, or fee mechanics.",
        "cooldown_hours": 168,
        "typical_severity": "0.6-0.95",
    },
    "regulatory": {
        "definition": "Regulatory action, lawsuit, enforcement, ban, approval, or "
        "government policy affecting a token or the sector.",
        "cooldown_hours": 120,
        "typical_severity": "0.5-0.9",
    },
    "protocol_upgrade": {
        "definition": "A network upgrade, hard fork, mainnet launch, or major "
        "technical migration.",
        "cooldown_hours": 168,
        "typical_severity": "0.4-0.8",
    },
    "delisting": {
        "definition": "An exchange removing a token from trading.",
        "cooldown_hours": 48,
        "typical_severity": "0.6-0.9",
    },
    "token_unlock": {
        "definition": "A scheduled vesting unlock or cliff release of previously "
        "locked token supply.",
        "cooldown_hours": 48,
        "typical_severity": "0.4-0.8",
    },
    "listing": {
        "definition": "An exchange adding a token, or the launch of a new spot / "
        "ETF / derivative product for it.",
        "cooldown_hours": 48,
        "typical_severity": "0.3-0.7",
    },
    "partnership": {
        "definition": "A partnership, integration, grant, or adoption announcement.",
        "cooldown_hours": 24,
        "typical_severity": "0.1-0.5",
    },
    "macro": {
        "definition": "A broad market or macro event not specific to one token "
        "(interest rates, ETF flows, sector-wide moves, sentiment shifts).",
        "cooldown_hours": 72,
        "typical_severity": "0.3-0.7",
    },
    "noise": {
        "definition": "Opinion, price commentary, speculation, listicles, or any "
        "item with no concrete operational catalyst.",
        "cooldown_hours": 0,
        "typical_severity": "0.0-0.1",
    },
}

VALID_CATEGORIES = tuple(CATALYST_CATEGORIES.keys())
VALID_DIRECTIONS = ("bullish", "bearish", "neutral")

# Catalyst Shield thresholds: an asset's risk score maps to a recommendation.
SUPPRESS_THRESHOLD = 0.66   # >= this  -> SUPPRESS (gate the model off)
CAUTION_THRESHOLD = 0.33    # >= this  -> CAUTION  (reduce exposure)
# below CAUTION_THRESHOLD     -> CLEAR


def cooldown_for(category: str) -> int:
    """Return the cooldown window (hours) for a category, 0 if unknown."""
    return CATALYST_CATEGORIES.get(category, {}).get("cooldown_hours", 0)


@dataclass
class Config:
    """Runtime configuration. Use `Config.from_env()` to build one.

    News comes from public RSS feeds, so no news API key is needed — the only
    credential required is the Gemini key.
    """

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"
    rss_feeds: list[str] = field(default_factory=list)  # empty -> client defaults
    db_path: str = "catalyst.db"

    @classmethod
    def from_env(cls) -> "Config":
        raw_feeds = os.getenv("RSS_FEEDS", "")
        feeds = [f.strip() for f in raw_feeds.split(",") if f.strip()]
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            gemini_embed_model=os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001"),
            rss_feeds=feeds,
            db_path=os.getenv("DB_PATH", str(ROOT / "catalyst.db")),
        )
