
/* app/static/app.js - nav + robust manifest UI with type and name filters */
(function () {
  // ---------- helpers ----------
  const $ = (sel) => document.querySelector(sel);
  const dsSel = $('#ds-select');
  const typeSel = $('#type-select');
  const nameFilter = $('#name-filter');
  const objSel = $('#obj-select');
  const dsErr = $('#ds-error');
  const objErr = $('#obj-error');
  const refsSummary = $('#refs-summary');
  const refsList = $('#refs-list'); // optional detailed list
  const buildSummary = $('#build-summary');
  const includeRefs = $('#include-refs');
  const btnLoadRefs = $('#btn-load-refs');
  const btnBuild = $('#btn-build');
  const btnIngest = $('#btn-ingest');
  const manifestBox = $('#manifest-json');

  function setText(node, msg) { if (node) node.textContent = msg || ''; }
  async function fetchJSON(url) {
    const r = await fetch(url, { headers: { 'Cache-Control': 'no-store' } });
    if (!r.ok) {
      let detail = '';
      try {
        const errBody = await r.json();
        const d = errBody.detail || errBody.reason || '';
        detail = typeof d === 'string' ? d : JSON.stringify(d);
      } catch { try { detail = (await r.text()).substring(0, 300); } catch {} }
      throw new Error(`${r.status} ${r.statusText}` + (detail ? ': ' + detail : ''));
    }
    return r.json();
  }
  async function postForm(url, data) {
    const body = new URLSearchParams(data);
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body
    });
    if (!r.ok) {
      let detail = '';
      try {
        const errBody = await r.json();
        const d = errBody.detail || errBody.reason || '';
        detail = typeof d === 'string' ? d : JSON.stringify(d);
      } catch { try { detail = (await r.text()).substring(0, 300); } catch {} }
      throw new Error(`${r.status} ${r.statusText}` + (detail ? ': ' + detail : ''));
    }
    return r.json();
  }

  // ---------- top nav (built by inline <script> in base.html) ----------
  // el() and linkSpan() kept for use by other UI code below.
  function el(tag, attrs, text) {
    const e = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') e.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
      else e.setAttribute(k, v);
    }
    if (text) e.textContent = text;
    return e;
  }
  function linkSpan(href, text, cls = 'navlink') {
    const s = el('span', { 'data-href': href, 'class': cls }, text);
    s.addEventListener('click', () => { window.location.assign(href); });
    return s;
  }
  document.addEventListener('click', function (e) {
    const el = e.target.closest('[data-href]');
    if (!el) return;
    const url = el.getAttribute('data-href');
    if (url) window.location.assign(url);
  });

  // ---------- manifest UI ----------
  async function loadDataspaces() {
    if (!dsSel) return;
    setText(dsErr, '');

    // If server has already prefilled options, use them and skip remote fetch.
    const alreadyPrefilled = dsSel.options && dsSel.options.length > 0;
    if (alreadyPrefilled) {
      // ensure a selection exists
      if (dsSel.selectedIndex < 0 && dsSel.options.length > 0) dsSel.selectedIndex = 0;
      return;
    }

    // Fallback: fetch from Keys JSON endpoint (same as /keys page)
    try {
      const res = await fetchJSON('/keys/dataspaces.json');
      const items = res.items || [];
      dsSel.innerHTML = '';
      if (!items.length) {
        setText(dsErr, 'No dataspaces found (check auth, base URL, partition).');
        return;
      }
      for (const x of items) {
        const path = x.path || '';
        const uri = x.uri || `eml:///dataspace('${path}')`;
        const opt = document.createElement('option');
        opt.value = path;           // value must be PATH (not EML)
        opt.textContent = uri;      // label shows canonical EML URI
        dsSel.appendChild(opt);
      }
      dsSel.selectedIndex = 0;
    } catch (e) {
      console.warn('Failed to load dataspaces:', e);
      setText(dsErr, `Failed to load dataspaces: ${e.message}`);
    }
  }

  async function loadTypes() {
    if (!dsSel || !typeSel) return;
    typeSel.innerHTML = '<option value="" selected>(All types)</option>';
    try {
      const ds = dsSel.value;
      if (!ds) return;
      const res = await fetchJSON(`/keys/types.json?ds=${encodeURIComponent(ds)}&source=live`);
      const items = res.items || [];
      for (const t of items) {
        const opt = document.createElement('option');
        opt.value = t.name || ''; // canonical type name
        const lbl = t.count != null ? `${t.name} (${t.count})` : t.name;
        opt.textContent = lbl;
        typeSel.appendChild(opt);
      }
      // Pre-select "(All types)"
      typeSel.options[0].selected = true;
    } catch (e) {
      console.warn('Failed to load types:', e);
      // leave "(All types)"
    }
  }

  function _getSelectedTypes() {
    // Collect all selected type values from the multi-select; empty string = all types
    if (!typeSel) return [];
    const vals = [];
    for (const opt of typeSel.selectedOptions) {
      if (opt.value) vals.push(opt.value);
    }
    return vals; // empty array means "all types"
  }

  async function loadObjects() {
    if (!dsSel || !objSel) return;
    setText(objErr, '');
    const ds = dsSel.value;
    const selectedTypes = _getSelectedTypes();
    if (!ds) {
      objSel.innerHTML = '<option value="">- select dataspace/type -</option>';
      return;
    }
    const qRaw = (nameFilter && nameFilter.value || '').trim();
    const q = (qRaw === '*' ? '' : qRaw);

    objSel.disabled = true;
    objSel.innerHTML = '<option value="">Loading…</option>';
    try {
      // Fetch objects: if specific types selected, request each and merge; otherwise fetch all
      let allItems = [];
      if (selectedTypes.length === 0) {
        const url = `/keys/objects.json?ds=${encodeURIComponent(ds)}&q=${encodeURIComponent(q)}`;
        const res = await fetchJSON(url);
        allItems = res.items || [];
      } else if (selectedTypes.length === 1) {
        const url = `/keys/objects.json?ds=${encodeURIComponent(ds)}&typ=${encodeURIComponent(selectedTypes[0])}&q=${encodeURIComponent(q)}`;
        const res = await fetchJSON(url);
        allItems = res.items || [];
      } else {
        // Multiple types selected: fetch in parallel and merge
        const fetches = selectedTypes.map(t =>
          fetchJSON(`/keys/objects.json?ds=${encodeURIComponent(ds)}&typ=${encodeURIComponent(t)}&q=${encodeURIComponent(q)}`)
            .then(r => r.items || [])
            .catch(() => [])
        );
        const results = await Promise.all(fetches);
        for (const items of results) allItems.push(...items);
      }
      const items = allItems.map(x => ({ ...x, typePath: x.typePath || x.type || '' }));
      objSel.innerHTML = '';
      if (!items.length) {
        objSel.innerHTML = '<option value="">No objects match</option>';
        setText(objErr, 'No objects returned. Try adjusting filters.');
        objSel.disabled = false;
        return;
      }
      for (const x of items) {
        const opt = document.createElement('option');
        // Use item's own typePath, fall back to the first selected type
        const typ2 = x.typePath || x.type || (selectedTypes[0] || '');
        const uuid = x.uuid || '';
        opt.value = JSON.stringify({ ds, typ: typ2, uuid });
        // Short type label: strip resqml20.obj_ prefix and any (uuid) suffix
        let labelType = (typ2.split('obj_').pop() || typ2).split('(')[0];
        const shortUuid = uuid.length > 13 ? uuid.slice(0, 8) + '…' : uuid;
        opt.textContent = `[${labelType}] ${(x.title || uuid || x.uri)}  (${shortUuid})`;
        opt.title = `${typ2}  uuid=${uuid}`;  // full info on hover
        objSel.appendChild(opt);
      }
      objSel.disabled = false;
      objSel.selectedIndex = 0;
    } catch (e) {
      console.warn('Failed to load objects:', e);
      setText(objErr, `Failed to load objects: ${e.message}`);
      objSel.disabled = false;
    }
  }

  // --- Refs preview using /keys/object/graph.json ---
  function renderRefsList(data) {
    if (!refsList) return;
    const { refs = [], primary = {}, summary = {} } = data || {};
    refsList.innerHTML = '';
    const hdr = el('div', { class: 'muted' },
      `Primary: ${primary.title || primary.uuid || ''} · URIs=${summary.total || 0}`);
    refsList.appendChild(hdr);
    const ul = el('ul', { class: 'refs-ul' });
    for (const r of refs) {
      const li = el('li', null,
        `[${r.role}] ${(r.typePath || '').split('obj_').pop() || r.typePath || ''} · ${r.title || r.uuid} · ${r.uuid}`);
      ul.appendChild(li);
    }
    if (!refs.length) ul.appendChild(el('li', { class: 'muted' }, 'No references found.'));
    refsList.appendChild(ul);
  }

  async function loadRefs() {
    setText(refsSummary, 'Loading…');
    if (refsList) refsList.innerHTML = '';
    const items = getSelectedItems();
    if (!items.length) { setText(refsSummary, 'Select an object first.'); return; }
    // Use first selected item for refs preview
    const { ds, typ, uuid } = items[0];
    if (!typ) { setText(refsSummary, 'Cannot load refs: object type unknown. Select a specific type first.'); return; }
    const include = includeRefs && includeRefs.checked ? 'true' : 'false';
    try {
      const url = `/keys/object/graph.json?ds=${encodeURIComponent(ds)}&typ=${encodeURIComponent(typ)}&uuid=${encodeURIComponent(uuid)}&include_refs=${include}`;
      const data = await fetchJSON(url);
      const { primary = {}, summary = {} } = data || {};
      setText(
        refsSummary,
        `URI=${primary.uri || ''} · refs=${summary.total || 0} (sources ${summary.sources || 0}, targets ${summary.targets || 0}, CRS ${summary.crs || 0})`
      );
      renderRefsList(data);
    } catch (e) {
      console.warn('refs error:', e);
      setText(refsSummary, `Failed to load refs: ${e.message}`);
    }
  }

  

function getSelectedItems() {
  // Collect all selected objects as { ds, typ, uuid }
  const items = [];
  if (!objSel || !objSel.selectedOptions) return items;
  for (const opt of objSel.selectedOptions) {
    if (!opt.value) continue;
    try { items.push(JSON.parse(opt.value)); } catch { /* ignore bad option */ }
  }
  return items;
}

async function buildManifest() {
  setText(buildSummary, 'Building…');
  if (btnBuild) btnBuild.disabled = true;

  const items = getSelectedItems();
  if (!items.length) {
    setText(buildSummary, 'Select one or more objects first.');
    if (btnBuild) btnBuild.disabled = false;
    return;
  }

  const t0 = performance.now();
  // Show a live elapsed timer while waiting
  const timer = setInterval(() => {
    const s = ((performance.now() - t0) / 1000).toFixed(0);
    setText(buildSummary, `Building… ${s}s`);
  }, 1000);

  try {
    let res;
    if (items.length === 1) {
      // Single selection: keep existing form route
      const { ds, typ, uuid } = items[0];
      res = await postForm('/dataspaces/manifest/build-uris', {
        ds, typ, uuid,
        include_refs: includeRefs && includeRefs.checked ? 'true' : 'false'
      });
    } else {
      // Multiple selection: call JSON route (NEW)
      const r = await fetch('/dataspaces/manifest/build-from-selection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items,
          include_refs: !!(includeRefs && includeRefs.checked)
          // Optional: legal, owners, viewers, countries, create_missing
        })
      });
      if (!r.ok) {
        let detail = '';
        try {
          const errBody = await r.json();
          const d = errBody.detail || errBody.reason || '';
          detail = typeof d === 'string' ? d : JSON.stringify(d);
        } catch { try { detail = (await r.text()).substring(0, 300); } catch {} }
        throw new Error(`${r.status} ${r.statusText}` + (detail ? ': ' + detail : ''));
      }
      res = await r.json();
    }

    clearInterval(timer);
    const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
    const mf = res.manifest || {};
    const jsonStr = JSON.stringify(mf, null, 2);
    // Wrap each line in a span for line-number CSS
    manifestBox.innerHTML = jsonStr.split('\n')
      .map(l => '<span class="line">' + l.replace(/&/g,'&amp;').replace(/</g,'&lt;') + '</span>')
      .join('');
    let msg = `Built manifest (uris=${res.countUris || 0}) in ${elapsed}s`;
    if (res.skippedUris) {
      msg += ` - ${res.skippedUris} URI(s) skipped (${(res.skippedTypes||[]).join(', ')})`;
    }
    setText(buildSummary, msg);
    if (btnIngest) btnIngest.disabled = false;
  } catch (e) {
    clearInterval(timer);
    const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
    console.warn('build error:', e);
    setText(buildSummary, `Build failed after ${elapsed}s: ${e.message}`);
    if (btnIngest) btnIngest.disabled = true;
  } finally {
    if (btnBuild) btnBuild.disabled = false;
  }
}

  async function ingestManifest() {
    const mfText = manifestBox.textContent || '';
    if (!mfText.trim()) { setText(buildSummary, 'No manifest to ingest.'); return; }
    setText(buildSummary, 'Ingesting…');
    try {
      const manifest = JSON.parse(mfText);
      const r = await fetch('/api/manifest/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ manifest, method: 'storage' })
      });
      if (!r.ok) {
        const errText = await r.text().catch(() => '');
        throw new Error(`${r.status} ${r.statusText}: ${errText.slice(0, 200)}`);
      }
      const res = await r.json();
      let info;
      if (res.method === 'storage') {
        const sr = res.storageResponse || {};
        const sent = sr.recordsSent ?? '?';
        const stored = sr.recordCount ?? '?';
        const ids = sr.recordIds || [];
        info = `${stored} record(s) stored (${sent} sent)`;
        if (ids.length) info += '\n' + ids.join('\n');
      } else {
        info = `workflow run=${res.runId || '?'}`;
      }
      setText(buildSummary, `Ingest OK - ${info}`);
    } catch (e) {
      console.warn('ingest error:', e);
      setText(buildSummary, `Ingest failed: ${e.message}`);
    }
  }

  // Wire events
  if (dsSel) dsSel.addEventListener('change', async () => { await loadTypes(); await loadObjects(); });
  if (typeSel) typeSel.addEventListener('change', loadObjects);
  if (nameFilter) nameFilter.addEventListener('input', loadObjects);
  if (btnLoadRefs) btnLoadRefs.addEventListener('click', loadRefs);
  if (btnBuild) btnBuild.addEventListener('click', buildManifest);
  if (btnIngest) btnIngest.addEventListener('click', ingestManifest);

  // ---- Dataspace two-segment filter for the <select> dropdown ----
  const mfDsF1 = $('#mf-ds-filter-1');
  const mfDsF2 = $('#mf-ds-filter-2');
  let _allDsOptions = [];  // [{value, text}] - filled after dataspaces load

  function _captureDsOptions() {
    if (!dsSel) return;
    _allDsOptions = [];
    for (const opt of dsSel.options) {
      _allDsOptions.push({ value: opt.value, text: opt.textContent });
    }
  }

  function _applyDsSelectFilter() {
    if (!dsSel || !_allDsOptions.length) return;
    const q1 = (mfDsF1 ? mfDsF1.value : '').trim().toLowerCase();
    const q2 = (mfDsF2 ? mfDsF2.value : '').trim().toLowerCase();
    const prevValue = dsSel.value;
    dsSel.innerHTML = '';
    let found = false;
    for (const item of _allDsOptions) {
      const parts = item.value.toLowerCase().split('/');
      const seg1 = parts[0] || '';
      const seg2 = parts.slice(1).join('/');
      if (q1 && !seg1.includes(q1)) continue;
      if (q2 && !seg2.includes(q2)) continue;
      const opt = document.createElement('option');
      opt.value = item.value;
      opt.textContent = item.text;
      dsSel.appendChild(opt);
      if (item.value === prevValue) { opt.selected = true; found = true; }
    }
    if (!found && dsSel.options.length > 0) dsSel.selectedIndex = 0;
  }

  if (mfDsF1) mfDsF1.addEventListener('input', _applyDsSelectFilter);
  if (mfDsF2) mfDsF2.addEventListener('input', _applyDsSelectFilter);

  // Init: dataspaces only - types/objects load on user selection
  async function initManifestUI() {
    if (!dsSel || !objSel) return; // not on index page
    await loadDataspaces(); // respects prefilled options
    // Insert a blank prompt as first option so nothing auto-loads
    const prompt = document.createElement('option');
    prompt.value = '';
    prompt.textContent = '- select a dataspace -';
    dsSel.insertBefore(prompt, dsSel.firstChild);
    dsSel.selectedIndex = 0;
    _captureDsOptions();    // snapshot all options for filtering
    // Don't auto-load types/objects - wait for user to pick a dataspace
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initManifestUI);
  else initManifestUI();
})();


// ===== Keys page: load a single object's details and render metadata/arrays =====
async function loadObjectDetails() {
  // Expect objSel.value to be a JSON string: { ds, typ, uuid }
  if (!objSel || !objSel.value) return;
  let sel;
  try { sel = JSON.parse(objSel.value); } catch { return; }
  const { ds, typ, uuid } = sel;
  if (!ds || !typ || !uuid) return;

  // Build the endpoint URL
  const url = `/keys/object.json?ds=${encodeURIComponent(ds)}&typ=${encodeURIComponent(typ)}&uuid=${encodeURIComponent(uuid)}`;

  // Fetch details
  const r = await fetch(url, { headers: { 'Cache-Control': 'no-store' } });
  if (!r.ok) {
    setText(objErr, `Failed to load details: ${r.status} ${r.statusText}`);
    return;
  }
  const data = await r.json();

  // ---- Render summary
  const summaryBox = document.getElementById('obj-summary');
  if (summaryBox) {
    const p = data.primary || {};
    summaryBox.textContent =
      `Title=${p.title || ''} · UUID=${p.uuid || ''} · Type=${p.typePath || ''} · ContentType=${p.contentType || ''}`;
  }

  // ---- Render metadata pairs table
  const tbody = document.getElementById('md-body');
  if (tbody) {
    tbody.innerHTML = '';
    const md = data.metadata || {};
    const pairs = md.pairs || [];
    if (!pairs.length) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td colspan="2" class="muted">No metadata available.</td>`;
      tbody.appendChild(tr);
    } else {
      for (const row of pairs) {
        const tr = document.createElement('tr');
        const td1 = document.createElement('td'); td1.textContent = String(row.name ?? '');
        const td2 = document.createElement('td'); td2.textContent = String(row.value ?? '');
        tr.appendChild(td1); tr.appendChild(td2);
        tbody.appendChild(tr);
      }
    }
  }

  // ---- Render arrays list (if any)
  const arrList = document.getElementById('arr-list');
  if (arrList) {
    arrList.innerHTML = '';
    const arrays = data.arrays || [];
    if (!arrays.length) {
      const li = document.createElement('li');
      li.textContent = 'No arrays.';
      li.className = 'muted';
      arrList.appendChild(li);
    } else {
      for (const a of arrays) {
        const li = document.createElement('li');
        // Show a compact description; adjust fields if needed
        li.textContent = `${a.PathInResource || a.pathInResource || '(path)'} · ${a.DataType || a.dataType || ''} · count=${a.Count || a.count || ''}`;
        arrList.appendChild(li);
      }
    }
  }
}


// --- Metadata table helpers (search.html) ---
(function () {
  function $(sel, root = document) { return root.querySelector(sel); }
  function $all(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

  // Simple CSV export of a <table> body
  function tableToCSV(table) {
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    const cellsToText = (tr) => Array.from(tr.children).map(td => {
      const t = (td.textContent || '').replace(/\r?\n/g, ' ').trim();
      // Escape CSV if needed
      return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
    });
    const header = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent.trim());
    const lines = [header, ...rows.map(cellsToText)];
    return lines.map(cols => cols.join(',')).join('\n');
  }

  // Copy helper
  async function copyCSV(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fallback: temporary textarea
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select(); document.execCommand('copy');
      document.body.removeChild(ta);
      return true;
    }
  }

  // Sort table by a column index
  function sortTable(table, colIdx, asc) {
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const getVal = (tr) => (tr.children[colIdx]?.textContent || '').toLowerCase();
    rows.sort((a, b) => {
      const va = getVal(a), vb = getVal(b);
      if (va < vb) return asc ? -1 : 1;
      if (va > vb) return asc ? 1 : -1;
      return 0;
    });
    rows.forEach(r => tbody.appendChild(r));
  }

  // Wire sorting and copy + filter for every meta-table
  function initMetaTables() {
    $all('.meta-container').forEach(container => {
      const table = $('.meta-table', container);
      if (!table) return;

      // Sorting by clicking headers
      $all('thead th', table).forEach((th, idx) => {
        let asc = true;
        th.style.cursor = 'pointer';
        th.addEventListener('click', () => {
          sortTable(table, idx, asc);
          asc = !asc;
        });
      });

      // Copy button
      const btn = $('.meta-copy', container);
      if (btn) {
        btn.addEventListener('click', async () => {
          const csv = tableToCSV(table);
          const ok = await copyCSV(csv);
          if (ok) { btn.textContent = 'Copied ✓'; setTimeout(() => btn.textContent = 'Copy (CSV)', 1200); }
        });
      }

      // Filter input (by Name column)
      const filter = $('.meta-filter', container);
      if (filter) {
        filter.addEventListener('input', () => {
          const q = filter.value.trim().toLowerCase();
          $all('tbody tr', table).forEach(tr => {
            const name = (tr.querySelector('.meta-name')?.textContent || '').toLowerCase();
            tr.style.display = !q || name.includes(q) ? '' : 'none';
          });
        });
      }
    });
  }

  // Re-run init when a record block becomes visible (search.html calls showBlock)
  document.addEventListener('DOMContentLoaded', initMetaTables);
  // In case search.html toggles visibility after selection, observe DOM changes lightly
  const obs = new MutationObserver(() => initMetaTables());
  obs.observe(document.body, { childList: true, subtree: true });
})();

// Wire it: load details when an object is selected
if (objSel) objSel.addEventListener('change', loadObjectDetails);
