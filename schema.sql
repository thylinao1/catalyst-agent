-- Catalyst Agent - relational schema
-- ---------------------------------------------------------------------------
-- Written for SQLite (zero-setup, ships with Python) but deliberately kept
-- portable. To move to Postgres / TimescaleDB for the deployed pipeline:
--   * INTEGER PRIMARY KEY            -> BIGSERIAL / GENERATED ALWAYS AS IDENTITY
--   * TEXT timestamps (ISO-8601 UTC) -> TIMESTAMPTZ
--   * TEXT json columns              -> JSONB
--   * then run SELECT create_hypertable('news_events', 'published_at') in TSDB.
-- All timestamps are stored as ISO-8601 UTC strings so ordering is lexical.
-- ---------------------------------------------------------------------------

-- Raw news/events pulled from the news feed. external_id is the upstream id,
-- kept UNIQUE so re-running the pipeline is idempotent (no duplicate rows).
CREATE TABLE IF NOT EXISTS news_events (
    id           INTEGER PRIMARY KEY,
    external_id  TEXT    NOT NULL UNIQUE,
    source       TEXT,
    title        TEXT    NOT NULL,
    url          TEXT,
    published_at TEXT,                       -- ISO-8601 UTC
    kind         TEXT,
    currencies   TEXT,                       -- json array of ticker strings
    raw_json     TEXT,                       -- full upstream payload, for audit
    fetched_at   TEXT    NOT NULL            -- ISO-8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_events_published ON news_events (published_at);

-- One row per event after the LLM agent classifies it.
CREATE TABLE IF NOT EXISTS classifications (
    id             INTEGER PRIMARY KEY,
    event_id       INTEGER NOT NULL REFERENCES news_events (id),
    category       TEXT    NOT NULL,         -- e.g. token_unlock, regulatory
    direction      TEXT    NOT NULL,         -- bullish | bearish | neutral
    severity       REAL    NOT NULL,         -- 0.0 - 1.0
    confidence     REAL    NOT NULL,         -- 0.0 - 1.0
    cooldown_hours INTEGER NOT NULL,         -- how long the catalyst stays "live"
    affected_assets TEXT,                    -- json array of ticker strings
    rationale      TEXT,                     -- model's short explanation
    model          TEXT,                    -- model name / version used
    classified_at  TEXT    NOT NULL,         -- ISO-8601 UTC
    UNIQUE (event_id)                        -- one classification per event
);

CREATE INDEX IF NOT EXISTS idx_class_time ON classifications (classified_at);

-- Per-asset gating signal produced by the Catalyst Shield. This is the
-- structured output a downstream model would consume.
CREATE TABLE IF NOT EXISTS catalyst_signals (
    id                  INTEGER PRIMARY KEY,
    asset               TEXT    NOT NULL,
    window_start        TEXT    NOT NULL,
    window_end          TEXT    NOT NULL,
    risk_score          REAL    NOT NULL,    -- 0.0 - 1.0
    recommendation      TEXT    NOT NULL,    -- CLEAR | CAUTION | SUPPRESS
    active_categories   TEXT,                -- json array
    contributing_events TEXT,                -- json array of event ids
    computed_at         TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signal_asset ON catalyst_signals (asset, computed_at);

-- Cache for knowledge-base embeddings so the RAG corpus is embedded only once.
-- Keyed by a hash of the source text; vector stored as a json array.
CREATE TABLE IF NOT EXISTS kb_embeddings (
    text_hash  TEXT PRIMARY KEY,
    model      TEXT NOT NULL,
    vector     TEXT NOT NULL,                -- json array of floats
    created_at TEXT NOT NULL
);
