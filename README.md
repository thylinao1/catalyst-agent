# Catalyst Agent

An LLM-powered agent that reads unstructured crypto news, classifies each item
into a fixed catalyst taxonomy, and condenses the live catalysts into a
structured per-asset **gating signal** (`CLEAR` / `CAUTION` / `SUPPRESS`) that a
downstream model can consume.

It is a working implementation of the *catalyst-awareness layer* that was
specified for the ARASAF statistical-arbitrage framework but stripped from the
shipped "Lite" version — rebuilt here as a standalone, deployable component.

## Pipeline

```
  RSS feeds ──────► news_client ──► (per new event)
                                         │
                                         ▼
                       knowledge_base ──► RAG retrieval (embeddings + cosine)
                                         │
                                         ▼
                       classifier ──────► Gemini, strict-JSON classification
                                         │
                                         ▼
                       storage ─────────► SQLite  (events + classifications)
                                         │
                                         ▼
                       catalyst_shield ─► per-asset risk score + recommendation
                                         │
                                         ▼
                       storage ─────────► SQLite  (catalyst_signals)
```

Perception → retrieval → reasoning → action. New events only are classified, so
re-running is cheap and idempotent.

## Project layout

```
catalyst_agent/
  run.py                  pipeline CLI entrypoint
  dashboard.py            Streamlit dashboard (read-only view of catalyst.db)
  .streamlit/config.toml  dashboard theme
  schema.sql              SQL schema (SQLite; ports to Postgres/TimescaleDB)
  requirements.txt        requests, feedparser, dotenv, streamlit
  catalyst/
    config.py             settings + the catalyst taxonomy
    models.py             NewsEvent / Classification / CatalystSignal records
    news_client.py        RSS feed client + offline sample source
    llm_client.py         Gemini REST client + offline MockLLMClient
    knowledge_base.py     RAG: embed labelled examples, retrieve nearest k
    classifier.py         the classification agent (RAG-augmented prompt)
    catalyst_shield.py    aggregates classifications into gating signals
    storage.py            SQLite repository (all SQL lives here)
    pipeline.py           orchestration + build_pipeline() factory
  data/
    knowledge_base.json   labelled RAG corpus
    sample_events.json    offline news fixture
  tests/
    test_pipeline.py      offline end-to-end test (no key, no network)
```

## Setup

1. **Python 3.10+**, then install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. **Get one free API key** — Google Gemini, at <https://aistudio.google.com/apikey>.
   News comes from public RSS feeds, so no news API key is needed.
3. Copy `.env.example` to `.env` and paste the Gemini key in.
4. Initialise the database:
   ```
   python run.py --init-db
   ```

## Usage

```
# Live: pull crypto news, classify with Gemini, store signals
python run.py --source live --currencies BTC,ETH,SOL

# Inspect the latest stored signals
python run.py --show-signals

# Offline: bundled sample feed + deterministic mock LLM (no keys needed)
python run.py --source sample --llm mock
```

### Dashboard

Once a pipeline run has populated the database, launch the Streamlit dashboard:

```
streamlit run dashboard.py
```

It shows the live catalyst signals, a filterable classification log, and the
category mix. It is read-only — it re-reads `catalyst.db` on each refresh and
never calls Gemini or the news feeds, so the pipeline and dashboard stay
cleanly decoupled.

## How it works

**News client** — `RSSNewsClient` pulls recent items from public crypto RSS
feeds (CoinDesk, Cointelegraph, Decrypt) and maps them to `NewsEvent` records.
`SampleNewsSource` reads a local JSON fixture instead, for offline work. Both
expose the same `.fetch()` method, so the pipeline is source-agnostic.

**RAG knowledge base** — `data/knowledge_base.json` holds hand-labelled example
events. Each is embedded once (Gemini `gemini-embedding-001`; vectors cached in
SQLite). For every incoming event the three most similar examples are retrieved
by cosine similarity and injected into the prompt as few-shot context.

**Classification agent** — builds a prompt from the taxonomy + retrieved
examples + the event, and calls Gemini with a JSON response schema so the model
can only return well-formed output. The result is validated (unknown categories
fall back to `noise`) and assigned the deterministic cooldown for its category.

**Catalyst Shield** — a catalyst stays "live" for its category's cooldown
window (e.g. 168h for an exploit, 48h for an unlock). The shield collects every
live catalyst per asset and combines them with a noisy-OR into one risk score,
then maps that to `CLEAR` / `CAUTION` / `SUPPRESS`.

**Storage** — all SQL is in `storage.py`. Writes are parameterised and
idempotent (`news_events.external_id` and `classifications.event_id` are
`UNIQUE`). SQLite is used for zero-setup; the schema is plain SQL and ports to
Postgres / TimescaleDB unchanged — see the header of `schema.sql`.

## Data model

| Table              | One row per…                               |
|--------------------|--------------------------------------------|
| `news_events`      | raw news item fetched from the feed        |
| `classifications`  | the agent's verdict on one event           |
| `catalyst_signals` | per-asset gating signal from one shield run|
| `kb_embeddings`    | cached embedding for one RAG example       |

## Testing

```
python tests/test_pipeline.py
```

Runs the full pipeline offline (sample feed + mock LLM, throwaway database) and
checks fetch → classify → store → signal, idempotency on re-run, and that
non-catalyst "noise" items never produce a gating signal.

## Roadmap

- **Deploy it** — containerise (Docker), schedule (Airflow / Prefect), run
  continuously, add drift monitoring on the classification mix.
- **Function calling** — let the agent call a tool to pull an asset's recent
  event history from SQL before deciding severity (true tool-use agent).
- **Postgres / TimescaleDB** — swap the storage backend for the deployed
  pipeline (schema already compatible).

## Honest limitations

- The catalyst taxonomy, cooldown windows and shield thresholds are
  hand-designed priors, not learned or backtested against price outcomes.
- `MockLLMClient` is a keyword stub for offline testing only — not a model.
- RSS feeds carry no structured coin tags, so affected assets are inferred by
  the LLM from the headline; the `--currencies` filter on RSS is a best-effort
  title match. Swap or add feeds via `RSS_FEEDS` in `.env`.
- On the Gemini free tier the client paces requests (~one every 7s) to stay
  under the ~10 requests/minute limit, and embeddings are batched into a single
  call, so a live run of ~15 events takes a couple of minutes. Lower
  `min_interval` in `llm_client.py` on a paid tier.
- Classification quality depends on the Gemini model; the RAG corpus is small
  and should grow as more labelled examples are collected.
