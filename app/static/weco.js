(function(){
  'use strict';

  const $ = (sel, root=document) => root.querySelector(sel);
  const $$ = (sel, root=document) => [...root.querySelectorAll(sel)];

  // ── State ─────────────────────────────────────────────────────────
  let importedWells = null;
  let correlationResult = null;
  let selectedDemo = null;
  let currentDemoId = '';
  let wellDetails = [];  // per-well data for log preview

  // ── DOM refs ──────────────────────────────────────────────────────
  const tabs = $$('.wc-tab');
  const bodies = $$('.wc-body');
  const healthDot = $('#health-dot');
  const healthTxt = $('#health-text');

  // Data tab
  const dsF1 = $('#ds-f1');
  const dsF2 = $('#ds-f2');
  const dsCount = $('#ds-count');
  const dsSel = $('#ds-select');
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
  const btnSelectAll = $('#btn-select-all-wells');
  const btnSelectNone = $('#btn-select-none-wells');

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
  const workflowName = $('#workflow-name');
  const btnSaveWorkflow = $('#btn-save-workflow');
  const btnLoadWorkflows = $('#btn-load-workflows');
  const workflowStatus = $('#workflow-status');
  const workflowList = $('#workflow-list');

  // Results tab
  const resEmpty = $('#results-empty');
  const resSummary = $('#results-summary');
  const resNWells = $('#res-n-wells');
  const resNRes = $('#res-n-results');
  const resElapsed = $('#res-elapsed');
  const resMode = $('#res-mode');
  const resSelector = $('#res-selector');
  const resCards = $('#results-cards');
  const btnResPrev = $('#btn-res-prev');
  const btnResNext = $('#btn-res-next');
  const resCostLabel = $('#res-cost-label');
  const resRanking = $('#res-ranking');

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
  let selectedWells = new Set(); // well names currently selected

  async function loadDataspaces() {
    try {
      const d = await api('GET', '/dataspaces');
      allDataspaces = (d.dataspaces || []).map(ds => {
        if (typeof ds === 'string') return ds;
        return ds.path || ds.DataspaceId || ds.id || ds.name || '';
      }).filter(Boolean);
      applyDsFilter();
    } catch(e) {
      dsSel.innerHTML = '<option disabled>Could not load dataspaces</option>';
    }
  }

  function applyDsFilter() {
    const q1 = (dsF1.value || '').trim().toLowerCase();
    const q2 = (dsF2.value || '').trim().toLowerCase();
    dsSel.innerHTML = '';
    let matched = 0;
    allDataspaces.forEach(path => {
      const lp = path.toLowerCase();
      const parts = lp.split('/');
      const seg1 = parts[0] || '';
      const seg2 = parts.slice(1).join('/');
      if (q1 && !seg1.includes(q1)) return;
      if (q2 && !seg2.includes(q2)) return;
      const o = document.createElement('option');
      o.value = path;
      o.textContent = path;
      dsSel.appendChild(o);
      matched++;
    });
    dsCount.textContent = (q1 || q2) ? `${matched}/${allDataspaces.length}` : `${allDataspaces.length}`;
    // Auto-select first available dataspace
    if (dsSel.options.length > 0 && !dsSel.value) {
      dsSel.selectedIndex = 0;
    }
  }

  dsF1.addEventListener('input', applyDsFilter);
  dsF2.addEventListener('input', applyDsFilter);
  btnRefreshDs.addEventListener('click', loadDataspaces);
  loadDataspaces();

  // ── Import wells ──────────────────────────────────────────────────
  btnImport.addEventListener('click', async () => {
    const ds = dsSel.value;
    if (!ds) { setStatus(importStat, 'warn', 'Select a dataspace first'); return; }
    importSpin.style.display = 'inline';
    setStatus(importStat, '', '');
    try {
      const data = await api('POST', '/import', { dataspace: ds });
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
    const names = data.well_names || [];
    wellCount.textContent = names.length;
    selectedWells = new Set(names); // select all by default
    renderWellChips(names);
    dataNames.textContent = (data.data_names || []).join(', ') || '(none)';
    regionNames.textContent = (data.region_names || []).join(', ') || '(none)';
    populateDropdowns(data.data_names || [], data.region_names || []);
    populateLogSelectors(data.data_names || [], data.region_names || []);
    updateLogWellList(names);
    runSummary.textContent = `${names.length} wells loaded | Logs: ${(data.data_names||[]).join(', ')} | Regions: ${(data.region_names||[]).join(', ')}`;
  }

  function renderWellChips(names) {
    const filter = (($('#well-filter') || {}).value || '').toLowerCase();
    wellChips.innerHTML = names.map(n => {
      const sel = selectedWells.has(n);
      if (filter && !n.toLowerCase().includes(filter)) return '';
      // Show log availability indicator if wellDetails loaded
      const wd = wellDetails.find(w => w.name === n);
      const logCount = wd ? wd.data_names.length : 0;
      const logBadge = logCount ? `<span class="log-badge">${logCount} logs</span>` : '';
      // Tooltip with metadata
      let tip = n;
      if (wd) {
        tip = `${n}\nSize: ${wd.size} pts`;
        if (wd.x !== undefined) tip += `\nX: ${wd.x.toFixed(1)}, Y: ${wd.y.toFixed(1)}, Z: ${wd.z.toFixed(1)}`;
        if (wd.data_names) tip += `\nLogs: ${wd.data_names.join(', ')}`;
        if (wd.region_names && wd.region_names.length) tip += `\nRegions: ${wd.region_names.join(', ')}`;
        if (wd.uuid) tip += `\nUUID: ${wd.uuid}`;
        if (wd.demo) tip += `\nDemo: ${wd.demo}`;
      }
      return `<span class="well-chip ${sel ? 'selected' : 'excluded'}" data-name="${esc(n)}" title="${esc(tip)}">${esc(n)} ${logBadge}</span>`;
    }).join('');
    // Click to toggle selection
    wellChips.querySelectorAll('.well-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const name = chip.dataset.name;
        if (selectedWells.has(name)) {
          selectedWells.delete(name);
          chip.classList.remove('selected');
          chip.classList.add('excluded');
        } else {
          selectedWells.add(name);
          chip.classList.add('selected');
          chip.classList.remove('excluded');
        }
        wellCount.textContent = selectedWells.size;
      });
    });
  }

  // Well filter input
  const wellFilter = $('#well-filter');
  if (wellFilter) {
    wellFilter.addEventListener('input', () => {
      const names = importedWells ? (importedWells.well_names || []) : [];
      renderWellChips(names);
    });
  }

  btnSelectAll.addEventListener('click', () => {
    wellChips.querySelectorAll('.well-chip').forEach(c => {
      selectedWells.add(c.dataset.name);
      c.classList.add('selected');
      c.classList.remove('excluded');
    });
    wellCount.textContent = selectedWells.size;
  });

  btnSelectNone.addEventListener('click', () => {
    selectedWells.clear();
    wellChips.querySelectorAll('.well-chip').forEach(c => {
      c.classList.remove('selected');
      c.classList.add('excluded');
    });
    wellCount.textContent = 0;
  });

  function enableAfterImport() {
    btnRun.disabled = false;
    tabs.forEach(t => {
      if (['logs', 'params', 'run'].includes(t.dataset.tab)) t.classList.remove('disabled');
    });
  }

  function populateDropdowns(dataLogs, regions) {
    const skip = new Set(['Depth', 'DEPTH', 'MD', 'X', 'Y', 'Z']);
    const usableLogs = dataLogs.filter(n => !skip.has(n));
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
    // Auto-select first usable log (skip Depth/X/Y/Z)
    if (usableLogs.length > 0) {
      const el = $('#p-var-data');
      if (el) el.value = usableLogs[0];
    }
    // Auto-suggest best parameters from the backend
    autoSuggest();
  }

  async function autoSuggest() {
    try {
      const data = await api('POST', '/suggest-defaults');
      if (data.options && Object.keys(data.options).length > 0) {
        applyOptions(data.options);
      }
    } catch(e) { /* silent fallback to manual selection */ }
  }

  // ── Demo datasets ─────────────────────────────────────────────────
  async function loadDemos() {
    try {
      const resp = await api('GET', '/demos');
      const items = Array.isArray(resp) ? resp : (resp.demos || []);
      if (!items.length) {
        demoGrid.innerHTML = '<div class="muted">No demos available</div>';
        return;
      }
      demoGrid.innerHTML = items.map(d => `
        <div class="demo-card" data-id="${esc(d.id || d.demo_id || '')}">
          <h4>${esc(d.title || d.name || d.id || '?')}</h4>
          <p>${esc(d.description || d.geology || '')}</p>
          <div class="demo-meta">
            ${d.n_wells || '?'} wells | ${d.group || ''}
            ${d.data_names && d.data_names.length ? ' | Logs: ' + d.data_names.join(', ') : ''}
          </div>
        </div>
      `).join('');
    } catch(e) {
      demoGrid.innerHTML = '<div class="muted">Could not load demos</div>';
    }
  }

  demoGrid.addEventListener('click', async e => {
    const card = e.target.closest('.demo-card');
    if (!card) return;
    $$('.demo-card', demoGrid).forEach(c => c.classList.remove('active'));
    card.classList.add('active');
    selectedDemo = card.dataset.id;
    currentDemoId = selectedDemo;
    btnRunDemo.style.display = 'inline-block';
    btnRunDemo.textContent = `\u25B6 Run "${selectedDemo}"`;

    // Also check if this can be imported from RDDMS
    const btnRddms = $('#btn-import-demo-rddms');
    if (btnRddms) {
      btnRddms.style.display = 'inline-block';
      btnRddms.textContent = `Import "${selectedDemo}" from RDDMS`;
      btnRddms.onclick = () => importDemoFromRddms(selectedDemo);
    }

    // Load wells for this demo (new: shows well/log matrix before running)
    setStatus(importStat, 'info', `Loading wells for "${selectedDemo}"...`);
    try {
      const data = await api('GET', `/demos/${encodeURIComponent(selectedDemo)}/wells`);
      importedWells = data;
      showWellsSummary({
        well_count: data.n_wells,
        well_names: data.wells.map(w => w.name),
        data_names: data.all_data_names || [],
        region_names: data.all_region_names || [],
      });
      // Show per-well log availability
      wellDetails = data.wells;
      enableAfterImport();
      setStatus(importStat, 'ok', `${data.n_wells} wells loaded from demo "${selectedDemo}" — select wells & logs, then Run`);
    } catch(e) {
      setStatus(importStat, 'warn', `Could not pre-load demo wells: ${e.message}`);
    }
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
      // Show available logs for this well
      ctx.fillText(`Available: ${well.data_names.join(', ')}`, 10, 50);
      return;
    }

    // Fetch actual log values
    try {
      const resp = await api('GET', `/well-data/${wellIdx}?channel=${encodeURIComponent(channel)}`);
      const values = resp.values || [];
      const depth = resp.depth || [];

      ctx.fillStyle = '#333';
      ctx.font = 'bold 13px sans-serif';
      ctx.fillText(`${well.name} — ${channel} (${values.length} samples)`, 10, 20);

      if (!values.length) return;

      const margin = {top: 40, bottom: 20, left: 50, right: 20};
      const w = rect.width - margin.left - margin.right;
      const h = rect.height - margin.top - margin.bottom;

      // Scale
      const vMin = Math.min(...values.filter(v => v !== null && isFinite(v)));
      const vMax = Math.max(...values.filter(v => v !== null && isFinite(v)));
      const dMin = depth.length ? depth[0] : 0;
      const dMax = depth.length ? depth[depth.length - 1] : values.length;

      // Draw axes
      ctx.strokeStyle = '#e1dfdd';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(margin.left, margin.top);
      ctx.lineTo(margin.left, margin.top + h);
      ctx.lineTo(margin.left + w, margin.top + h);
      ctx.stroke();

      // Axis labels
      ctx.fillStyle = '#605e5c';
      ctx.font = '10px sans-serif';
      ctx.fillText(dMin.toFixed(1), 2, margin.top + 10);
      ctx.fillText(dMax.toFixed(1), 2, margin.top + h);
      ctx.fillText(vMin.toFixed(1), margin.left, margin.top + h + 14);
      ctx.fillText(vMax.toFixed(1), margin.left + w - 20, margin.top + h + 14);

      // Draw curve (depth on Y-axis, value on X-axis)
      ctx.strokeStyle = '#0078d4';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < values.length; i++) {
        if (values[i] === null || !isFinite(values[i])) continue;
        const x = margin.left + ((values[i] - vMin) / (vMax - vMin || 1)) * w;
        const y = margin.top + ((i) / (values.length - 1 || 1)) * h;
        if (!started) { ctx.moveTo(x, y); started = true; }
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    } catch(e) {
      ctx.fillStyle = '#605e5c';
      ctx.font = '13px sans-serif';
      ctx.fillText(`${well.name} — ${channel}`, 10, 20);
      ctx.fillText(`(preview not available: ${e.message})`, 10, 38);
    }
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
    const wellNamesList = selectedWells.size > 0 ? Array.from(selectedWells) : null;

    try {
      engineLog.textContent += `Options: ${JSON.stringify(options)}\nN-best: ${nBest}\n`;
      if (wellNamesList) engineLog.textContent += `Wells: ${wellNamesList.length} selected\n`;
      const data = await api('POST', '/run', { options, n_best: nBest, well_names: wellNamesList });
      correlationResult = data;
      if (data.wells_plot_data) wellDetails = data.wells_plot_data;
      engineLog.textContent += `\nCompleted: ${data.n_results} solutions in ${data.elapsed_ms} ms\n`;
      engineLog.textContent += `Mode: ${data.mode || 'in-process'}\n`;
      if (data.options_used) engineLog.textContent += `Options applied: ${JSON.stringify(data.options_used)}\n`;
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

    const options = gatherOptions();
    const nBest = parseInt($('#p-n-best').value) || 5;
    const wellNamesList = selectedWells.size > 0 ? Array.from(selectedWells) : null;

    try {
      // Use /run (with user options + well selection) since wells are pre-loaded
      engineLog.textContent += `Options: ${JSON.stringify(options)}\nN-best: ${nBest}\n`;
      if (wellNamesList) engineLog.textContent += `Wells: ${wellNamesList.length} selected\n`;
      const data = await api('POST', '/run', { options, n_best: nBest, well_names: wellNamesList });
      correlationResult = data;
      if (data.wells_plot_data) wellDetails = data.wells_plot_data;
      engineLog.textContent += `\nCompleted: ${data.n_results || '?'} solutions in ${data.elapsed_ms} ms\n`;
      engineLog.textContent += `Mode: ${data.mode || 'in-process'}\n`;
      engineLog.textContent += `Options: ${JSON.stringify(data.options_used || {})}\n`;

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

  // ── Import demo from RDDMS ─────────────────────────────────────────
  async function importDemoFromRddms(demoId) {
    importSpin.style.display = 'inline';
    setStatus(importStat, 'info', `Importing "${demoId}" from RDDMS...`);
    const ds = dsSel.value || 'maap/weco';
    try {
      const data = await api('POST', `/import/demo?demo_id=${encodeURIComponent(demoId)}&dataspace=${encodeURIComponent(ds)}`);
      importedWells = data;
      showWellsSummary(data);
      setStatus(importStat, 'ok', `Imported ${data.well_count} wells from RDDMS (demo: ${demoId})`);
      enableAfterImport();
    } catch(e) {
      setStatus(importStat, 'err', `RDDMS import failed: ${e.message}. Try running local demo instead.`);
    } finally {
      importSpin.style.display = 'none';
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
  const corrCanvas = $('#corr-canvas');
  const resultsPlot = $('#results-plot');
  const btnViewPlot = $('#btn-view-plot');
  const btnViewTable = $('#btn-view-table');

  btnViewPlot.addEventListener('click', () => {
    resultsPlot.style.display = 'block';
    resCards.style.display = 'none';
  });
  btnViewTable.addEventListener('click', () => {
    resultsPlot.style.display = 'none';
    resCards.style.display = 'block';
  });

  function showResults(data) {
    resEmpty.style.display = 'none';
    resSummary.style.display = 'block';
    resNWells.textContent = data.n_wells || '?';
    resNRes.textContent = data.n_results || 0;
    resElapsed.textContent = data.elapsed_ms || '-';
    resMode.textContent = data.mode || 'in-process';

    const results = data.results || [];
    resSelector.innerHTML = results.map((r, i) =>
      `<option value="${i}">#${i+1} (cost: ${r.cost != null ? r.cost.toFixed(4) : '-'})</option>`
    ).join('');

    // Build cost ranking display
    if (results.length > 1) {
      const maxCost = Math.max(...results.map(r => r.cost || 0));
      let rankHtml = '<strong>Cost Ranking (lowest = best):</strong><br>';
      results.forEach((r, i) => {
        const pct = maxCost > 0 ? ((r.cost || 0) / maxCost * 100) : 0;
        const sel = i === 0 ? ' style="background:#e3f2fd; font-weight:bold;"' : '';
        rankHtml += `<div class="rank-row" data-idx="${i}"${sel}>` +
          `#${i+1} cost=${(r.cost != null ? r.cost.toFixed(4) : '-')} ` +
          `<span style="display:inline-block;height:8px;width:${Math.max(pct, 2)}%;background:#1565c0;border-radius:2px;vertical-align:middle;"></span></div>`;
      });
      resRanking.innerHTML = rankHtml;
      resRanking.style.display = 'block';

      // Clickable ranking rows
      resRanking.querySelectorAll('.rank-row').forEach(row => {
        row.style.cursor = 'pointer';
        row.addEventListener('click', () => {
          const idx = parseInt(row.dataset.idx);
          resSelector.value = idx;
          resSelector.dispatchEvent(new Event('change'));
        });
      });
    } else {
      resRanking.style.display = 'none';
    }

    // Show first result
    updateResultView(results, 0, data);

    resSelector.onchange = () => {
      const idx = parseInt(resSelector.value);
      updateResultView(results, idx, data);
    };

    btnResPrev.onclick = () => {
      const idx = parseInt(resSelector.value) || 0;
      if (idx > 0) { resSelector.value = idx - 1; resSelector.dispatchEvent(new Event('change')); }
    };
    btnResNext.onclick = () => {
      const idx = parseInt(resSelector.value) || 0;
      if (idx < results.length - 1) { resSelector.value = idx + 1; resSelector.dispatchEvent(new Event('change')); }
    };
  }

  function updateResultView(results, idx, data) {
    renderResultCard(results, idx, data.well_names);
    // Ensure plot container is visible before measuring canvas
    resultsPlot.style.display = 'block';
    // Defer drawing until the browser has laid out the canvas
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        drawCorrelationPlot(data, idx);
      });
    });
    // Update cost label and highlight in ranking
    const r = results[idx];
    resCostLabel.textContent = r ? `Cost: ${r.cost != null ? r.cost.toFixed(4) : '-'} | ${(r.lines||[]).length} lines` : '';
    // Highlight active row in ranking
    resRanking.querySelectorAll('.rank-row').forEach((row, i) => {
      row.style.background = i === idx ? '#e3f2fd' : '';
      row.style.fontWeight = i === idx ? 'bold' : '';
    });
  }

  function renderResultCard(results, idx, wellNames) {
    if (!results[idx]) { resCards.innerHTML = ''; return; }
    const r = results[idx];
    // lines[] format: each line has markers[] array
    const lines = r.lines || [];
    const names = wellNames || [];

    let html = `<div class="result-card">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span class="result-rank">#${idx+1}</span>
        <span class="result-cost">Cost: ${r.cost != null ? r.cost.toFixed(4) : '-'} | ${lines.length} correlation lines</span>
      </div>`;

    if (lines.length && names.length) {
      html += '<table class="corr-table"><thead><tr><th>Line</th>';
      names.forEach(n => { html += `<th>${esc(n)}</th>`; });
      html += '</tr></thead><tbody>';
      lines.forEach((line, li) => {
        const markers = line.markers || line;
        html += `<tr><td style="font-weight:600;">${li+1}</td>`;
        if (Array.isArray(markers)) {
          markers.forEach(v => { html += `<td>${v != null ? v : '-'}</td>`; });
        }
        html += '</tr>';
      });
      html += '</tbody></table>';
    }
    html += '</div>';
    resCards.innerHTML = html;
  }

  // ── Correlation Plot (canvas-based) ───────────────────────────────
  async function drawCorrelationPlot(data, resultIdx) {
    const canvas = corrCanvas;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    // Fallback if canvas not yet laid out (tab just became visible)
    const cw = rect.width > 0 ? rect.width : canvas.parentElement.clientWidth || 800;
    const ch = rect.height > 0 ? rect.height : 420;
    canvas.width = cw * dpr;
    canvas.height = ch * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, cw, ch);

    const nWells = data.n_wells || 0;
    const wellNames = data.well_names || [];
    const results = data.results || [];
    const result = results[resultIdx];
    if (!result || !nWells) return;

    // Get well plot data (depths + logs + regions)
    let plotData = data.wells_plot_data;
    if (!plotData) {
      try {
        const pd = await api('GET', '/plot-data');
        plotData = pd.wells;
      } catch(e) {
        ctx.fillStyle = '#c62828';
        ctx.font = '13px sans-serif';
        ctx.fillText('Could not load plot data: ' + e.message, 10, 30);
        return;
      }
    }

    // Layout
    const margin = {top: 35, bottom: 25, left: 40, right: 15};
    const W = cw - margin.left - margin.right;
    const H = ch - margin.top - margin.bottom;
    const wellWidth = 70;
    const wellSpacing = Math.min((W - wellWidth) / Math.max(nWells - 1, 1), 200);
    const totalWidth = wellSpacing * (nWells - 1) + wellWidth;
    const offsetX = margin.left + (W - totalWidth) / 2;

    // Find global depth range
    let minDepth = Infinity, maxDepth = -Infinity;
    for (const wd of plotData) {
      if (wd.depth && wd.depth.length) {
        minDepth = Math.min(minDepth, wd.depth[0]);
        maxDepth = Math.max(maxDepth, wd.depth[wd.depth.length-1]);
      } else {
        minDepth = Math.min(minDepth, 0);
        maxDepth = Math.max(maxDepth, wd.size);
      }
    }
    if (!isFinite(minDepth)) { minDepth = 0; maxDepth = 100; }

    const depthToY = (d) => margin.top + ((d - minDepth) / (maxDepth - minDepth)) * H;
    const wellX = (i) => offsetX + i * wellSpacing + wellWidth / 2;

    // Zone color palette (Set3-like pastels)
    const zonePalette = [
      '#8dd3c7','#ffffb3','#bebada','#fb8072','#80b1d3',
      '#fdb462','#b3de69','#fccde5','#d9d9d9','#bc80bd','#ccebc5','#ffed6f'
    ];

    // Log trace colors
    const logColors = ['#1565c0', '#c62828', '#2e7d32', '#6a1b9a', '#e65100'];

    // ── Draw each well column ───────────────────────────────────────
    for (let i = 0; i < nWells; i++) {
      const wd = plotData[i];
      const cx = wellX(i);
      const halfW = wellWidth / 2;

      // Well name header
      ctx.fillStyle = '#333';
      ctx.font = 'bold 11px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(wd.name, cx, margin.top - 10);

      // Draw well column border
      const y0 = depthToY(wd.depth ? wd.depth[0] : 0);
      const y1 = depthToY(wd.depth ? wd.depth[wd.depth.length-1] : wd.size);
      ctx.strokeStyle = '#ccc';
      ctx.lineWidth = 1;
      ctx.strokeRect(cx - halfW, y0, wellWidth, y1 - y0);

      // ── Zone/region background bands ─────────────────────────────
      const regions = wd.regions || {};
      const regionNames = wd.region_names || Object.keys(regions);
      if (regionNames.length > 0) {
        const rname = regionNames[0];  // primary region for bands
        const rvals = regions[rname];
        if (rvals && rvals.length) {
          // Build unique zone list for color mapping
          const uniqueZones = [...new Set(rvals.filter(v => v != null && v !== ''))];
          const zoneColorMap = {};
          uniqueZones.forEach((z, zi) => { zoneColorMap[z] = zonePalette[zi % zonePalette.length]; });

          // Draw contiguous zone spans
          let prevVal = rvals[0], startIdx = 0;
          for (let s = 1; s <= rvals.length; s++) {
            if (s === rvals.length || rvals[s] !== prevVal) {
              if (prevVal && zoneColorMap[prevVal]) {
                const yt = depthToY(wd.depth ? wd.depth[startIdx] : startIdx);
                const yb = depthToY(wd.depth ? (wd.depth[Math.min(s-1, wd.depth.length-1)]) : s-1);
                ctx.fillStyle = zoneColorMap[prevVal];
                ctx.globalAlpha = 0.3;
                ctx.fillRect(cx - halfW, yt, wellWidth, yb - yt);
                ctx.globalAlpha = 1.0;

                // Zone label
                const ymid = (yt + yb) / 2;
                if (yb - yt > 12) {
                  ctx.fillStyle = '#444';
                  ctx.font = '8px sans-serif';
                  ctx.textAlign = 'left';
                  ctx.fillText(String(prevVal).slice(0, 10), cx - halfW + 2, ymid + 3);
                }
              }
              if (s < rvals.length) { prevVal = rvals[s]; startIdx = s; }
            }
          }
        }
      }

      // ── Multi-log traces ─────────────────────────────────────────
      const logs = wd.logs || {};
      const logNames = wd.log_names || Object.keys(logs);
      const maxLogs = Math.min(logNames.length, 3);  // show up to 3 logs

      for (let li = 0; li < maxLogs; li++) {
        const lname = logNames[li];
        const logVals = logs[lname] || (li === 0 ? wd.log_values : null);
        if (!logVals || logVals.length < 2) continue;

        let lMin = Infinity, lMax = -Infinity;
        for (const v of logVals) { if (v != null) { lMin = Math.min(lMin, v); lMax = Math.max(lMax, v); } }
        if (lMax === lMin) lMax = lMin + 1;

        ctx.beginPath();
        ctx.strokeStyle = logColors[li % logColors.length];
        ctx.lineWidth = li === 0 ? 1.4 : 0.9;
        ctx.globalAlpha = li === 0 ? 1.0 : 0.6;
        let started = false;
        for (let s = 0; s < wd.size && s < logVals.length; s++) {
          if (logVals[s] == null) continue;
          const y = depthToY(wd.depth ? wd.depth[s] : s);
          const x = cx - halfW + ((logVals[s] - lMin) / (lMax - lMin)) * wellWidth;
          if (!started) { ctx.moveTo(x, y); started = true; }
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
        ctx.globalAlpha = 1.0;
      }

      // Log legend below well name
      if (maxLogs > 0) {
        ctx.font = '8px sans-serif';
        ctx.textAlign = 'center';
        const legendY = margin.top - 2;
        let legendText = logNames.slice(0, maxLogs).map((n, li) => n).join(' / ');
        ctx.fillStyle = '#666';
        ctx.fillText(legendText.slice(0, 20), cx, legendY);
      }
    }

    // ── Draw correlation lines (typed: boundary/gap/framework) ────────
    const lines = result.lines || [];
    const lineStyles = {
      boundary: { color: '#D32F2F', width: 1.8, alpha: 0.85, dash: [] },
      gap:      { color: '#1565C0', width: 1.2, alpha: 0.6, dash: [4, 3] },
      framework:{ color: '#999999', width: 0.6, alpha: 0.3, dash: [] },
    };

    for (let li = 0; li < lines.length; li++) {
      const line = lines[li];
      const markers = line.markers || line;
      if (!Array.isArray(markers)) continue;
      const lt = line.line_type || 'framework';
      const style = lineStyles[lt] || lineStyles.framework;

      ctx.strokeStyle = style.color;
      ctx.lineWidth = style.width;
      ctx.globalAlpha = style.alpha;
      ctx.setLineDash(style.dash);

      ctx.beginPath();
      let first = true;
      for (let w = 0; w < nWells && w < markers.length; w++) {
        const markerIdx = markers[w];
        if (markerIdx == null || markerIdx < 0) continue;
        const wd = plotData[w];
        const depth = wd.depth ? (wd.depth[markerIdx] || markerIdx) : markerIdx;
        const y = depthToY(depth);
        const x = wellX(w);
        if (first) { ctx.moveTo(x, y); first = false; }
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Marker dots only for boundary lines
      if (lt === 'boundary') {
        ctx.globalAlpha = 1.0;
        ctx.setLineDash([]);
        for (let w = 0; w < nWells && w < markers.length; w++) {
          const markerIdx = markers[w];
          if (markerIdx == null || markerIdx < 0) continue;
          const wd = plotData[w];
          const depth = wd.depth ? (wd.depth[markerIdx] || markerIdx) : markerIdx;
          const y = depthToY(depth);
          const x = wellX(w);
          ctx.beginPath();
          ctx.arc(x, y, 2.5, 0, 2 * Math.PI);
          ctx.fillStyle = style.color;
          ctx.fill();
        }
      }
    }

    ctx.globalAlpha = 1.0;
    ctx.setLineDash([]);

    // ── Depth axis labels ───────────────────────────────────────────
    ctx.fillStyle = '#605e5c';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    const nTicks = 6;
    for (let t = 0; t <= nTicks; t++) {
      const d = minDepth + (maxDepth - minDepth) * t / nTicks;
      const y = depthToY(d);
      ctx.fillText(d.toFixed(1), margin.left - 4, y + 3);
      ctx.strokeStyle = '#f3f2f1';
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(margin.left, y);
      ctx.lineTo(cw - margin.right, y);
      ctx.stroke();
    }

    // ── Region legend (bottom) ──────────────────────────────────────
    if (plotData[0] && plotData[0].region_names && plotData[0].region_names.length) {
      ctx.font = '9px sans-serif';
      ctx.textAlign = 'left';
      ctx.fillStyle = '#555';
      ctx.fillText('Zones: ' + plotData[0].region_names.join(', '), margin.left, ch - 6);
    }

    // ── Correlation line legend ─────────────────────────────────────
    const legendY = ch - 6;
    const legendX = cw / 2;
    ctx.font = '9px sans-serif';
    ctx.textAlign = 'left';
    // Boundary
    ctx.strokeStyle = '#D32F2F'; ctx.lineWidth = 2; ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(legendX, legendY - 3); ctx.lineTo(legendX + 20, legendY - 3); ctx.stroke();
    ctx.fillStyle = '#D32F2F'; ctx.fillText('Boundary', legendX + 23, legendY);
    // Gap
    ctx.strokeStyle = '#1565C0'; ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(legendX + 85, legendY - 3); ctx.lineTo(legendX + 105, legendY - 3); ctx.stroke();
    ctx.fillStyle = '#1565C0'; ctx.fillText('Gap/hiatus', legendX + 108, legendY);
    // Framework
    ctx.strokeStyle = '#999'; ctx.lineWidth = 0.8; ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(legendX + 180, legendY - 3); ctx.lineTo(legendX + 200, legendY - 3); ctx.stroke();
    ctx.fillStyle = '#999'; ctx.fillText('Framework', legendX + 203, legendY);
    ctx.setLineDash([]);
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

  // ── Workflow save/load ────────────────────────────────────────────────
  btnSaveWorkflow.addEventListener('click', async () => {
    const name = (workflowName.value || '').trim();
    if (!name) { setStatus(workflowStatus, 'err', 'Enter a workflow name'); return; }
    const body = {
      name,
      demo_id: currentDemoId || '',
      dataspace: dsSel.value || '',
      options: gatherOptions(),
      n_best: parseInt($('#p-n-best')?.value || '5', 10),
      well_ids: [],
      notes: '',
    };
    try {
      const res = await api('POST', '/workflows', body);
      setStatus(workflowStatus, 'ok', `Saved "${res.name}" (id=${res.id})`);
      loadWorkflowList();
    } catch(e) {
      setStatus(workflowStatus, 'err', 'Save failed: ' + e.message);
    }
  });

  btnLoadWorkflows.addEventListener('click', () => loadWorkflowList());

  async function loadWorkflowList() {
    try {
      const list = await api('GET', '/workflows');
      if (!list.length) {
        workflowList.innerHTML = '<span class="muted">No saved workflows</span>';
        return;
      }
      workflowList.innerHTML = list.map(wf => {
        const d = new Date(wf.updated_at * 1000).toLocaleDateString();
        return `<div style="display:flex; justify-content:space-between; align-items:center; padding:2px 0; border-bottom:1px solid #f3f2f1;">
          <span><a href="#" class="wf-load" data-id="${wf.id}" style="font-weight:500;">${esc(wf.name)}</a>
            <span class="muted" style="font-size:11px;"> ${wf.demo_id ? '(' + wf.demo_id + ')' : ''} ${d}</span></span>
          <a href="#" class="wf-delete" data-id="${wf.id}" style="color:#a4262c; font-size:11px;">del</a>
        </div>`;
      }).join('');
      // Bind load links
      workflowList.querySelectorAll('.wf-load').forEach(a => {
        a.addEventListener('click', async (e) => {
          e.preventDefault();
          await loadWorkflow(parseInt(a.dataset.id, 10));
        });
      });
      // Bind delete links
      workflowList.querySelectorAll('.wf-delete').forEach(a => {
        a.addEventListener('click', async (e) => {
          e.preventDefault();
          await deleteWorkflow(parseInt(a.dataset.id, 10));
        });
      });
    } catch(e) {
      workflowList.innerHTML = '<span class="muted">Failed to load</span>';
    }
  }

  async function loadWorkflow(id) {
    try {
      const wf = await api('GET', '/workflows/' + id);
      workflowName.value = wf.name;
      if (wf.options && typeof wf.options === 'object') {
        applyOptions(wf.options);
      }
      if (wf.n_best && $('#p-n-best')) $('#p-n-best').value = wf.n_best;
      if (wf.demo_id) currentDemoId = wf.demo_id;
      setStatus(workflowStatus, 'ok', `Loaded "${wf.name}"`);
    } catch(e) {
      setStatus(workflowStatus, 'err', 'Load failed: ' + e.message);
    }
  }

  async function deleteWorkflow(id) {
    try {
      await api('DELETE', '/workflows/' + id);
      setStatus(workflowStatus, 'ok', 'Deleted');
      loadWorkflowList();
    } catch(e) {
      setStatus(workflowStatus, 'err', 'Delete failed: ' + e.message);
    }
  }

  // ── RESQML Object Browser ──────────────────────────────────────────
  const objBrowser = $('#obj-browser');
  const objBrowserHint = $('#obj-browser-hint');
  const objTypeSelect = $('#obj-type-select');
  const objTypeChips = $('#obj-type-chips');
  const objFilter = $('#obj-filter');
  const objList = $('#obj-list');
  const objCount = $('#obj-count');
  const objSelectedCount = $('#obj-selected-count');
  const btnObjLoad = $('#btn-obj-load');
  const btnObjSelectAll = $('#btn-obj-select-all');
  const btnObjSelectNone = $('#btn-obj-select-none');

  let objTypes = [];
  let objCache = {}; // type -> [{uuid, name, lastChanged, storeCreated}]
  let objSelected = new Set(); // "type::uuid" keys

  async function loadObjectTypes() {
    try {
      const resp = await api('GET', '/objects/types');
      objTypes = resp.types || [];
      objTypeSelect.innerHTML = '<option value="">-- Select type --</option>' +
        objTypes.map(t => `<option value="${esc(t.type)}">${esc(t.label)} (${esc(t.group)})</option>`).join('');
    } catch(e) { /* silent */ }
  }
  loadObjectTypes();

  // Show browser when a dataspace is selected
  dsSel.addEventListener('change', () => {
    if (dsSel.value) {
      objBrowser.style.display = 'block';
      objBrowserHint.style.display = 'none';
      objCache = {};
      objTypeChips.innerHTML = '';
      objList.innerHTML = '';
      objCount.textContent = '';
    }
  });

  btnObjLoad.addEventListener('click', async () => {
    const ds = dsSel.value;
    const typ = objTypeSelect.value;
    if (!ds || !typ) return;
    objCount.textContent = 'Loading...';
    try {
      const resp = await api('GET', `/objects?dataspace=${encodeURIComponent(ds)}&type=${encodeURIComponent(typ)}`);
      objCache[typ] = resp.objects || [];
      renderObjTypeChips();
      renderObjList(typ);
    } catch(e) {
      objCount.textContent = 'Error: ' + e.message;
    }
  });

  function renderObjTypeChips() {
    objTypeChips.innerHTML = Object.keys(objCache).map(typ => {
      const info = objTypes.find(t => t.type === typ);
      const label = info ? info.label : typ.split('.').pop();
      const count = objCache[typ].length;
      return `<span class="obj-type-chip active" data-type="${esc(typ)}">${esc(label)}<span class="type-count">(${count})</span></span>`;
    }).join('');
    objTypeChips.querySelectorAll('.obj-type-chip').forEach(chip => {
      chip.addEventListener('click', () => renderObjList(chip.dataset.type));
    });
  }

  function renderObjList(typ) {
    const objects = objCache[typ] || [];
    const filter = (objFilter.value || '').toLowerCase();
    const filtered = objects.filter(o =>
      !filter || o.name.toLowerCase().includes(filter) || o.uuid.toLowerCase().includes(filter)
    );
    objCount.textContent = `${filtered.length}/${objects.length} objects`;
    objList.innerHTML = filtered.map(o => {
      const key = `${typ}::${o.uuid}`;
      const checked = objSelected.has(key) ? 'checked' : '';
      const date = o.lastChanged ? new Date(o.lastChanged).toLocaleDateString() : '';
      return `<div class="obj-row ${checked ? 'selected' : ''}" data-key="${esc(key)}">
        <input type="checkbox" ${checked}>
        <span class="obj-name" title="${esc(o.name)}">${esc(o.name)}</span>
        <span class="obj-uuid">${esc(o.uuid.slice(0,8))}…</span>
        <span class="obj-date">${esc(date)}</span>
      </div>`;
    }).join('');
    // Click to toggle
    objList.querySelectorAll('.obj-row').forEach(row => {
      row.addEventListener('click', (e) => {
        if (e.target.tagName === 'INPUT') return; // handled by checkbox
        const key = row.dataset.key;
        const cb = row.querySelector('input[type="checkbox"]');
        if (objSelected.has(key)) {
          objSelected.delete(key);
          cb.checked = false;
          row.classList.remove('selected');
        } else {
          objSelected.add(key);
          cb.checked = true;
          row.classList.add('selected');
        }
        updateObjSelectedCount();
      });
      const cb = row.querySelector('input[type="checkbox"]');
      cb.addEventListener('change', () => {
        const key = row.dataset.key;
        if (cb.checked) { objSelected.add(key); row.classList.add('selected'); }
        else { objSelected.delete(key); row.classList.remove('selected'); }
        updateObjSelectedCount();
      });
    });
    updateObjSelectedCount();
  }

  function updateObjSelectedCount() {
    objSelectedCount.textContent = objSelected.size ? `${objSelected.size} selected` : '';
  }

  if (objFilter) objFilter.addEventListener('input', () => {
    const typ = objTypeSelect.value;
    if (typ && objCache[typ]) renderObjList(typ);
  });

  btnObjSelectAll.addEventListener('click', () => {
    objList.querySelectorAll('.obj-row').forEach(row => {
      const key = row.dataset.key;
      objSelected.add(key);
      row.classList.add('selected');
      row.querySelector('input[type="checkbox"]').checked = true;
    });
    updateObjSelectedCount();
  });

  btnObjSelectNone.addEventListener('click', () => {
    objList.querySelectorAll('.obj-row').forEach(row => {
      const key = row.dataset.key;
      objSelected.delete(key);
      row.classList.remove('selected');
      row.querySelector('input[type="checkbox"]').checked = false;
    });
    updateObjSelectedCount();
  });

})();
