(function(){
  'use strict';

  const $ = (sel, root=document) => root.querySelector(sel);
  const $$ = (sel, root=document) => [...root.querySelectorAll(sel)];

  // ── State ─────────────────────────────────────────────────────────
  let importedWells = null;   // last import response
  let correlationResult = null;  // last run response

  // ── Elements ──────────────────────────────────────────────────────
  const tabs      = $$('.wc-tab');
  const bodies    = $$('.wc-body');
  const healthDot = $('#health-dot');
  const healthTxt = $('#health-text');

  // Wells tab
  const dsInput    = $('#wc-dataspace');
  const btnImport  = $('#btn-import');
  const btnDemo    = $('#btn-demo');
  const importSpin = $('#import-spinner');
  const importStat = $('#import-status');
  const wellsSumm  = $('#wells-summary');
  const wellCount  = $('#well-count');
  const wellChips  = $('#well-chips');
  const dataNames  = $('#data-names');
  const regionNames= $('#region-names');
  const btnNext    = $('#btn-next-params');

  // Params tab
  const showAdv    = $('#show-advanced');
  const btnSuggest = $('#btn-suggest');
  const suggestSt  = $('#suggest-status');
  const btnRun     = $('#btn-run');
  const runSpin    = $('#run-spinner');
  const runStatus  = $('#run-status');
  const runError   = $('#run-error');

  // Results tab
  const resEmpty   = $('#results-empty');
  const resSummary = $('#results-summary');
  const resNWells  = $('#res-n-wells');
  const resNRes    = $('#res-n-results');
  const resElapsed = $('#res-elapsed');
  const resCards   = $('#results-cards');
  const btnExport  = $('#btn-export');
  const exportSt   = $('#export-status');

  // ── Tab switching ─────────────────────────────────────────────────
  function switchTab(name) {
    tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === name));
    bodies.forEach(b => b.classList.toggle('active', b.id === 'tab-' + name));
  }
  tabs.forEach(t => t.addEventListener('click', () => switchTab(t.dataset.tab)));

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
      setStatus(importStat, 'ok', `Imported ${data.well_count} wells`);
      btnRun.disabled = false;
    } catch(e) {
      setStatus(importStat, 'err', 'Import failed: ' + e.message);
    } finally {
      importSpin.style.display = 'none';
    }
  });

  // ── Demo run ──────────────────────────────────────────────────────
  btnDemo.addEventListener('click', async () => {
    importSpin.style.display = 'inline';
    setStatus(importStat, '', '');
    try {
      const data = await api('POST', '/run/demo?demo_id=ds1.1&n_best=5');
      correlationResult = data;
      // Demo returns results directly
      setStatus(importStat, 'ok', 'Demo completed');
      showResults(data);
      switchTab('results');
    } catch(e) {
      setStatus(importStat, 'err', 'Demo failed: ' + e.message);
    } finally {
      importSpin.style.display = 'none';
    }
  });

  // ── Show wells summary ────────────────────────────────────────────
  function showWellsSummary(data) {
    wellsSumm.style.display = 'block';
    wellCount.textContent = data.well_count;
    wellChips.innerHTML = (data.well_names || [])
      .map(n => `<span class="well-chip">${esc(n)}</span>`).join('');
    dataNames.textContent = (data.data_names || []).join(', ') || '(none)';
    regionNames.textContent = (data.region_names || []).join(', ') || '(none)';

    // Populate param dropdowns
    populateDropdowns(data.data_names || [], data.region_names || []);
  }

  function populateDropdowns(dataLogs, regions) {
    const dataSelects = ['#p-var-data', '#p-var-data2'];
    const regionSelects = ['#p-no-crossing', '#p-same-region', '#p-polarity-region',
                           '#p-dist-distal', '#p-dist-facies'];

    dataSelects.forEach(sel => {
      const el = $(sel);
      if (!el) return;
      el.innerHTML = '<option value="">-- select --</option>';
      dataLogs.forEach(n => {
        el.innerHTML += `<option value="${esc(n)}">${esc(n)}</option>`;
      });
    });
    regionSelects.forEach(sel => {
      const el = $(sel);
      if (!el) return;
      el.innerHTML = '<option value="">-- none --</option>';
      regions.forEach(n => {
        el.innerHTML += `<option value="${esc(n)}">${esc(n)}</option>`;
      });
    });
  }

  // ── Next → params ─────────────────────────────────────────────────
  btnNext.addEventListener('click', () => {
    switchTab('params');
    // Auto-suggest
    suggestDefaults();
  });

  // ── Advanced toggle ───────────────────────────────────────────────
  showAdv.addEventListener('change', () => {
    const show = showAdv.checked;
    $$('.advanced-param').forEach(el => {
      el.style.display = show ? '' : 'none';
    });
  });

  // ── Suggest defaults ──────────────────────────────────────────────
  btnSuggest.addEventListener('click', suggestDefaults);

  async function suggestDefaults() {
    suggestSt.textContent = 'Analyzing...';
    try {
      const data = await api('POST', '/suggest-defaults');
      if (data.options) {
        applyOptions(data.options);
        suggestSt.textContent = '✓ Applied';
      } else {
        suggestSt.textContent = 'No suggestions';
      }
    } catch(e) {
      suggestSt.textContent = 'Failed';
    }
  }

  function applyOptions(opts) {
    const map = {
      'var-data': '#p-var-data', 'var-weight': '#p-var-weight',
      'var-data2': '#p-var-data2', 'var-weight2': '#p-var-weight2',
      'no-crossing': '#p-no-crossing', 'same-region': '#p-same-region',
      'polarity-region': '#p-polarity-region',
      'const-gap-cost': '#p-gap-cost',
      'dist-distal': '#p-dist-distal', 'dist-facies': '#p-dist-facies',
    };
    for (const [key, sel] of Object.entries(map)) {
      if (opts[key] !== undefined) {
        const el = $(sel);
        if (el) el.value = opts[key];
      }
    }
  }

  // ── Run correlation ───────────────────────────────────────────────
  btnRun.addEventListener('click', async () => {
    runSpin.style.display = 'inline';
    runStatus.textContent = '';
    setStatus(runError, '', '');
    btnRun.disabled = true;

    const options = gatherOptions();
    const nBest = parseInt($('#p-n-best').value) || 5;

    try {
      const data = await api('POST', '/run', { options, n_best: nBest });
      correlationResult = data;
      runStatus.textContent = `✓ ${data.n_results} solutions (${data.elapsed_ms} ms)`;
      showResults(data);
      switchTab('results');
    } catch(e) {
      setStatus(runError, 'err', 'Correlation failed: ' + e.message);
    } finally {
      runSpin.style.display = 'none';
      btnRun.disabled = false;
    }
  });

  function gatherOptions() {
    const opts = {};
    const val = (sel) => { const el = $(sel); return el ? el.value : ''; };

    if (val('#p-var-data'))  opts['var-data'] = val('#p-var-data');
    if (val('#p-var-weight') !== '1') opts['var-weight'] = parseFloat(val('#p-var-weight')) || 1.0;
    if (val('#p-no-crossing'))  opts['no-crossing'] = val('#p-no-crossing');
    if (val('#p-same-region'))  opts['same-region'] = val('#p-same-region');
    if (val('#p-var-data2'))  opts['var-data2'] = val('#p-var-data2');
    if (val('#p-var-weight2') && val('#p-var-weight2') !== '1') opts['var-weight2'] = parseFloat(val('#p-var-weight2'));
    if (val('#p-gap-cost') && val('#p-gap-cost') !== '0') opts['const-gap-cost'] = parseFloat(val('#p-gap-cost'));
    if (val('#p-polarity-region'))  opts['polarity-region'] = val('#p-polarity-region');
    if (val('#p-dist-distal'))  opts['dist-distal'] = val('#p-dist-distal');
    if (val('#p-dist-facies'))  opts['dist-facies'] = val('#p-dist-facies');

    return opts;
  }

  // ── Show results ──────────────────────────────────────────────────
  function showResults(data) {
    resEmpty.style.display = 'none';
    resSummary.style.display = 'block';
    resNWells.textContent = data.n_wells || '?';
    resNRes.textContent = data.n_results || 0;
    resElapsed.textContent = data.elapsed_ms || '-';

    const results = data.results || [];
    resCards.innerHTML = '';
    results.forEach((r, i) => {
      const card = document.createElement('div');
      card.className = 'result-card';
      card.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span class="result-rank">#${i+1}</span>
          <span class="result-cost">Cost: ${r.cost != null ? r.cost.toFixed(4) : '-'}</span>
        </div>
        ${renderCorrelationTable(r, data.well_names)}
      `;
      resCards.appendChild(card);
    });
  }

  function renderCorrelationTable(result, wellNames) {
    if (!result.markers || !wellNames) return '';
    const names = wellNames || [];
    let html = '<table class="corr-table"><thead><tr>';
    html += '<th>Marker</th>';
    names.forEach(n => { html += `<th>${esc(n)}</th>`; });
    html += '</tr></thead><tbody>';

    // markers is an array of arrays (marker_index per well)
    // or could be a correlation matrix — adapt to actual format
    if (Array.isArray(result.markers)) {
      result.markers.forEach((row, mi) => {
        html += '<tr>';
        html += `<td style="font-weight:600;">${mi + 1}</td>`;
        if (Array.isArray(row)) {
          row.forEach(v => { html += `<td>${v != null ? v : '-'}</td>`; });
        } else {
          html += `<td colspan="${names.length}">${row}</td>`;
        }
        html += '</tr>';
      });
    }
    html += '</tbody></table>';
    return html;
  }

  // ── Export ────────────────────────────────────────────────────────
  btnExport.addEventListener('click', async () => {
    exportSt.textContent = 'Exporting...';
    try {
      const data = await api('POST', '/export');
      exportSt.textContent = '✓ Exported to RDDMS';
    } catch(e) {
      exportSt.textContent = '✗ ' + e.message;
    }
  });

  // ── Utils ─────────────────────────────────────────────────────────
  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

})();
