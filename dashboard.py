"""Streamlit dashboard for the Catalyst Agent.

A read-only view over catalyst.db. Populate the database by running the
pipeline first, then launch the dashboard:

    python run.py --source live --currencies BTC,ETH,SOL
    streamlit run dashboard.py

The dashboard never calls Gemini or the news feeds. It only reads the SQLite
database the pipeline writes, so the two stay cleanly decoupled.

The dark styling is forced via injected CSS rather than relying on Streamlit's
theme config, so it looks the same regardless of the local Streamlit setup.
"""
from __future__ import annotations

import html
import os

import pandas as pd
import streamlit as st

from catalyst.config import Config
from catalyst.storage import Storage

st.set_page_config(page_title="Catalyst Agent", layout="wide")

CONFIG = Config.from_env()

REC_COLOR = {"SUPPRESS": "#e5484d", "CAUTION": "#f5a623", "CLEAR": "#30a46c"}
DIR_COLOR = {"bullish": "#30a46c", "bearish": "#e5484d", "neutral": "#888da0"}

# Forced dark styling. All colours are explicit so nothing depends on whether
# the Streamlit theme config loaded.
STYLES = """
<style>
  /* --- force a dark canvas regardless of the Streamlit theme --- */
  .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"],
  [data-testid="stHeader"], body { background-color: #0d0e12 !important; }
  [data-testid="stHeader"] { height: 0; }
  [data-testid="stAppDeployButton"], #MainMenu, footer { display: none; }
  .block-container { max-width: 1080px; padding-top: 1.6rem; padding-bottom: 4rem; }
  .stApp, .stMarkdown, [data-testid="stMarkdownContainer"] { color: #f0f1f5; }

  /* --- header --- */
  .cat-title { font-size: 2rem; font-weight: 800; letter-spacing: -0.02em;
    color: #f0f1f5; }
  .cat-sub { color: #888da0; font-size: 0.95rem; margin: 0.15rem 0 0.1rem; }

  /* --- refresh button --- */
  .stButton > button { background: #16181f !important; color: #f0f1f5 !important;
    border: 1px solid #262934 !important; border-radius: 8px !important;
    font-weight: 600 !important; }
  .stButton > button:hover { border-color: #4f8ff7 !important;
    color: #ffffff !important; }

  /* --- metric cards --- */
  .metric-grid { display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 14px; margin: 16px 0 4px; }
  .metric-card { background: #16181f; border: 1px solid #262934;
    border-radius: 12px; padding: 16px 18px; transition: border-color 0.15s; }
  .metric-card:hover { border-color: #353a4a; }
  .metric-label { color: #888da0; font-size: 0.72rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.07em; }
  .metric-value { font-size: 2rem; font-weight: 800; margin-top: 4px;
    line-height: 1.1; color: #f0f1f5; }
  .metric-card.alert .metric-value { color: #e5484d; }

  /* --- section headings --- */
  .section-title { font-size: 1.18rem; font-weight: 700; color: #f0f1f5;
    margin: 32px 0 1px; }
  .section-sub { color: #888da0; font-size: 0.85rem; margin-bottom: 13px; }

  /* --- signal cards --- */
  .signal-card { display: flex; align-items: center; gap: 16px;
    background: #16181f; border: 1px solid #262934; border-left: 4px solid #555;
    border-radius: 10px; padding: 14px 18px; margin-bottom: 9px;
    transition: border-color 0.15s; }
  .signal-card:hover { border-color: #353a4a; }
  .signal-card.suppress { border-left-color: #e5484d; }
  .signal-card.caution { border-left-color: #f5a623; }
  .signal-card.clear { border-left-color: #30a46c; }
  .sig-asset { font-size: 1.15rem; font-weight: 800; color: #f0f1f5;
    width: 74px; }
  .pill { font-size: 0.68rem; font-weight: 700; padding: 3px 11px;
    border-radius: 999px; letter-spacing: 0.05em; white-space: nowrap; }
  .pill.suppress { background: rgba(229,72,77,0.16); color: #ff6b70; }
  .pill.caution { background: rgba(245,166,35,0.16); color: #f7b955; }
  .pill.clear { background: rgba(48,164,108,0.16); color: #4cc98a; }
  .sig-cats { color: #888da0; font-size: 0.85rem; flex: 1; }
  .risk-track { width: 120px; height: 8px; background: #262934;
    border-radius: 999px; overflow: hidden; }
  .risk-fill { height: 100%; border-radius: 999px; }
  .sig-risk { font-size: 1.05rem; font-weight: 800; color: #f0f1f5;
    width: 44px; text-align: right; }

  /* --- category mix bars --- */
  .catbar-row { display: flex; align-items: center; gap: 12px;
    margin-bottom: 6px; }
  .catbar-label { width: 150px; font-size: 0.82rem; color: #b9bdca;
    text-align: right; }
  .catbar-track { flex: 1; height: 20px; background: #16181f;
    border: 1px solid #262934; border-radius: 5px; overflow: hidden; }
  .catbar-fill { height: 100%; background: #4f8ff7; }
  .catbar-count { width: 26px; font-size: 0.82rem; color: #888da0; }

  /* --- classification log table --- */
  .log-wrap { border: 1px solid #262934; border-radius: 10px;
    max-height: 460px; overflow-y: auto; }
  .log-wrap::-webkit-scrollbar { width: 8px; }
  .log-wrap::-webkit-scrollbar-thumb { background: #2a2d3a; border-radius: 4px; }
  .log-table { width: 100%; border-collapse: collapse; font-size: 0.83rem; }
  .log-table th { position: sticky; top: 0; background: #1a1c24; color: #888da0;
    text-align: left; padding: 9px 14px; font-weight: 600; font-size: 0.7rem;
    text-transform: uppercase; letter-spacing: 0.05em;
    border-bottom: 1px solid #262934; }
  .log-table td { padding: 9px 14px; border-bottom: 1px solid #1c1e27;
    color: #d6d8e0; }
  .log-table tr:last-child td { border-bottom: none; }
  .log-table tr:hover td { background: #14161d; }
  .cat-tag { background: #222533; color: #aab0c2; padding: 2px 8px;
    border-radius: 5px; font-size: 0.74rem; }
  .sev-track { display: inline-block; width: 52px; height: 6px;
    background: #262934; border-radius: 3px; overflow: hidden;
    vertical-align: middle; margin-right: 7px; }
  .sev-fill { display: block; height: 100%; background: #4f8ff7; }
  .headline { color: #c9ccd6; max-width: 360px; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; }
  .nowrap { white-space: nowrap; }
  .foot { color: #5f6478; font-size: 0.78rem; margin-top: 26px; }
</style>
"""


def load_data():
    """Read everything the dashboard needs from the database."""
    storage = Storage(CONFIG.db_path)
    storage.init_db()  # idempotent, harmless if the DB is brand new
    return (
        storage.counts(),
        storage.latest_signals(),
        storage.recent_classified_events(limit=200),
    )


def metric_cards(counts: dict, signals: list) -> str:
    """HTML for the four summary metric cards."""
    suppressed = sum(s.recommendation == "SUPPRESS" for s in signals)
    cards = [
        ("News events", counts["news_events"], False),
        ("Classifications", counts["classifications"], False),
        ("Live signals", len(signals), False),
        ("Assets suppressed", suppressed, suppressed > 0),
    ]
    cells = ""
    for label, value, alert in cards:
        cls = "metric-card alert" if alert else "metric-card"
        cells += (
            f'<div class="{cls}"><div class="metric-label">{label}</div>'
            f'<div class="metric-value">{value}</div></div>'
        )
    return f'<div class="metric-grid">{cells}</div>'


def signal_cards(signals: list) -> str:
    """HTML for the colour-coded per-asset signal cards."""
    if not signals:
        return (
            '<div class="signal-card clear">'
            '<div class="sig-cats">No live catalysts. Every asset is CLEAR.'
            "</div></div>"
        )
    rows = ""
    for s in signals:
        cls = s.recommendation.lower()
        color = REC_COLOR.get(s.recommendation, "#888")
        pct = max(0, min(100, round(s.risk_score * 100)))
        cats = html.escape(", ".join(s.active_categories) or "-")
        rows += (
            f'<div class="signal-card {cls}">'
            f'<div class="sig-asset">{html.escape(s.asset)}</div>'
            f'<span class="pill {cls}">{s.recommendation}</span>'
            f'<div class="sig-cats">{cats}</div>'
            f'<div class="risk-track"><div class="risk-fill" '
            f'style="width:{pct}%;background:{color}"></div></div>'
            f'<div class="sig-risk">{s.risk_score:.2f}</div></div>'
        )
    return rows


def category_bars(series: pd.Series) -> str:
    """HTML for the category-mix horizontal bars."""
    if series.empty:
        return '<div class="section-sub">No classifications yet.</div>'
    top = int(series.max())
    rows = ""
    for category, count in series.items():
        pct = round(int(count) / top * 100)
        rows += (
            f'<div class="catbar-row">'
            f'<div class="catbar-label">{html.escape(str(category))}</div>'
            f'<div class="catbar-track"><div class="catbar-fill" '
            f'style="width:{pct}%"></div></div>'
            f'<div class="catbar-count">{int(count)}</div></div>'
        )
    return rows


def log_table(rows: list[dict]) -> str:
    """HTML for the classification-log table."""
    if not rows:
        return '<div class="section-sub">No classifications recorded yet.</div>'
    header = (
        "<tr><th>Time</th><th>Source</th><th>Category</th><th>Direction</th>"
        "<th>Severity</th><th>Headline</th></tr>"
    )
    body = ""
    for r in rows:
        ts = pd.to_datetime(r.get("classified_at"), errors="coerce")
        ts_str = ts.strftime("%b %d, %H:%M") if pd.notna(ts) else "-"
        severity = float(r.get("severity") or 0.0)
        sev_pct = max(0, min(100, round(severity * 100)))
        direction = str(r.get("direction", ""))
        dir_color = DIR_COLOR.get(direction, "#888da0")
        body += (
            "<tr>"
            f'<td class="nowrap">{ts_str}</td>'
            f"<td>{html.escape(str(r.get('source', ''))[:24])}</td>"
            f'<td><span class="cat-tag">{html.escape(str(r.get("category", "")))}'
            "</span></td>"
            f'<td style="color:{dir_color}">{html.escape(direction)}</td>'
            f'<td class="nowrap"><span class="sev-track"><span class="sev-fill" '
            f'style="width:{sev_pct}%"></span></span>{severity:.2f}</td>'
            f'<td class="headline">{html.escape(str(r.get("title", "")))}</td>'
            "</tr>"
        )
    return (
        f'<div class="log-wrap"><table class="log-table"><thead>{header}'
        f"</thead><tbody>{body}</tbody></table></div>"
    )


# --- page ------------------------------------------------------------------
st.markdown(STYLES, unsafe_allow_html=True)
st.markdown(
    '<div class="cat-title">Catalyst Agent</div>'
    '<div class="cat-sub">LLM-classified crypto-news catalysts and the '
    "per-asset gating signals they produce.</div>",
    unsafe_allow_html=True,
)
st.button("Refresh data")

try:
    counts, signals, log_rows = load_data()
except Exception as exc:  # surface any DB error in the UI rather than crashing
    st.error(f"Could not read the database: {exc}")
    st.stop()

if counts["news_events"] == 0:
    st.info(
        "No data yet. Populate the database first, then refresh:\n\n"
        "`python run.py --source live --currencies BTC,ETH,SOL`"
    )
    st.stop()

st.markdown(metric_cards(counts, signals), unsafe_allow_html=True)

st.markdown(
    '<div class="section-title">Catalyst signals</div>'
    '<div class="section-sub">The structured gate a downstream model '
    "consumes, ranked highest-risk first.</div>",
    unsafe_allow_html=True,
)
st.markdown(signal_cards(signals), unsafe_allow_html=True)

st.markdown(
    '<div class="section-title">Classification log</div>'
    '<div class="section-sub">Every event the agent has classified.</div>',
    unsafe_allow_html=True,
)

if log_rows:
    cat_series = pd.Series(
        [r["category"] for r in log_rows]
    ).value_counts()
    st.markdown('<div class="section-sub">Category mix</div>', unsafe_allow_html=True)
    st.markdown(category_bars(cat_series), unsafe_allow_html=True)
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

st.markdown(log_table(log_rows), unsafe_allow_html=True)
st.markdown(
    f'<div class="foot">Database: {html.escape(os.path.basename(CONFIG.db_path))}</div>',
    unsafe_allow_html=True,
)
