(function(){
  'use strict';

  const $ = (sel, root=document) => root.querySelector(sel);
  const $$ = (sel, root=document) => [...root.querySelectorAll(sel)];

  // ── State ─────────────────────────────────────────────────────────
  let importedWells = null;
  let correlationResult = null;
  let selectedDemo = null;
  let wellDetails = [];  // per-well data for log preview

  // ── DOM refs ──────────────────────────────────────────────────────
  const tabs = $$('.wc-tab');
  const bodies = $$('.wc-body');
  const healthDot = $('#health-dot');
  const healthTxt = $('#health-text');

  // Data tab
  const dsFilterInput = $('#ds-filter-input');
  const dsList = $('#ds-list');
  const dsInput = $('#wc-dataspace');
  const btnImport = $('#btn-import');
  const btnRefreshDs = $('#btn-refresh-ds');
  const importSpin = $('#import-spinner');
  const importStat = $('#import-status');
  const wellsSumm = $('#wells-summary');
  const wellCount = $('#well-count');
  const wellChips = $('#well-chips');
  const dataNames = $('#data-names');
  const regionNames = $('#region-names');
  const demoGrid = $('#demo-grid');

  // Log tab
  const logWellList = $('#log-well-list');
  const logChannelSel = $('#log-channel-select');
  const logRegionSel = $('#log-region-select');
  const logCanvas = $('#log-canvas');

  // Params tab
  const paramPreset = $('#param-preset');
  const showAdv = $('#show-advanced');
  const btnSuggest = $('#btn-suggest');
  const suggestSt = $('#suggest-status');

  // Run tab
  const runSummary = $('#run-summary');
  const btnRun = $('#btn-run');
  const btnRunDemo = $('#btn-run-demo');
  const runSpin = $('#run-spinner');
  const runProgress = $('#run-progress');
  const runError = $('#run-error');
  const engineLog = $('#engine-log');

  // Results tab
  const resEmpty = $('#results-empty');
  const resSummary = $('#results-summary');
  const resNWells = $('#res-n-wells');
  const resNRes = $('#res-n-results');
  const resElapsed = $('#res-elapsed');
  const resMode = $('#res-mode');
  const resSelector = $('#res-selector');
  const resCards = $('#results-cards');

  // Export tab
  const btnExportRddms = $('#btn-export-rddms');
  const btnExportJson = $('#btn-export-json');
  const btnExportCsv = $('#btn-export-csv');
  const exportStatus = $('#export-status');

  // ── Tab switching ─────────────────────────────────────────────────
  function switchTab(name) {
    tabs.forEach(t => {
      const isTarget = t.dataset.tab === name;
      t.classList.toggle('active', isTarget);
      if (isTarget) t.classList.remove('disabled');
    });
    bodies.forEach(b => b.classList.toggle('active', b.id === 'tab-' + name));
  }
  tabs.forEach(t => t.addEventListener('click', () => {
    if (!t.classList.contains('disabled')) switchTab(t.dataset.tab);
  }));

  // ── API helpers ───────────────────────────────────────────────────
  async function api(method, path, body) {
    const opts = { method, headers: {'Content-Type': 'application/json'} };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch('/weco' + path, opts);
    if (!resp.ok) {
      const txt = await resp.text();
      throw new Error(txt || `HTTP ${resp.status}`);
    }
    return resp.json();
  }

  function setStatus(el, cls, msg) {
    el.className = 'wc-status ' + cls;
    el.textContent = msg;
    el.style.display = msg ? 'block' : 'none';
  }

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
  }

  // ── Health check ──────────────────────────────────────────────────
  async function checkHealth() {
    try {
      const d = await api('GET', '/health');
      healthDot.className = 'health-dot ' + (d.connected ? 'ok' : 'err');
      healthTxt.textContent = d.connected
        ? `Engine OK (v${d.version})`
        : 'Engine unavailable';
    } catch(e) {
      healthDot.className = 'health-dot err';
      healthTxt.textContent = 'Engine check failed';
    }
  }
  checkHealth();

  // ── Dataspace list ────────────────────────────────────────────────
  let allDataspaces = [];

  async function loadDataspaces() {
    try {
      const d = await api('GET', '/dataspaces');
      allDataspaces = (d.dataspaces || []).map(ds =>
        typeof ds === 'string' ? ds : (ds.DataspaceId || ds.id || ds.name || JSON.stringify(ds))
      );
      renderDataspaces();
    } catch(e) {
      dsList.innerHTML = '<div class="muted" style="padding:4px; font-size:12px;">Could not load dataspaces</div>';
    }
  }

  function renderDataspaces(filter) {
    const filt = (filter || '').toLowerCase();
    const items = filt ? allDataspaces.filter(d => d.toLowerCase().includes(filt)) : allDataspaces;
    dsList.innerHTML = items.map(d =>
      `<div class="ds-item" data-ds="${esc(d)}">${esc(d)}</div>`
    ).join('') || '<div class="muted" style="padding:4px; font-size:12px;">No dataspaces</div>';
  }

  dsList.addEventListener('click', e => {
    const item = e.target.closest('.ds-item');
    if (!item) return;
    dsInput.value = item.dataset.ds;
    $$('.ds-item', dsList).forEach(i => i.classList.remove('active'));
    item.classList.add('active');
  });

  dsFilterInput.addEventListener('input', () => renderDataspaces(dsFilterInput.value));
  btnRefreshDs.addEventListener('click', loadDataspaces);
  loadDataspaces();

  // ── Import wells ──────────────────────────────────────────────────
  btnImport.addEventListener('click', async () => {
    importSpin.style.display = 'inline';
    setStatus(importStat, '', '');
    try {
      const data = await api('POST', '/import', {
        dataspace: dsInput.value.trim() || null
      });
      importedWells = data;
      showWellsSummary(data);
      setStatus(importStat, 'ok', `Imported ${data.well_count} wells (${(data.data_names||[]).length} logs, ${(data.region_names||[]).length} regions)`);
      enableAfterImport();
    } catch(e) {
      setStatus(importStat, 'err', 'Import failed: ' + e.message);
    } finally {
      importSpin.style.display = 'none';
    }
  });

  function showWellsSummary(data) {
    wellsSumm.style.display = 'block';
    wellCount.textContent = data.well_count;
    wellChips.innerHTML = (data.well_names || [])
      .map(n => `<span class="well-chip">${esc(n)}</span>`).join('');
    dataNames.textContent = (data.data_names || []).join(', ') || '(none)';
    regionNames.textContent = (data.region_names || []).join(', ') || '(none)';
    populateDropdowns(data.data_names || [], data.region_names || []);
    populateLogSelectors(data.data_names || [], data.region_names || []);
    updateLogWellList(data.well_names || []);
    runSummary.textContent = `${data.well_count} wells loaded | Logs: ${(data.data_names||[]).join(', ')} | Regions: ${(data.region_names||[]).join(', ')}`;
  }

  function enableAfterImport() {
    btnRun.disabled = false;
    tabs.forEach(t => {
      if (['logs', 'params', 'run'].includes(t.dataset.tab)) t.classList.remove('disabled');
    });
  }

  function populateDropdowns(dataLogs, regions) {
    const dataSelects = ['#p-var-data', '#p-var-data2'];
    const regionSelects = ['#p-no-crossing', '#p-same-region', '#p-polarity-region',
                           '#p-dist-distal', '#p-dist-facies'];
    dataSelects.forEach(sel => {
      const el = $(sel);
      if (!el) return;
      el.innerHTML = '<option value="">-- select --</option>';
      dataLogs.forEach(n => { el.innerHTML += `<option value="${esc(n)}">${esc(n)}</option>`; });
    });
    regionSelects.forEach(sel => {
      const el = $(sel);
      if (!el) return;
      el.innerHTML = '<option value="">-- none --</option>';
      regions.forEach(n => { el.innerHTML += `<option value="${esc(n)}">${esc(n)}</option>`; });
    });
    // Auto-select first data log
    if (dataLogs.length > 0) {
      const el = $('#p-var-data');
      if (el) el.value = dataLogs[0];
    }
  }

  // ── Demo datasets ─────────────────────────────────────────────────
  async function loadDemos() {
    try {
      const demos = await api('GET', '/demos');
      const items = Array.isArray(demos) ? demos : (demos.demos || []);
      if (!items.length) {
        demoGrid.innerHTML = '<div class="muted">No demos available</div>';
        return;
      }
      demoGrid.innerHTML = items.map(d => `
        <div class="demo-card" data-id="${esc(d.id || d.demo_id || '')}">
          <h4>${esc(d.title || d.name || d.id || '?')}</h4>
          <p>${esc(d.description || '')}</p>
          <div class="demo-meta">${d.n_wells || '?'} wells | ${d.group || ''}</div>
        </div>
      `).join('');
    } catch(e) {
      demoGrid.innerHTML = '<div class="muted">Could not load demos</div>';
    }
  }

  demoGrid.addEventListener('click', e => {
    const card = e.target.closest('.demo-card');
    if (!card) return;
    $$('.demo-card', demoGrid).forEach(c => c.classList.remove('active'));
    card.classList.add('active');
    selectedDemo = card.dataset.id;
    btnRunDemo.style.display = 'inline-block';
    btnRunDemo.textContent = `\u25B6 Run "${selectedDemo}"`;
  });
  loadDemos();

  // ── Log preview ───────────────────────────────────────────────────
  function populateLogSelectors(dataLogs, regions) {
    logChannelSel.innerHTML = dataLogs.map(n =>
      `<option value="${esc(n)}">${esc(n)}</option>`
    ).join('') || '<option value="">-- no logs --</option>';
    logRegionSel.innerHTML = '<option value="">-- none --</option>' +
      regions.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
  }

  function updateLogWellList(names) {
    logWellList.innerHTML = names.map((n, i) =>
      `<div class="well-chip" data-idx="${i}">${esc(n)}</div>`
    ).join('');
  }

  logWellList.addEventListener('click', e => {
    const chip = e.target.closest('.well-chip');
    if (!chip) return;
    $$('.well-chip', logWellList).forEach(c => c.classList.remove('selected'));
    chip.classList.add('selected');
    drawLogPreview(parseInt(chip.dataset.idx));
  });

  logChannelSel.addEventListener('change', () => {
    const sel = $('.well-chip.selected', logWellList);
    if (sel) drawLogPreview(parseInt(sel.dataset.idx));
  });

  logRegionSel.addEventListener('change', () => {
    const sel = $('.well-chip.selected', logWellList);
    if (sel) drawLogPreview(parseInt(sel.dataset.idx));
  });

  async function drawLogPreview(wellIdx) {
    const canvas = logCanvas;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, rect.width, rect.height);

    // Fetch well detail if not cached
    if (!wellDetails.length) {
      try {
        const info = await api('GET', '/wells');
        wellDetails = info.wells || [];
      } catch(e) {
        ctx.fillStyle = '#c62828';
        ctx.font = '13px sans-serif';
        ctx.fillText('Could not load well data', 10, 30);
        return;
      }
    }

    const well = wellDetails[wellIdx];
    if (!well) return;

    const channel = logChannelSel.value;
    if (!channel || !well.data_names.includes(channel)) {
      ctx.fillStyle = '#605e5c';
      ctx.font = '13px sans-serif';
      ctx.fillText(`No "${channel}" data for ${well.name}`, 10, 30);
      return;
    }

    // We need actual values — request from a lightweight endpoint
    // For now show placeholder with well info
    ctx.fillStyle = '#333';
    ctx.font = 'bold 13px sans-serif';
    ctx.fillText(`${well.name} — ${channel}`, 10, 20);
    ctx.font = '12px sans-serif';
    ctx.fillStyle = '#605e5c';
    ctx.fillText(`${well.size} samples | Depth range available`, 10, 38);
    ctx.fillText(`Available logs: ${well.data_names.join(', ')}`, 10, 55);
    if (well.region_names.length)
      ctx.fillText(`Regions: ${well.region_names.join(', ')}`, 10, 72);

    // Draw a simple representation
    const margin = {top:85, bottom:20, left:40, right:20};
    const w = rect.width - margin.left - margin.right;
    const h = rect.height - margin.top - margin.bottom;

    // Axes
    ctx.strokeStyle = '#e1dfdd';
    ctx.beginPath();
    ctx.moveTo(margin.left, margin.top);
    ctx.lineTo(margin.left, margin.top + h);
    ctx.lineTo(margin.left + w, margin.top + h);
    ctx.stroke();

    ctx.fillStyle = '#605e5c';
    ctx.font = '10px sans-serif';
    ctx.fillText('Depth', 5, margin.top + h/2);
    ctx.fillText(channel, margin.left + w/2 - 10, margin.top + h + 15);
  }

  // ── Advanced toggle ───────────────────────────────────────────────
  showAdv.addEventListener('change', () => {
    const show = showAdv.checked;
    $$('.adv').forEach(el => { el.style.display = show ? '' : 'none'; });
  });

  // ── Auto-suggest ──────────────────────────────────────────────────
  btnSuggest.addEventListener('click', async () => {
    suggestSt.textContent = 'Analyzing...';
    try {
      const data = await api('POST', '/suggest-defaults');
      if (data.options) {
        applyOptions(data.options);
        suggestSt.textContent = '\u2713 Applied';
      } else {
        suggestSt.textContent = 'No suggestions';
      }
    } catch(e) {
      suggestSt.textContent = 'Failed';
    }
  });

  function applyOptions(opts) {
    const map = {
      'var-data': '#p-var-data', 'var-weight': '#p-var-weight',
      'var-data2': '#p-var-data2', 'var-weight2': '#p-var-weight2',
      'no-crossing': '#p-no-crossing', 'same-region': '#p-same-region',
      'polarity-region': '#p-polarity-region',
      'const-gap-cost': '#p-gap-cost',
      'dist-distal': '#p-dist-distal', 'dist-facies': '#p-dist-facies',
      'band-width': '#p-band-width', 'max-cor': '#p-max-cor',
    };
    for (const [key, sel] of Object.entries(map)) {
      if (opts[key] !== undefined) {
        const el = $(sel);
        if (el) el.value = opts[key];
      }
    }
  }

  // ── Preset handling ───────────────────────────────────────────────
  paramPreset.addEventListener('change', () => {
    const preset = paramPreset.value;
    if (!preset) return;
    const presets = {
      simple: {'var-weight': 1.0},
      constrained: {'var-weight': 1.0},
      distality: {'var-weight': 1.0},
      'multi-log': {'var-weight': 0.6, 'var-weight2': 0.4},
    };
    if (presets[preset]) applyOptions(presets[preset]);
  });

  // ── Run correlation ───────────────────────────────────────────────
  btnRun.addEventListener('click', () => runCorrelation());
  btnRunDemo.addEventListener('click', () => runDemo());

  async function runCorrelation() {
    runSpin.style.display = 'inline';
    runProgress.style.display = 'block';
    runProgress.classList.add('indeterminate');
    setStatus(runError, '', '');
    btnRun.disabled = true;
    engineLog.textContent = 'Starting correlation engine...\n';

    const options = gatherOptions();
    const nBest = parseInt($('#p-n-best').value) || 5;

    try {
      engineLog.textContent += `Options: ${JSON.stringify(options)}\nN-best: ${nBest}\n`;
      const data = await api('POST', '/run', { options, n_best: nBest });
      correlationResult = data;
      engineLog.textContent += `\nCompleted: ${data.n_results} solutions in ${data.elapsed_ms} ms\n`;
      engineLog.textContent += `Mode: ${data.mode || 'in-process'}\n`;
      showResults(data);
      enableResultsTabs();
      switchTab('results');
    } catch(e) {
      setStatus(runError, 'err', 'Correlation failed: ' + e.message);
      engineLog.textContent += `\nERROR: ${e.message}\n`;
    } finally {
      runSpin.style.display = 'none';
      runProgress.style.display = 'none';
      runProgress.classList.remove('indeterminate');
      btnRun.disabled = false;
    }
  }

  async function runDemo() {
    if (!selectedDemo) return;
    runSpin.style.display = 'inline';
    runProgress.style.display = 'block';
    runProgress.classList.add('indeterminate');
    setStatus(runError, '', '');
    engineLog.textContent = `Running demo "${selectedDemo}"...\n`;
    switchTab('run');

    const nBest = parseInt($('#p-n-best').value) || 5;
    try {
      const data = await api('POST', `/run/demo?demo_id=${encodeURIComponent(selectedDemo)}&n_best=${nBest}`);
      correlationResult = data;
      engineLog.textContent += `\nCompleted: ${data.n_results || '?'} solutions\n`;
      showResults(data);
      enableResultsTabs();
      switchTab('results');
    } catch(e) {
      setStatus(runError, 'err', 'Demo failed: ' + e.message);
      engineLog.textContent += `\nERROR: ${e.message}\n`;
    } finally {
      runSpin.style.display = 'none';
      runProgress.style.display = 'none';
      runProgress.classList.remove('indeterminate');
    }
  }

  function gatherOptions() {
    const opts = {};
    const val = (sel) => { const el = $(sel); return el ? el.value : ''; };

    if (val('#p-var-data'))  opts['var-data'] = val('#p-var-data');
    const w1 = parseFloat(val('#p-var-weight'));
    if (!isNaN(w1) && w1 !== 1.0) opts['var-weight'] = w1;
    if (val('#p-no-crossing'))  opts['no-crossing'] = val('#p-no-crossing');
    if (val('#p-same-region'))  opts['same-region'] = val('#p-same-region');
    if (val('#p-var-data2'))  opts['var-data2'] = val('#p-var-data2');
    const w2 = parseFloat(val('#p-var-weight2'));
    if (val('#p-var-data2') && !isNaN(w2)) opts['var-weight2'] = w2;
    const gc = parseFloat(val('#p-gap-cost'));
    if (!isNaN(gc) && gc !== 0) opts['const-gap-cost'] = gc;
    if (val('#p-polarity-region'))  opts['polarity-region'] = val('#p-polarity-region');
    if (val('#p-dist-distal'))  opts['dist-distal'] = val('#p-dist-distal');
    if (val('#p-dist-facies'))  opts['dist-facies'] = val('#p-dist-facies');
    const bw = parseInt(val('#p-band-width'));
    if (!isNaN(bw) && bw > 0) opts['band-width'] = bw;
    const mc = parseInt(val('#p-max-cor'));
    if (!isNaN(mc) && mc > 0 && mc !== 50) opts['max-cor'] = mc;

    return opts;
  }

  function enableResultsTabs() {
    tabs.forEach(t => {
      if (['results', 'export'].includes(t.dataset.tab)) t.classList.remove('disabled');
    });
  }

  // ── Results display ───────────────────────────────────────────────
  function showResults(data) {
    resEmpty.style.display = 'none';
    resSummary.style.display = 'block';
    resNWells.textContent = data.n_wells || '?';
    resNRes.textContent = data.n_results || 0;
    resElapsed.textContent = data.elapsed_ms || '-';
    resMode.textContent = data.mode || 'in-process';

    const results = data.results || [];
    // Populate selector
    resSelector.innerHTML = results.map((r, i) =>
      `<option value="${i}">#${i+1} (cost: ${r.cost != null ? r.cost.toFixed(4) : '-'})</option>`
    ).join('');

    renderResultCard(results, 0, data.well_names);
    resSelector.addEventListener('change', () => {
      renderResultCard(results, parseInt(resSelector.value), data.well_names);
    });
  }

  function renderResultCard(results, idx, wellNames) {
    if (!results[idx]) { resCards.innerHTML = ''; return; }
    const r = results[idx];
    let html = `
      <div class="result-card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span class="result-rank">#${idx+1}</span>
          <span class="result-cost">Total Cost: ${r.cost != null ? r.cost.toFixed(4) : '-'}</span>
        </div>
        ${renderCorrelationTable(r, wellNames)}
      </div>
    `;
    resCards.innerHTML = html;
  }

  function renderCorrelationTable(result, wellNames) {
    if (!result.markers && !result.correlation) return '';
    const markers = result.markers || result.correlation || [];
    const names = wellNames || [];
    if (!markers.length) return '';

    let html = '<table class="corr-table"><thead><tr><th>Marker</th>';
    names.forEach(n => { html += `<th>${esc(n)}</th>`; });
    html += '</tr></thead><tbody>';

    if (Array.isArray(markers)) {
      markers.forEach((row, mi) => {
        html += '<tr>';
        html += `<td style="font-weight:600;">${mi + 1}</td>`;
        if (Array.isArray(row)) {
          row.forEach(v => { html += `<td>${v != null ? v : '-'}</td>`; });
        } else {
          html += `<td colspan="${names.length}">${esc(String(row))}</td>`;
        }
        html += '</tr>';
      });
    }
    html += '</tbody></table>';
    return html;
  }

  // ── Export ────────────────────────────────────────────────────────
  btnExportRddms.addEventListener('click', async () => {
    setStatus(exportStatus, 'info', 'Exporting to RDDMS...');
    try {
      const data = await api('POST', '/export');
      if (data.status === 'pending') {
        setStatus(exportStatus, 'warn', data.message);
      } else {
        setStatus(exportStatus, 'ok', 'Exported to RDDMS');
      }
    } catch(e) {
      setStatus(exportStatus, 'err', 'Export failed: ' + e.message);
    }
  });

  btnExportJson.addEventListener('click', () => {
    if (!correlationResult) return;
    const blob = new Blob([JSON.stringify(correlationResult, null, 2)], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'weco_results.json'; a.click();
    URL.revokeObjectURL(url);
    setStatus(exportStatus, 'ok', 'JSON downloaded');
  });

  btnExportCsv.addEventListener('click', () => {
    if (!correlationResult) return;
    const results = correlationResult.results || [];
    const names = correlationResult.well_names || [];
    if (!results.length) return;

    let csv = 'Solution,Cost,' + names.join(',') + '\n';
    results.forEach((r, i) => {
      const markers = r.markers || r.correlation || [];
      markers.forEach((row, mi) => {
        csv += `${i+1},${r.cost != null ? r.cost : ''},`;
        if (Array.isArray(row)) csv += row.map(v => v != null ? v : '').join(',');
        csv += '\n';
      });
    });

    const blob = new Blob([csv], {type:'text/csv'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'weco_markers.csv'; a.click();
    URL.revokeObjectURL(url);
    setStatus(exportStatus, 'ok', 'CSV downloaded');
  });

})();
