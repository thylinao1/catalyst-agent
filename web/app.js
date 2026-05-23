/* Catalyst Agent dashboard - loads data.json and renders everything. */
'use strict';

const REC_COLOR = { SUPPRESS: '#e2504d', CAUTION: '#d99a2b', CLEAR: '#3aa874' };
const DIR = {
  bullish: { color: '#3aa874', mark: '▲' },
  bearish: { color: '#e2504d', mark: '▼' },
  neutral: { color: '#8b8e97', mark: '●' },
};
const CAT_COLOR = {
  macro: '#5b9ed6',
  noise: '#585b63',
  protocol_upgrade: '#3aa874',
  regulatory: '#d99a2b',
  token_unlock: '#b07cd0',
  exploit: '#e2504d',
  listing: '#4cb3a5',
  partnership: '#c98a5b',
};
const CAT_FALLBACK = ['#5b9ed6', '#b07cd0', '#4cb3a5', '#c98a5b', '#8e8ad6'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const pad = (n) => String(n).padStart(2, '0');
const catColor = (() => {
  let i = 0;
  const extra = {};
  return (c) => {
    if (CAT_COLOR[c]) return CAT_COLOR[c];
    if (!extra[c]) extra[c] = CAT_FALLBACK[i++ % CAT_FALLBACK.length];
    return extra[c];
  };
})();

function fmtRun(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return '-';
  return `${pad(d.getUTCDate())} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`
       + ` · ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
}
function fmtRow(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return '-';
  return `${MON[d.getUTCMonth()]} ${pad(d.getUTCDate())} `
       + `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* ---- boot ----------------------------------------------------------- */
(function boot() {
  const data = window.CATALYST_DATA;
  if (!data || !data.counts) {
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('error').classList.remove('hidden');
    return;
  }
  try {
    render(data);
  } catch (err) {
    console.error(err);
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('error').classList.remove('hidden');
  }
})();

function render(data) {
  document.getElementById('loading').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');

  document.getElementById('runStamp').textContent = fmtRun(data.run_computed_at);
  document.getElementById('genMeta').textContent =
    'snapshot ' + fmtRun(data.generated_at);
  document.getElementById('footLeft').textContent =
    'Catalyst Agent · static snapshot · ' + fmtRun(data.generated_at);
  document.getElementById('analyticsMeta').textContent =
    data.classifications.length + ' classified events';
  document.getElementById('logMeta').textContent =
    data.classifications.length + ' rows';

  renderKPIs(data.counts);
  renderSignals(data.signals);
  renderCharts(data);
  renderLog(data.classifications);
}

/* ---- KPI strip ------------------------------------------------------ */
function renderKPIs(c) {
  const coverage = c.news_events
    ? Math.round((c.classifications / c.news_events) * 100) : 0;
  const cards = [
    { label: 'Events ingested', value: c.news_events,
      sub: 'pulled from RSS feeds', icon: '▤' },
    { label: 'Classified', value: c.classifications,
      sub: coverage + '% of events', icon: '◈' },
    { label: 'Live signals', value: c.live_signals,
      sub: 'assets gated this run', icon: '◎' },
    { label: 'Suppressed', value: c.suppressed, alert: c.suppressed > 0,
      sub: `${c.caution} caution · ${c.clear} clear`, icon: '◉' },
  ];
  document.getElementById('kpiGrid').innerHTML = cards.map((k) => `
    <div class="kpi${k.alert ? ' is-alert' : ''}">
      <div class="kpi-top">
        <span class="kpi-label">${k.label}</span>
        <span class="kpi-icon">${k.icon}</span>
      </div>
      <div class="kpi-value">${k.value}</div>
      <div class="kpi-sub">${esc(k.sub)}</div>
    </div>`).join('');
}

/* ---- gating signals ------------------------------------------------- */
function renderSignals(signals) {
  const list = document.getElementById('signalList');
  if (!signals.length) {
    list.innerHTML = '<div class="state"><p>No live catalysts. '
      + 'Every asset is CLEAR.</p></div>';
    return;
  }
  list.innerHTML = signals.map((s, i) => {
    const rec = s.recommendation;
    const cls = rec.toLowerCase();
    const color = REC_COLOR[rec] || '#8b8e97';
    const pct = Math.max(2, Math.min(100, Math.round(s.risk_score * 100)));
    const cats = (s.active_categories || [])
      .map((c) => `<span class="cat-tag">${esc(c)}</span>`).join('') || '-';
    const n = (s.contributing || []).length;
    const detail = (s.contributing || []).map((e) => {
      const d = DIR[e.direction] || DIR.neutral;
      const link = e.url
        ? `<a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.title)}</a>`
        : esc(e.title);
      return `
        <div class="contrib">
          <div class="contrib-dir" style="color:${d.color}">${d.mark}</div>
          <div>
            <div class="contrib-title">${link}</div>
            <div class="contrib-meta">
              <span style="color:${catColor(e.category)}">${esc(e.category)}</span>
              <span>${esc(e.source)}</span>
              <span>${fmtRow(e.published_at)} UTC</span>
            </div>
            <div class="contrib-rationale">${esc(e.rationale)}</div>
          </div>
          <div class="contrib-sev">
            sev <b>${e.severity.toFixed(2)}</b><br>
            conf <b>${e.confidence.toFixed(2)}</b>
          </div>
        </div>`;
    }).join('');
    return `
      <div class="signal${i === 0 ? ' open' : ''}">
        <div class="signal-main" data-toggle>
          <div class="signal-tick">${esc(s.asset)}</div>
          <div class="badge ${cls}">${esc(rec)}</div>
          <div class="signal-risk">
            <span class="v">${s.risk_score.toFixed(2)}</span>
            <span class="k">risk score</span>
          </div>
          <div>
            <div class="signal-cats">${cats}</div>
            <div class="risk-bar" style="margin-top:9px">
              <i style="width:${pct}%;background:${color}"></i>
            </div>
          </div>
          <div class="signal-count">${n} contributing<br>event${n === 1 ? '' : 's'}</div>
          <div class="chev">▾</div>
        </div>
        <div class="signal-detail">${detail}</div>
      </div>`;
  }).join('');

  list.querySelectorAll('[data-toggle]').forEach((el) => {
    el.addEventListener('click', () =>
      el.parentElement.classList.toggle('open'));
  });
}

/* ---- charts --------------------------------------------------------- */
function renderCharts(data) {
  Chart.defaults.font.family = "'JetBrains Mono', monospace";
  Chart.defaults.font.size = 10;
  Chart.defaults.color = '#8b8e97';

  const grid = { color: 'rgba(255,255,255,0.05)', drawTicks: false };
  const noGrid = { display: false };

  const barLabels = {
    id: 'barLabels',
    afterDatasetsDraw(chart) {
      const { ctx } = chart;
      ctx.save();
      ctx.font = "500 10px 'JetBrains Mono', monospace";
      ctx.fillStyle = '#e6e7ea';
      ctx.textBaseline = 'middle';
      chart.getDatasetMeta(0).data.forEach((bar, i) => {
        const raw = chart.data.datasets[0].data[i];
        const txt = chart.data.datasets[0]._fmt
          ? chart.data.datasets[0]._fmt(raw) : raw;
        ctx.fillText(txt, bar.x + 7, bar.y);
      });
      ctx.restore();
    },
  };

  /* risk by asset */
  new Chart(document.getElementById('riskChart'), {
    type: 'bar',
    data: {
      labels: data.signals.map((s) => s.asset),
      datasets: [{
        data: data.signals.map((s) => s.risk_score),
        backgroundColor: data.signals.map((s) => REC_COLOR[s.recommendation]),
        borderRadius: 3, barThickness: 18,
        _fmt: (v) => v.toFixed(2),
      }],
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      layout: { padding: { right: 34 } },
      plugins: { legend: { display: false }, tooltip: tip((c) =>
        `${c.label}  risk ${c.raw.toFixed(3)}`) },
      scales: {
        x: { min: 0, max: 1, grid, border: { display: false },
             ticks: { stepSize: 0.25 } },
        y: { grid: noGrid, border: { display: false } },
      },
    },
    plugins: [barLabels],
  });

  /* category mix */
  new Chart(document.getElementById('catChart'), {
    type: 'bar',
    data: {
      labels: data.category_mix.map((c) => c.category),
      datasets: [{
        data: data.category_mix.map((c) => c.count),
        backgroundColor: data.category_mix.map((c) => catColor(c.category)),
        borderRadius: 3, barThickness: 18,
        _fmt: (v) => String(v),
      }],
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      layout: { padding: { right: 26 } },
      plugins: { legend: { display: false }, tooltip: tip((c) =>
        `${c.label}  ${c.raw} event${c.raw === 1 ? '' : 's'}`) },
      scales: {
        x: { beginAtZero: true, grid, border: { display: false },
             ticks: { precision: 0 } },
        y: { grid: noGrid, border: { display: false } },
      },
    },
    plugins: [barLabels],
  });

  /* severity x confidence scatter */
  const byCat = {};
  data.classifications.forEach((e) => {
    (byCat[e.category] = byCat[e.category] || []).push({
      x: e.severity, y: e.confidence, t: e.title,
    });
  });
  new Chart(document.getElementById('scatterChart'), {
    type: 'scatter',
    data: {
      datasets: Object.keys(byCat).map((cat) => ({
        label: cat,
        data: byCat[cat],
        backgroundColor: catColor(cat),
        pointRadius: 5, pointHoverRadius: 7,
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom',
          labels: { boxWidth: 7, boxHeight: 7, usePointStyle: true,
            padding: 12, font: { size: 9.5 } } },
        tooltip: tip((c) => [
          c.dataset.label + '  ' + c.raw.t.slice(0, 46),
          `severity ${c.raw.x.toFixed(2)}  confidence ${c.raw.y.toFixed(2)}`,
        ]),
      },
      scales: {
        x: { min: 0, max: 1, grid, border: { display: false },
             title: { display: true, text: 'severity', color: '#585b63' },
             ticks: { stepSize: 0.25 } },
        y: { min: 0, max: 1, grid, border: { display: false },
             title: { display: true, text: 'confidence', color: '#585b63' },
             ticks: { stepSize: 0.25 } },
      },
    },
  });
}

function tip(labelFn) {
  return {
    backgroundColor: '#16181d',
    borderColor: 'rgba(255,255,255,0.13)', borderWidth: 1,
    titleColor: '#e6e7ea', bodyColor: '#8b8e97',
    padding: 9, cornerRadius: 6, displayColors: false,
    callbacks: { title: () => '', label: labelFn },
  };
}

/* ---- classification log -------------------------------------------- */
function renderLog(rows) {
  const state = { key: 'classified_at', dir: -1, cat: 'all' };

  const cats = ['all', ...new Set(rows.map((r) => r.category))];
  const filters = document.getElementById('filters');
  cats.forEach((c) => {
    const chip = document.createElement('span');
    chip.className = 'chip' + (c === 'all' ? ' active' : '');
    chip.textContent = c === 'all' ? 'all' : c;
    chip.addEventListener('click', () => {
      state.cat = c;
      filters.querySelectorAll('.chip').forEach((x) =>
        x.classList.toggle('active', x === chip));
      draw();
    });
    filters.appendChild(chip);
  });

  document.querySelectorAll('#logHead th').forEach((th) => {
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      if (state.key === key) state.dir *= -1;
      else { state.key = key; state.dir = key === 'title' ? 1 : -1; }
      draw();
    });
  });

  function draw() {
    document.querySelectorAll('#logHead th').forEach((th) => {
      const on = th.dataset.key === state.key;
      th.classList.toggle('sorted', on);
      th.querySelector('.arrow').textContent = state.dir < 0 ? '▼' : '▲';
    });
    let view = rows.filter((r) =>
      state.cat === 'all' || r.category === state.cat);
    view = view.slice().sort((a, b) => {
      let x = a[state.key], y = b[state.key];
      if (typeof x === 'string') { x = x.toLowerCase(); y = y.toLowerCase(); }
      return x < y ? -state.dir : x > y ? state.dir : 0;
    });
    document.getElementById('logMeta').textContent =
      view.length + (view.length === rows.length ? ' rows'
        : ' of ' + rows.length + ' rows');
    document.getElementById('logBody').innerHTML = view.map((r) => {
      const d = DIR[r.direction] || DIR.neutral;
      const sev = Math.round(r.severity * 100);
      const link = r.url
        ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>`
        : esc(r.title);
      return `
        <tr>
          <td class="t-time">${fmtRow(r.classified_at)}</td>
          <td class="t-src">${esc(shortSource(r.source))}</td>
          <td><span class="cat-tag"
              style="color:${catColor(r.category)}">${esc(r.category)}</span></td>
          <td><span class="dir-pill" style="color:${d.color}">
              ${d.mark} ${esc(r.direction)}</span></td>
          <td class="num">
            <div class="sev-cell">
              <span class="sev-mini"><i style="width:${sev}%"></i></span>
              <span class="t-num">${r.severity.toFixed(2)}</span>
            </div>
          </td>
          <td class="num t-conf"><span class="t-num">${r.confidence.toFixed(2)}</span></td>
          <td class="t-head">${link}</td>
        </tr>`;
    }).join('');
  }
  draw();
}

function shortSource(s) {
  return String(s || '').split(':')[0].split('.')[0].trim() || '-';
}
