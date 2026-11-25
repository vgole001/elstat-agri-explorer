'use strict';
/*
 * Greek agriculture map.
 * Data:  ../data/agri.json      (written by `python -m parser run`)
 * Shapes: data/regions.geojson  (written by tools/build_geo.py; property `code` = region_code)
 * Everything joins on region_code, never on names.
 */

const DATA_URL = '../data/agri.json';
const GEO_URL = 'data/regions.geojson';
const ISSUES_URL = '../data/anomalies.json';
const UNITS = { area: 'stremmas', production: 'tons', yield: 'kg/stremma', holdings: 'holdings', animals: 'heads' };
const METRIC_LABEL = { area: 'Area', production: 'Production', yield: 'Yield', holdings: 'Holdings', animals: 'Animals' };
const METRICS = ['area', 'production', 'yield', 'holdings', 'animals'];   // display order
const MODE_LABEL = { share: 'Share of Greece (%)', value: 'Value' };
const ALL_USES = '';            // detail '' = no split, or the sum of all uses

const $ = id => document.getElementById(id);
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

let INDEX = new Map();          // dataset -> Map(entryKey -> entry)
const SECTOR_OF = {};           // dataset -> sector (crops / livestock)
let ISSUES = [];                // anomaly flags from `python -m analysis` (optional)
const REGIONS = {};             // code -> {code, name, level, parent}
let GEO = null, map = null, geoLayer = null;
const layerByCode = {};

const state = { sector: '', dataset: '', category: '', item: '', detail: '', metric: '', year: '', mode: '', region: 'GR' };

// ------------------------------------------------------------------ data index

function parentOf(code) {
  if (code === 'GR') return null;
  return code.includes('-') ? code.split('-')[0] : 'GR';
}

/* entry = { category, item, table, summedUses, series: { 'metric|detail': { year: { code: value } } } } */
function buildIndex(records) {
  for (const r of records) {
    if (!REGIONS[r.region_code]) {
      REGIONS[r.region_code] = { code: r.region_code, name: r.region, level: r.level, parent: parentOf(r.region_code) };
    }
    if (!INDEX.has(r.dataset)) INDEX.set(r.dataset, new Map());
    SECTOR_OF[r.dataset] = r.sector;
    const ds = INDEX.get(r.dataset);
    const key = r.category + '||' + r.item;
    if (!ds.has(key)) ds.set(key, { category: r.category, item: r.item, table: r.table, summedUses: false, series: {} });
    const e = ds.get(key);
    const sk = r.metric + '|' + (r.detail || '');
    const byYear = (e.series[sk] ||= {});
    (byYear[r.year] ||= {})[r.region_code] = Number(r.value);
  }
  for (const ds of INDEX.values()) {
    for (const e of ds.values()) {
      // production split by use (grapes): add the sum of all uses as detail ''
      const split = Object.keys(e.series).filter(k => k.startsWith('production|') && k !== 'production|');
      if (split.length && !e.series['production|']) {
        const sum = {};
        for (const k of split) {
          for (const [y, vals] of Object.entries(e.series[k])) {
            for (const [code, v] of Object.entries(vals)) {
              (sum[y] ||= {})[code] = ((sum[y] || {})[code] || 0) + v;
            }
          }
        }
        e.series['production|'] = sum;
        e.summedUses = true;
      }
      // yield = production / area, only where both exist (kg per stremma)
      const a = e.series['area|'], p = e.series['production|'];
      if (a && p) {
        const y = {};
        for (const year of Object.keys(a)) {
          for (const [code, av] of Object.entries(a[year])) {
            const pv = (p[year] || {})[code];
            if (av > 0 && pv != null) (y[year] ||= {})[code] = pv * 1000 / av;
          }
        }
        if (Object.keys(y).length) e.series['yield|'] = y;
      }
    }
  }
}

const entry = () => INDEX.get(state.dataset)?.get(state.category + '||' + state.item);
const seriesOf = (metric, detail = state.detail) => entry()?.series[metric + '|' + (metric === 'production' ? detail : '')];

function value(code, metric = state.metric, year = state.year) {
  const v = seriesOf(metric)?.[year]?.[code];
  return v == null || Number.isNaN(v) ? null : v;
}

/* what the map and lists show for a code: raw value or share of a parent */
function display(code, of = 'GR') {
  const v = value(code);
  if (v == null) return null;
  if (state.mode !== 'share') return v;
  const t = value(of);
  return t ? (v / t) * 100 : null;
}

// ------------------------------------------------------------------ formatting

const nf = d => new Intl.NumberFormat('en-US', { maximumFractionDigits: d, minimumFractionDigits: 0 });
function fmt(v, metric = state.metric) {
  if (v == null) return '—';
  if (metric === 'yield') return nf(1).format(v);
  if (metric === 'production') return nf(Math.abs(v) < 100 ? 1 : 0).format(v);
  return nf(0).format(v);
}
const fmtPct = v => {
  if (v == null) return '—';
  if (v > 0 && v < 0.01) return '<0.01%';
  return nf(v < 1 ? 2 : 1).format(v) + '%';
};
const fmtDisplay = v => (state.mode === 'share' ? fmtPct(v) : fmt(v));
const unitLabel = () => (state.mode === 'share' ? '% of Greece' : UNITS[state.metric]);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const prettyDataset = d => d.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
const isLivestock = () => state.sector === 'livestock';
/* livestock items are herd-size classes: "Total", "1-4", "50 and over" (animals per holding) */
const bySize = () => isLivestock() && /herd size/i.test(state.category);
const itemLabel = i => {
  if (!isLivestock()) return i;
  if (i === 'Total') return bySize() ? 'All sizes' : 'All types';
  return bySize() ? `${i} animals` : i;
};

// ------------------------------------------------------------------ filters

function fill(select, options, current) {
  select.innerHTML = options.map(o => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('');
  const chosen = options.some(o => o.value === current) ? current : (options[0]?.value ?? '');
  select.value = chosen;
  select.disabled = options.length === 0;   // a single choice stays openable, so it doesn't look empty
  return chosen;
}

function refreshFilters() {
  const sectors = [...new Set(Object.values(SECTOR_OF))].sort();
  state.sector = fill($('f-sector'), sectors.map(s => ({ value: s, label: prettyDataset(s) })), state.sector);

  const datasets = [...INDEX.keys()].filter(d => SECTOR_OF[d] === state.sector).sort();
  state.dataset = fill($('f-dataset'), datasets.map(d => ({ value: d, label: prettyDataset(d) })), state.dataset);

  const entries = [...INDEX.get(state.dataset).values()];
  const cats = [...new Set(entries.map(e => e.category))];
  state.category = fill($('f-category'), cats.map(c => ({ value: c, label: c })), state.category);

  const items = entries.filter(e => e.category === state.category).map(e => e.item);
  $('l-item').textContent = !isLivestock() ? 'Item' : bySize() ? 'Herd size' : 'Type';
  state.item = fill($('f-item'), items.map(i => ({ value: i, label: i === state.category ? '(all)' : itemLabel(i) })), state.item);

  const e = entry();
  const metrics = METRICS.filter(m => e.series[m + '|']);
  state.metric = fill($('f-metric'), metrics.map(m => ({ value: m, label: `${METRIC_LABEL[m]} (${UNITS[m]})` })), state.metric);

  const details = Object.keys(e.series).filter(k => k.startsWith('production|') && k !== 'production|').map(k => k.slice(11));
  const showDetail = state.metric === 'production' && details.length > 0;
  $('wrap-detail').hidden = !showDetail;
  state.detail = showDetail
    ? fill($('f-detail'), [{ value: ALL_USES, label: 'All uses' }, ...details.map(d => ({ value: d, label: d }))], state.detail)
    : ALL_USES;

  const years = Object.keys(seriesOf(state.metric) || {}).sort();
  state.year = fill($('f-year'), [...years].reverse().map(y => ({ value: y, label: y })), state.year);

  const modes = state.metric === 'yield' ? ['value'] : ['share', 'value'];
  state.mode = fill($('f-mode'), modes.map(m => ({ value: m, label: MODE_LABEL[m] })), state.mode);
}

function onFilterChange(ev) {
  const field = ev.target.id.replace('f-', '');
  state[field] = ev.target.value;
  render();
}

// ------------------------------------------------------------------ colour scale

const SEQ = () => [1, 2, 3, 4, 5].map(i => css('--seq-' + i));

/* Quantile classes over the regions with a value above zero (up to 4, or 5 when there
   are no zeros). Exact zeros get their own class - the lightest step - so a crop grown
   in only a few regions still spreads its colours over the regions that grow it. */
function scaleFor(values) {
  const ramp = SEQ();
  const present = values.filter(v => v != null);
  const hasZero = present.some(v => v === 0);
  const pos = present.filter(v => v > 0).sort((a, b) => a - b);
  const classes = [];                                   // [{lo, hi, color}]
  if (hasZero) classes.push({ lo: 0, hi: 0, color: ramp[0], zero: true });
  if (pos.length) {
    const k = hasZero ? 4 : 5;
    const q = p => pos[Math.min(pos.length - 1, Math.floor(p * pos.length))];
    const cuts = [];
    for (let i = 1; i < k; i++) {
      const c = q(i / k);
      if (c > pos[0] && (!cuts.length || c > cuts[cuts.length - 1])) cuts.push(c);
    }
    const edges = [pos[0], ...cuts, pos[pos.length - 1]];
    const steps = hasZero ? ramp.slice(1) : ramp;
    const n = edges.length - 1 || 1;
    for (let i = 0; i < n; i++) {
      const color = n === 1 ? steps[Math.floor(steps.length / 2)] : steps[Math.round(i * (steps.length - 1) / (n - 1))];
      classes.push({ lo: edges[i], hi: edges[Math.min(i + 1, edges.length - 1)], color });
    }
  }
  const classOf = v => {
    if (v == null) return -1;
    if (v === 0 && hasZero) return 0;
    let idx = classes.length - 1;
    for (let i = classes.length - 1; i >= 0; i--) if (!classes[i].zero && v >= classes[i].lo) { idx = i; break; }
    return idx;
  };
  return { classes, colors: classes.map(c => c.color), classOf };
}

// ------------------------------------------------------------------ map

function initMap() {
  map = L.map('map', { zoomSnap: 0.25, minZoom: 5, maxZoom: 10, attributionControl: true });
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution('© EuroGeographics · ELSTAT');
  geoLayer = L.geoJSON(GEO, {
    onEachFeature: (f, layer) => {
      layerByCode[f.properties.code] = layer;
      layer.bindTooltip('', { sticky: true, direction: 'top', offset: [0, -6] });
      layer.on({
        mouseover: () => { layer.setStyle({ weight: 2.5, color: css('--text-primary') }); layer.bringToFront(); highlightRow(f.properties.code, true); },
        mouseout: () => { styleLayer(f.properties.code); highlightRow(f.properties.code, false); },
        click: () => selectRegion(state.region === f.properties.code ? 'GR' : f.properties.code),
      });
    },
  }).addTo(map);
  fitGreece();
  new ResizeObserver(() => map.invalidateSize()).observe($('map'));
}

function fitGreece() { map.fitBounds(geoLayer.getBounds(), { padding: [16, 16] }); }

let scale = null;
function styleLayer(code) {
  const layer = layerByCode[code];
  if (!layer) return;
  const c = scale.classOf(display(code));
  const selected = state.region === code;
  layer.setStyle({
    fillColor: c < 0 ? css('--nodata') : scale.colors[c],
    fillOpacity: 1,
    color: selected ? css('--text-primary') : css('--surface-1'),
    weight: selected ? 2.5 : 1,
  });
  if (selected) layer.bringToFront();
}

function renderMap() {
  const codes = Object.keys(layerByCode);
  scale = scaleFor(codes.map(c => display(c)));
  for (const code of codes) {
    styleLayer(code);
    const name = REGIONS[code]?.name || code;
    const d = display(code);
    const raw = value(code);
    const extra = state.mode === 'share' && raw != null ? ` · ${fmt(raw)} ${UNITS[state.metric]}` : '';
    layerByCode[code].setTooltipContent(
      `<div class="tip-name">${esc(name)}</div><div class="tip-val">${fmtDisplay(d)} ${state.mode === 'share' ? '' : esc(UNITS[state.metric])}${extra}</div>`);
  }
  renderLegend();
}

function renderLegend() {
  const title = `${METRIC_LABEL[state.metric]}, ${unitLabel()} · ${state.year}`;
  const rows0 = scale.classes.map(c => {
    const label = c.zero ? 'None (0)' : c.lo === c.hi ? fmtDisplay(c.lo) : `${fmtDisplay(c.lo)} – ${fmtDisplay(c.hi)}`;
    return `<div class="row"><span class="sw" style="background:${c.color}"></span>${label}</div>`;
  });
  let rows = rows0.reverse().join('');
  rows += `<div class="row"><span class="sw" style="background:${css('--nodata')}"></span>No data</div>`;
  $('legend').innerHTML = `<h4>${esc(title)}</h4>${rows}`;
}

/* Selecting a region outlines it and fills the panel; the map keeps all of Greece in view
   (regional units have no shapes yet, so there is nothing to zoom into). */
function selectRegion(code) {
  state.region = code;
  render();
}

// ------------------------------------------------------------------ side panel

function renderPanel() {
  const code = state.region;
  const reg = REGIONS[code] || { name: 'Greece', level: 'country' };
  const e = entry();
  $('back').hidden = code === 'GR';
  $('p-title').textContent = reg.name;
  const parts = [e.category];
  if (e.item !== e.category) parts.push(itemLabel(e.item));
  if (state.metric === 'production' && state.detail) parts.push(state.detail);
  $('p-sub').textContent = `${parts.join(' · ')} · ${state.year}`;

  // tiles: every metric of the item (area, production, yield / holdings) for the place, + share of Greece
  const tiles = [];
  for (const m of METRICS) {
    if (!e.series[m + '|']) continue;
    const label = m === 'production' && e.summedUses && !state.detail ? 'Production (all uses)' : METRIC_LABEL[m];
    tiles.push(`<div class="tile"><div class="k">${label}</div><div class="v">${fmt(value(code, m), m)}</div><div class="u">${UNITS[m]}</div></div>`);
  }
  if (code !== 'GR' && state.metric !== 'yield') {
    const v = value(code), t = value('GR');
    tiles.push(`<div class="tile"><div class="k">Share of Greece</div><div class="v">${fmtPct(v != null && t ? v / t * 100 : null)}</div><div class="u">${METRIC_LABEL[state.metric].toLowerCase()}</div></div>`);
  }
  $('p-tiles').innerHTML = tiles.join('');

  renderTrend(code);
  renderShareTable(code);
  renderList(code);
  renderIssues();
}

// ------------------------------------------------------------------ anomaly flags (data/anomalies.json)

const KIND_LABEL = {
  spike: 'One-year spike or dip', share_shift: 'Share of Greece left its usual range',
  hard_change: 'Hard change in the national total', appeared: 'Appeared', disappeared: 'Disappeared',
  yield_out_of_range: 'Yield far outside the usual range', yield_change: 'Yield moved differently from Greece',
  name_gap: 'Crop name missing in some years',
};
const metricMatch = (im, m) => im === m || (im === 'area+production' && (m === 'area' || m === 'production'));
const cropIssues = () => ISSUES.filter(i => i.dataset === state.dataset && i.category === state.category && i.item === state.item);
function flagFor(code, year) {
  const detail = state.metric === 'production' ? state.detail : '';
  return cropIssues().find(i => i.region_code === code && String(i.year) === String(year)
    && metricMatch(i.metric, state.metric) && (i.detail || '') === detail);
}

/* Regions (or a region's units) x years: share of Greece's total, or yield relative to
   Greece's yield. Cells flagged by the anomaly scan are marked. */
function renderShareTable(code) {
  const years = Object.keys(seriesOf(state.metric) || {}).sort();
  $('b-share').hidden = years.length < 2;
  if (years.length < 2) return;
  const isYield = state.metric === 'yield';
  $('p-share-title').textContent = isYield ? "Yield relative to Greece's, by year" : 'Share of Greece by year';
  const cell = (c, y) => {
    const v = value(c, state.metric, y), g = value('GR', state.metric, y);
    if (v == null || !g) return '—';
    return isYield ? '×' + nf(2).format(v / g) : fmtPct(v / g * 100);
  };
  const last = years[years.length - 1];
  const kids = Object.values(REGIONS).filter(r => r.parent === code)
    .sort((a, b) => (value(b.code, state.metric, last) ?? -1) - (value(a.code, state.metric, last) ?? -1));
  const rows = code === 'GR' ? kids : [REGIONS[code], ...kids];
  const head = `<tr><th></th>${years.map(y => `<th class="num">${y}</th>`).join('')}</tr>`;
  const body = rows.map(r => `<tr class="${r.code === code ? 'self' : r.level === 'region' ? 'click' : ''}" data-code="${r.code}">
      <td>${esc(r.name)}</td>${years.map(y => {
        const f = flagFor(r.code, y);
        return `<td class="num${f ? ' flag' : ''}"${f ? ` title="${esc(KIND_LABEL[f.kind] + ': ' + f.note)}"` : ''}>${cell(r.code, y)}</td>`;
      }).join('')}</tr>`).join('');
  $('p-share').innerHTML = head + body;
  $('p-share').querySelectorAll('tr.click').forEach(tr => { tr.onclick = () => selectRegion(tr.dataset.code); });
  const nFlags = rows.reduce((n, r) => n + years.filter(y => flagFor(r.code, y)).length, 0);
  $('p-share-note').textContent = (isYield
    ? "×1.00 = same yield as Greece. A place's ratio is usually stable; a jump points to a local event or an error."
    : "A place's share of Greece is usually stable for a crop; national ups and downs cancel out.")
    + (nFlags ? ` ⚠ = flagged by the anomaly scan (hover for details).` : '');
}

/* All flags for the selected crop (any metric, any place); click to jump there. */
function renderIssues() {
  const list = cropIssues().filter(i => i.kind !== 'name_gap');
  $('b-issues').hidden = !list.length;
  if (!list.length) return;
  const shown = list.slice(0, 15);
  $('p-issues').innerHTML = shown.map((i, n) => {
    const yrs = i.year_from ? `${i.year_from}→${i.year}` : i.year;
    const metric = i.metric === 'area+production' ? 'area & production' : i.metric;
    return `<button type="button" class="issue" data-n="${n}">
      <div class="t">⚠ ${esc(i.region)} · ${esc(metric)} · ${yrs}<span class="sev ${i.severity}">${i.severity}</span></div>
      <div class="n">${esc(KIND_LABEL[i.kind] || i.kind)}. ${esc(i.note)}</div></button>`;
  }).join('') + (list.length > shown.length ? `<p class="note">…and ${list.length - shown.length} more in data/anomalies.md</p>` : '');
  $('p-issues').querySelectorAll('.issue').forEach(btn => {
    btn.onclick = () => {
      const i = shown[Number(btn.dataset.n)];
      state.metric = i.metric === 'area+production' ? (state.metric === 'production' ? 'production' : 'area') : i.metric;
      state.detail = i.detail || '';
      state.year = String(i.year);
      const r = REGIONS[i.region_code];
      state.region = !r || r.level === 'country' ? 'GR' : r.level === 'unit' ? r.parent : r.code;
      render();
    };
  });
}

function renderList(code) {
  const kids = Object.values(REGIONS).filter(r => r.parent === code);
  const isYield = state.metric === 'yield';
  $('p-list-title').textContent = code === 'GR' ? 'Regions' : `Regional units of ${REGIONS[code].name}`;
  if (!kids.some(k => value(k.code) != null)) {
    $('p-list').innerHTML = `<tr><td class="note">${code === 'GR' ? 'No regional values' : 'This table has no regional-unit values'}.</td></tr>`;
    return;
  }
  const rows = kids.map(k => {
    const v = value(k.code);
    const t = value(code);
    return { k, v, share: !isYield && v != null && t ? v / t * 100 : null };
  }).sort((a, b) => (b.v ?? -1) - (a.v ?? -1));
  const max = Math.max(...rows.map(r => r.v ?? 0), 0);
  const head = `<tr><th>${code === 'GR' ? 'Region' : 'Unit'}</th><th class="num">${esc(UNITS[state.metric])}</th>` +
    `<th class="num">${isYield ? '' : '% of ' + esc(code === 'GR' ? 'Greece' : 'region')}</th><th></th></tr>`;
  const body = rows.map(({ k, v, share }) => {
    const w = isYield ? (max ? (v ?? 0) / max * 100 : 0) : (share ?? 0);
    const clickable = k.level === 'region';
    return `<tr data-code="${k.code}" class="${clickable ? 'click' : ''}">
      <td>${esc(k.name)}</td><td class="num">${fmt(v)}</td><td class="num">${isYield ? '' : fmtPct(share)}</td>
      <td class="barcell"><div class="bar" style="width:${Math.max(0, Math.min(100, w))}%"></div></td></tr>`;
  }).join('');
  $('p-list').innerHTML = head + body;
  $('p-list').querySelectorAll('tr.click').forEach(tr => {
    tr.onclick = () => selectRegion(tr.dataset.code);
    tr.onmouseenter = () => layerByCode[tr.dataset.code]?.setStyle({ weight: 2.5, color: css('--text-primary') });
    tr.onmouseleave = () => styleLayer(tr.dataset.code);
  });
}

function highlightRow(code, on) {
  $('p-list').querySelector(`tr[data-code="${code}"]`)?.classList.toggle('hover', on);
}

/* Trend: yield -> kg/stremma for both lines; area/production -> % change since the first
   year, so a region and Greece (very different sizes) share one axis. Needs two years. */
function renderTrend(code) {
  const years = Object.keys(seriesOf(state.metric) || {}).sort();
  if (years.length < 2) {
    $('p-trend').innerHTML = `<p class="note">Only ${years[0] || 'one year'} is loaded. The trend appears when files for more years are added to raw_data/.</p>`;
    return;
  }
  const isYield = state.metric === 'yield';
  const line = c => {
    const pts = years.map(y => [Number(y), value(c, state.metric, y)]);
    if (isYield) return pts;
    const base = pts.find(p => p[1] != null)?.[1];
    return pts.map(([y, v]) => [y, v != null && base ? (v / base - 1) * 100 : null]);
  };
  const series = [{ name: 'Greece', color: css('--series-greece'), pts: line('GR') }];
  if (code !== 'GR') series.unshift({ name: REGIONS[code].name, color: css('--series-region'), pts: line(code) });
  const yLabel = isYield ? 'kg/stremma' : `% change since ${years[0]}`;
  const fmtChange = v => (v > 0 ? '+' : v < 0 ? '−' : '') + nf(1).format(Math.abs(v)) + '%';
  $('p-trend').innerHTML = lineChart(series, yLabel, isYield ? v => nf(0).format(v) : fmtChange, !isYield);
}

/* Round tick values (1, 2 or 5 x 10^k steps) inside [lo, hi]; 0 is a tick whenever it is in range. */
function niceTicks(lo, hi, target = 4) {
  const raw = (hi - lo) / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map(s => s * mag).find(s => s >= raw) || raw;
  const ticks = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) ticks.push(Math.abs(t) < step / 1e6 ? 0 : t);
  return ticks;
}

function lineChart(series, yLabel, fmtY, isChange = false) {
  const W = 340, H = 170, m = { l: 40, r: 10, t: 10, b: 24 };
  const all = series.flatMap(s => s.pts).filter(p => p[1] != null);
  const xs = all.map(p => p[0]), ys = all.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (isChange) { y0 = Math.min(y0, 0); y1 = Math.max(y1, 0); }   // keep the 0% line in view
  const pad = (y1 - y0) * 0.1 || Math.abs(y1) * 0.1 || 1;
  y0 = isChange ? y0 - pad : Math.max(0, y0 - pad); y1 += pad;
  const X = x => m.l + (x1 === x0 ? 0.5 : (x - x0) / (x1 - x0)) * (W - m.l - m.r);
  const Y = y => H - m.b - (y - y0) / (y1 - y0) * (H - m.t - m.b);
  const ticks = niceTicks(y0, y1);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Trend, ${esc(yLabel)}">`;
  for (const t of ticks) {
    const zero = isChange && t === 0;
    svg += `<line class="${zero ? 'zero' : 'axis'}" x1="${m.l}" x2="${W - m.r}" y1="${Y(t)}" y2="${Y(t)}"/>` +
           `<text${zero ? ' class="lbl"' : ''} x="${m.l - 6}" y="${Y(t) + 4}" text-anchor="end">${zero ? '0%' : fmtY(t)}</text>`;
  }
  for (const x of [...new Set(xs)]) svg += `<text x="${X(x)}" y="${H - 6}" text-anchor="middle">${x}</text>`;
  for (const s of series) {
    const pts = s.pts.filter(p => p[1] != null);
    svg += `<polyline fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" points="${pts.map(p => `${X(p[0])},${Y(p[1])}`).join(' ')}"/>`;
    for (const p of pts) svg += `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="4" fill="${s.color}" stroke="var(--surface-1)" stroke-width="2"><title>${esc(s.name)} ${p[0]}: ${fmtY(p[1])}</title></circle>`;
  }
  svg += '</svg>';
  const legend = series.map(s => `<span style="--c:${s.color}">${esc(s.name)}</span>`).join('');
  return `<div class="chart">${svg}<div class="chart-legend">${legend}<span style="--c:transparent">${esc(yLabel)}</span></div></div>`;
}

// ------------------------------------------------------------------ state <-> URL

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  for (const k of Object.keys(state)) if (p.has(k)) state[k] = p.get(k);
  if (!REGIONS[state.region]) state.region = 'GR';
}
function writeHash() {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(state)) if (v) p.set(k, v);
  history.replaceState(null, '', '#' + p.toString());
}

// ------------------------------------------------------------------ main

function render() {
  refreshFilters();
  if (REGIONS[state.region]?.level === 'unit') state.region = REGIONS[state.region].parent;
  renderMap();
  renderPanel();
  writeHash();
}

async function main() {
  try {
    const [records, geo] = await Promise.all([
      fetch(DATA_URL, { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(`${DATA_URL}: HTTP ${r.status}`); return r.json(); }),
      fetch(GEO_URL).then(r => { if (!r.ok) throw new Error(`${GEO_URL}: HTTP ${r.status}`); return r.json(); }),
    ]);
    buildIndex(records);
    GEO = geo;
    // anomaly flags are optional: the page works without them
    ISSUES = await fetch(ISSUES_URL, { cache: 'no-cache' }).then(r => (r.ok ? r.json() : [])).catch(() => []);
  } catch (err) {
    $('status').textContent = `Could not load data (${err.message}). Serve the project folder over HTTP: ` +
      'python -m http.server 8000, then open http://localhost:8000/dashboard/';
    return;
  }
  REGIONS.GR ||= { code: 'GR', name: 'Greece', level: 'country', parent: null };
  readHash();
  initMap();
  $('filters').addEventListener('change', onFilterChange);
  $('back').onclick = () => selectRegion('GR');
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', render);
  $('status').textContent = '';
  render();
}

main();
