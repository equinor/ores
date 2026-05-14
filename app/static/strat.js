(function(){
  'use strict';

  const $ = (sel, root=document) => root.querySelector(sel);
  const qInput     = $('#strat-q');
  const typeSelect  = $('#strat-type');
  const limitInput = $('#strat-limit');
  const btnSearch  = $('#btn-search');
  const resSelect  = $('#strat-results');
  const searchStat = $('#search-status');
  const statusBox  = $('#load-status');
  const legendBox  = $('#legend');
  const matrixRoot = $('#matrix-root');
  const metaBody   = $('#meta-body');

  const setStatus = (msg) => { if (statusBox) statusBox.textContent = msg || ''; };
  const clear = (el) => { if (el) el.innerHTML=''; };

  /* ------------------------------------------------------------------ */
  /*  METADATA helper                                                   */
  /* ------------------------------------------------------------------ */
  function renderMetaPairs(obj){
    if (!metaBody) return;
    function flt(val, path='', out=[]){
      if (val && typeof val === 'object' && !Array.isArray(val))
        for (const [k,v] of Object.entries(val)) flt(v, path ? `${path}.${k}` : k, out);
      else if (Array.isArray(val)) val.forEach((v,i)=>flt(v, path?`${path}.${i}`:`${i}`, out));
      else out.push({name:path, value:(val===null||val===undefined)?'-':String(val)});
      return out;
    }
    const pairs = flt(obj);
    clear(metaBody);
    if (!pairs.length){ metaBody.innerHTML='<tr><td class="muted">No metadata</td><td></td></tr>'; return; }
    for (const p of pairs){
      const tr=document.createElement('tr');
      tr.innerHTML=`<td class="meta-name">${p.name}</td><td>${p.value}</td>`;
      metaBody.appendChild(tr);
    }
  }

  /* ------------------------------------------------------------------ */
  /*  CONTAINMENT helpers                                               */
  /* ------------------------------------------------------------------ */
  /** Normalize a name for fuzzy matching: strip trailing punctuation. */
  function _normName(s) {
    return (s || '').toLowerCase().trim().replace(/[.\-,]+$/g, '').trim();
  }

  /** Normalize age pair to (olderMa, youngerMa) regardless of convention. */
  function ageNorm(a, b) {
    if (a == null || b == null) return [null, null];
    return a >= b ? [a, b] : [b, a];
  }

  /** Convention-agnostic age containment check (0.5 Ma tolerance). */
  function ageContained(child, parent) {
    const [co, cy] = ageNorm(child.topMa, child.baseMa);
    const [po, py] = ageNorm(parent.topMa, parent.baseMa);
    if (co == null || po == null) return false;
    return co <= po + 0.5 && cy >= py - 0.5;
  }

  function isContainedIn(child, parent) {
    // 1. ParentName: authoritative parent declaration (fuzzy match)
    if (child.parentName) {
      if (_normName(child.parentName) === _normName(parent.name)) return true;
      // parentName set but doesn't match this parent - fall through to age
    }
    // 2. Chrono Code hierarchy (e.g. "Phanerozoic.Paleozoic.Silurian")
    if (child.code && parent.code) {
      return child.code.startsWith(parent.code + '.') || child.code === parent.code;
    }
    // 3. Age containment: convention-agnostic (works for both SMDA and ICS)
    return ageContained(child, parent);
  }

  /* ------------------------------------------------------------------ */
  /*  BUILD HIERARCHY TREE                                              */
  /*  Ranks kept in original OSDU order (coarsest → finest).            */
  /*  Parent–child via age/code containment; leaf nodes get colSpan     */
  /*  to fill remaining columns.  Row count = number of leaves.         */
  /* ------------------------------------------------------------------ */
  function buildHierarchy(model) {
    const ranks = (model.ranks || []).map((rk, ri) => ({
      rankName: rk.rankName || 'Unspecified',
      isChrono: !!rk.isChrono,
      units: (rk.units || []).map((u, ui) => {
        const [olderMa, youngerMa] = ageNorm(
          (u.topMa != null) ? u.topMa : (u.olderMa ?? null),
          (u.baseMa != null) ? u.baseMa : (u.youngerMa ?? null));
        return {
          name:   u.name   || '(unit)',
          topMa:  (u.topMa  != null) ? u.topMa  : null,
          baseMa: (u.baseMa != null) ? u.baseMa : null,
          olderMa, youngerMa,
          color:  u.color  || null,
          code:   u.code   || '',
          parentName: u.parentName || '',
          _synthetic: !!u._synthetic,
          _origIdx: (u._origIdx != null) ? u._origIdx : ui,
          horizonTop:  u.horizonTop  || null,
          horizonBase: u.horizonBase || null,
        };
      })
    })).filter(rk => rk.units.length > 0);

    if (!ranks.length) return null;
    const nRanks = ranks.length;

    // Create tree nodes
    const levels = ranks.map((rk, ri) =>
      rk.units.map(u => ({
        ...u,
        rankIdx:   ri,
        rankName:  rk.rankName,
        children:  [],
        parent:    null,
        leafCount: 0,
        rowStart:  0,
        isLeaf:    false,
        colSpan:   1,
      }))
    );

    // ── Helper: make a synthetic stub node at a given rank ──
    function _makeSynth(name, rankIdx, children) {
      const olders   = children.map(c => c.olderMa).filter(v => v != null);
      const youngers = children.map(c => c.youngerMa).filter(v => v != null);
      const older  = olders.length  ? Math.max(...olders)  : null;
      const younger = youngers.length ? Math.min(...youngers) : null;
      const node = {
        name, topMa: older, baseMa: younger,
        olderMa: older, youngerMa: younger,
        color: null, code: '', parentName: '', _synthetic: true,
        _origIdx: 9999, horizonTop: null, horizonBase: null,
        rankIdx, rankName: ranks[rankIdx].rankName,
        children: [], parent: null, leafCount: 0, rowStart: 0,
        isLeaf: false, colSpan: 1,
      };
      levels[rankIdx].push(node);
      for (const c of children) { node.children.push(c); c.parent = node; }
      return node;
    }

    // ── Helper: find a node by name at any rank ≤ maxRank ──
    function _findByName(name, maxRank) {
      const key = _normName(name);
      if (!key) return null;
      for (let pi = maxRank; pi >= 0; pi--)
        for (const p of levels[pi])
          if (_normName(p.name) === key) return p;
      return null;
    }

    // ── Helper: find best age-containment parent for a child ──
    function _findByAge(child, maxRank) {
      let bestParent = null, bestRange = Infinity, bestRank = -1;
      for (let pi = maxRank; pi >= 0; pi--) {
        for (const p of levels[pi]) {
          if (!ageContained(child, p)) continue;
          const range = (p.olderMa != null && p.youngerMa != null)
            ? (p.olderMa - p.youngerMa) : Infinity;
          if (pi > bestRank || (pi === bestRank && range < bestRange)) {
            bestParent = p; bestRange = range; bestRank = pi;
          }
        }
        if (bestParent && bestRank === pi) break;
      }
      return bestParent;
    }

    // ── Assign parents ──
    // For each child unit, try these strategies in order:
    //   1. parentName match (fuzzy) - authoritative for litho columns
    //   2. Age containment fallback - when parentName is set but no name
    //      match exists (data inconsistency) or when parentName is absent
    //   3. Code hierarchy - chrono code containment
    // If the named parent exists at a NON-ADJACENT rank, synthesize
    // intermediate stubs at every skipped rank.
    function _linkToTarget(child, target, ri) {
      if (target.rankIdx === ri - 1) {
        target.children.push(child);
        child.parent = target;
      } else {
        // Parent is 2+ ranks above - fill intermediate ranks.
        // At each intermediate rank, prefer an existing REAL node that
        // age-contains the child over creating a synthetic stub.  This
        // prevents orphan entries from different schemes (e.g. Hardenbol)
        // from spawning redundant stubs that sort incorrectly.
        let cur = target;
        for (let mid = target.rankIdx + 1; mid < ri; mid++) {
          let label = child.parentName || child.name;
          // 1. Reuse existing synthetic stub with same name
          let stub = cur.children.find(
            c => c.rankIdx === mid && c._synthetic &&
                 _normName(c.name) === _normName(label));
          // 2. Prefer a real node that age-contains the child
          if (!stub) {
            stub = cur.children.find(
              c => c.rankIdx === mid && !c._synthetic &&
                   ageContained(child, c));
          }
          // 3. Fallback: create a synthetic stub
          if (!stub) {
            stub = _makeSynth(label, mid, []);
            cur.children.push(stub); stub.parent = cur;
          }
          cur = stub;
        }
        cur.children.push(child);
        child.parent = cur;
        // Update synthetic ancestor ages to reflect new child
        let anc = cur;
        while (anc && anc._synthetic) {
          let needsUpdate = false;
          if (child.olderMa != null && (anc.olderMa == null || child.olderMa > anc.olderMa)) {
            anc.olderMa = child.olderMa; anc.topMa = child.olderMa; needsUpdate = true;
          }
          if (child.youngerMa != null && (anc.youngerMa == null || child.youngerMa < anc.youngerMa)) {
            anc.youngerMa = child.youngerMa; anc.baseMa = child.youngerMa; needsUpdate = true;
          }
          if (!needsUpdate) break;
          anc = anc.parent;
        }
      }
    }

    for (let ri = 1; ri < nRanks; ri++) {
      for (const child of levels[ri]) {
        // 1. Try parentName match (fuzzy)
        if (child.parentName) {
          const target = _findByName(child.parentName, ri - 1);
          if (target) {
            _linkToTarget(child, target, ri);
            continue;
          }
        }
        // 2. Try age containment (works for all column types)
        const agePar = _findByAge(child, ri - 1);
        if (agePar) {
          _linkToTarget(child, agePar, ri);
          continue;
        }
        // 3. Try code hierarchy
        if (child.code) {
          for (let pi = ri - 1; pi >= 0; pi--) {
            const codePar = levels[pi].find(p => p.code && child.code.startsWith(p.code + '.'));
            if (codePar) {
              _linkToTarget(child, codePar, ri);
              break;
            }
          }
        }
        // If still orphan, handled by synthesis below
      }
    }

    // ── Synthesize stubs for remaining orphans with parentName ──
    for (let ri = 1; ri < nRanks; ri++) {
      const orphans = levels[ri].filter(n => !n.parent && n.parentName);
      if (!orphans.length) continue;
      const byParent = new Map();
      for (const o of orphans) {
        const key = _normName(o.parentName);
        if (!byParent.has(key)) byParent.set(key, { displayName: o.parentName, children: [] });
        byParent.get(key).children.push(o);
      }
      for (const [, group] of byParent) {
        _makeSynth(group.displayName, ri - 1, group.children);
      }
    }

    // ── Nest remaining orphan stubs under higher-rank ancestors ──
    for (let ri = nRanks - 1; ri >= 1; ri--) {
      for (const node of levels[ri]) {
        if (node.parent) continue;
        if (node.parentName) {
          const t = _findByName(node.parentName, ri - 1);
          if (t) { t.children.push(node); node.parent = t; continue; }
        }
        const agePar = _findByAge(node, ri - 1);
        if (agePar) { agePar.children.push(node); node.parent = agePar; continue; }
      }
    }

    // Collect roots (no parent) - rank-0 nodes + orphans from deeper ranks
    const roots = [];
    for (let ri = 0; ri < nRanks; ri++)
      for (const n of levels[ri])
        if (!n.parent) roots.push(n);

    // Sort roots: older (bigger Ma) first, then by data-model order as tiebreaker
    function _sortKey(a, b) {
      const ao = a.olderMa ?? -Infinity, bo = b.olderMa ?? -Infinity;
      if (ao !== bo) return bo - ao;                      // older first
      return (a._origIdx ?? 9999) - (b._origIdx ?? 9999); // then model order
    }
    roots.sort(_sortKey);

    // Compute leaf counts + colSpan
    function computeLeaf(node) {
      if (node.children.length === 0) {
        node.isLeaf = true;
        node.leafCount = 1;
        node.colSpan = nRanks - node.rankIdx;   // span to rightmost column
      } else {
        node.isLeaf = false;
        node.children.sort(_sortKey);
        node.leafCount = 0;
        for (const c of node.children) {
          computeLeaf(c);
          node.leafCount += c.leafCount;
        }
        const minChildRank = Math.min(...node.children.map(c => c.rankIdx));
        node.colSpan = minChildRank - node.rankIdx;
      }
    }
    for (const r of roots) computeLeaf(r);

    // Assign row starts via DFS
    let rowIdx = 0;
    function assignRows(nodes) {
      for (const n of nodes) {
        n.rowStart = rowIdx;
        if (n.isLeaf) rowIdx++;
        else assignRows(n.children);
      }
    }
    assignRows(roots);

    const totalRows = rowIdx;

    // Column metadata: rank-level gradient dark → light
    const columns = ranks.map((rk, ri) => {
      const t = nRanks === 1 ? 0.5 : ri / (nRanks - 1);
      const lightness  = Math.round(36 + t * 50);    // 36% → 86%
      const saturation = Math.round(46 - t * 16);    // 46% → 30%
      const bg = `hsl(210, ${saturation}%, ${lightness}%)`;
      const fg = lightness < 55 ? '#fff' : '#222';
      return { rankName: rk.rankName, bg, fg, nodes: levels[ri] };
    });

    return { columns, totalRows, nRanks };
  }

  /* ------------------------------------------------------------------ */
  /*  RENDER LEGEND                                                     */
  /* ------------------------------------------------------------------ */
  function renderLegend(columns) {
    clear(legendBox);
    if (!columns) return;
    for (const col of columns) {
      const wrap = document.createElement('span');
      wrap.className = _hiddenRanks.has(col.rankName) ? 'legend-item off' : 'legend-item';
      const sw = document.createElement('i');
      sw.className = 'legend-sw';
      sw.style.cssText = `width:14px;height:14px;display:inline-block;border-radius:3px;border:1px solid rgba(0,0,0,.18);background:${col.bg};`;
      wrap.appendChild(sw);
      const lbl = document.createElement('span');
      lbl.textContent = `${col.rankName} (${col.nodes.length})`;
      wrap.appendChild(lbl);
      wrap.addEventListener('click', () => toggleRank(col.rankName));
      legendBox.appendChild(wrap);
    }
  }

  function toggleRank(rankName) {
    if (_hiddenRanks.has(rankName)) _hiddenRanks.delete(rankName);
    else _hiddenRanks.add(rankName);
    refreshHierarchy();
  }

  /** Re-build + re-render hierarchy using _cachedModel with hidden ranks filtered out. */
  function refreshHierarchy() {
    if (!_cachedModel) return;
    // Build full hierarchy (all ranks) for legend counts
    const fullHierarchy = buildHierarchy(_cachedModel);
    renderLegend(fullHierarchy ? fullHierarchy.columns : []);
    // Filtered model: only visible ranks
    const filtered = {
      ..._cachedModel,
      ranks: (_cachedModel.ranks || []).filter(rk => !_hiddenRanks.has(rk.rankName || 'Unspecified')),
    };
    const hierarchy = buildHierarchy(filtered);
    renderHierarchy(hierarchy);
    // Update status row count
    if (hierarchy) {
      const info = `${hierarchy.totalRows} rows \u00d7 ${hierarchy.nRanks} ranks`;
      const isSingleRank = !!(_cachedModel.column || {})._singleRank;
      const prefix = isSingleRank ? 'Single Rank' : 'OK';
      setStatus(`${prefix} - ${info}`);
    }
  }

  /* ------------------------------------------------------------------ */
  /*  RENDER HIERARCHY TABLE                                            */
  /* ------------------------------------------------------------------ */
  function fmtAge(v) {
    if (v == null) return '';
    return Math.round(v * 100) / 100;
  }
  function isLightColor(hex) {
    if (!hex || hex[0] !== '#') return true;
    const r = parseInt(hex.substr(1,2),16),
          g = parseInt(hex.substr(3,2),16),
          b = parseInt(hex.substr(5,2),16);
    return (0.299*r + 0.587*g + 0.114*b) > 155;
  }

  function renderHierarchy(hierarchy) {
    clear(matrixRoot);
    if (!hierarchy || hierarchy.totalRows === 0) {
      matrixRoot.innerHTML = '<p class="muted" style="padding:.5rem;">No stratigraphic units to display.</p>';
      return;
    }
    const { columns, totalRows, nRanks } = hierarchy;

    // Build start-map per column: row → node
    const startMap = columns.map(col => {
      const m = new Map();
      for (const node of col.nodes) m.set(node.rowStart, node);
      return m;
    });

    const table = document.createElement('table');
    table.className = 'sc-table';

    //  Header
    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    for (const col of columns) {
      const th = document.createElement('th');
      th.textContent = col.rankName;
      th.className = 'rank-col';
      th.style.background = col.bg;
      th.style.color = col.fg;
      hr.appendChild(th);
    }
    thead.appendChild(hr);
    table.appendChild(thead);

    //  Body
    const tbody = document.createElement('tbody');
    const coveredUntil = new Array(nRanks).fill(-1);

    for (let r = 0; r < totalRows; r++) {
      const tr = document.createElement('tr');

      for (let c = 0; c < nRanks; c++) {
        if (r <= coveredUntil[c]) continue;           // covered by rowspan / colspan

        const node = startMap[c].get(r);
        if (node) {
          const td = document.createElement('td');
          td.className = node._synthetic ? 'sc-cell sc-synthetic' : 'sc-cell';
          if (node.leafCount > 1)  td.rowSpan = node.leafCount;
          if (node.colSpan  > 1)   td.colSpan = node.colSpan;

          // Background: prefer ICS chrono colour; else rank gradient
          const bgColor = node.color || columns[c].bg;
          td.style.background = bgColor;
          td.style.color = node.color ? (isLightColor(node.color) ? '#222' : '#fff') : columns[c].fg;

          // Name
          const nameEl = document.createElement('strong');
          nameEl.textContent = node.name;
          td.appendChild(nameEl);

          // Age (supplementary info - always show older–younger)
          if (node.olderMa != null && node.youngerMa != null) {
            const ageEl = document.createElement('div');
            ageEl.className = 'sc-age';
            ageEl.textContent = `${fmtAge(node.youngerMa)}\u2013${fmtAge(node.olderMa)} Ma`;
            td.appendChild(ageEl);
          }

          // Horizon boundary labels (real OSDU HorizonInterpretation data)
          if (node.horizonTop) {
            td.classList.add('sc-horizon-top');
            const hEl = document.createElement('div');
            hEl.className = 'sc-horizon';
            hEl.textContent = `\u25B3 ${node.horizonTop.name}`;
            td.appendChild(hEl);
          }
          if (node.horizonBase) {
            td.classList.add('sc-horizon-base');
            const hEl = document.createElement('div');
            hEl.className = 'sc-horizon';
            hEl.textContent = `\u25BD ${node.horizonBase.name}`;
            td.appendChild(hEl);
          }

          td.title = node.name
            + (node.olderMa != null ? `\n${node.youngerMa}\u2013${node.olderMa} Ma` : '')
            + (node.code  ? `\n${node.code}` : '');

          tr.appendChild(td);

          // Mark coverage
          const endRow = r + node.leafCount - 1;
          for (let cc = c; cc < Math.min(c + node.colSpan, nRanks); cc++)
            coveredUntil[cc] = Math.max(coveredUntil[cc], endRow);
        } else {
          // Uncovered empty cell (rare with colSpan logic)
          const td = document.createElement('td');
          td.className = 'sc-cell sc-empty';
          tr.appendChild(td);
        }
      }
      tbody.appendChild(tr);
    }

    table.appendChild(tbody);
    matrixRoot.appendChild(table);
  }

  /* ------------------------------------------------------------------ */
  /*  LOAD + SEARCH                                                     */
  /* ------------------------------------------------------------------ */
  let currentColumnId = null;  // Track currently loaded column for RDDMS push
  let _cachedModel = null;       // Full model for legend-toggle re-renders
  const _hiddenRanks = new Set(); // rankName strings currently toggled off

  async function loadColumnById(id){
    const rid = (id||'').trim();
    if (!rid) { setStatus('Select a Column or Rank.'); return; }
    setStatus('Loading\u2026');
    currentColumnId = null;
    const rddmsColInfo = document.getElementById('rddms-col-info');
    const btnRddmsPushEl = document.getElementById('btn-rddms-push');
    if (rddmsColInfo) rddmsColInfo.textContent = 'Loading…';
    if (btnRddmsPushEl) btnRddmsPushEl.disabled = true;
    try {
      const url = `/api/strat/column.json?id=${encodeURIComponent(rid)}&enrich=true`;
      const res = await fetch(url, { headers:{'Cache-Control':'no-store'} });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const model = await res.json();
      _cachedModel = model;
      _hiddenRanks.clear();
      const isSingleRank = !!(model.column || {})._singleRank;
      const hierarchy = buildHierarchy(model);
      renderLegend(hierarchy ? hierarchy.columns : []);
      renderHierarchy(hierarchy);
      renderMetaPairs({
        column: model.column || {},
        ranks: (model.ranks || []).map(r => ({
          rankName: r.rankName,
          unitCount: r.unitCount || (r.units||[]).length
        }))
      });
      const info = hierarchy
        ? `${hierarchy.totalRows} rows \u00d7 ${hierarchy.nRanks} ranks`
        : 'empty';
      const prefix = isSingleRank ? 'Single Rank' : 'OK';
      setStatus(`${prefix} - ${info}`);
      // Enable RDDMS push after successful load
      currentColumnId = rid;
      const colName = (model.column || {}).name || rid;
      if (rddmsColInfo) rddmsColInfo.innerHTML = `Column loaded: <strong>${colName}</strong> - ready to push.`;
      if (btnRddmsPushEl) btnRddmsPushEl.disabled = false;

      // Count real (non-synthetic) units and horizons
      let totalUnits = 0;
      for (const rk of (model.ranks || [])) {
        for (const u of (rk.units || [])) { if (!u._synthetic) totalUnits++; }
      }
      const hc = model.horizonCount || 0;

      // Generate Horizons panel: only if real units exist
      const horizonPanel = document.getElementById('horizon-panel');
      if (horizonPanel) {
        horizonPanel.style.display = totalUnits > 0 ? 'block' : 'none';
        const hInfo = document.getElementById('horizon-info');
        if (hInfo) {
          hInfo.textContent = hc > 0
            ? `This column already has ${hc} HorizonInterpretation record(s) in OSDU.`
            : 'No HorizonInterpretation records found for this column (none linked from units).';
        }
      }
      // Generate Units panel: only if horizons exist
      const unitgenPanel = document.getElementById('unitgen-panel');
      if (unitgenPanel) {
        unitgenPanel.style.display = hc > 0 ? 'block' : 'none';
        const ugInfo = document.getElementById('unitgen-info');
        if (ugInfo) {
          ugInfo.textContent = `${hc} horizon(s) available \u2192 can generate up to ${Math.max(0, hc - 1)} unit interval(s). Column currently has ${totalUnits} unit(s).`;
        }
      }
    } catch(e) {
      console.warn(e);
      setStatus('Load failed: ' + e.message);
    }
  }

  async function doSearch(){
    const q = (qInput.value||'*').trim();
    const lim = Math.max(1, Math.min(1000, parseInt(limitInput.value||'50', 10)));
    const stype = (typeSelect ? typeSelect.value : 'all') || 'all';
    searchStat.textContent = 'Searching\u2026';
    resSelect.innerHTML = '<option value="">- searching -</option>';
    try {
      const url = `/api/strat/search.json?q=${encodeURIComponent(q)}&limit=${lim}&type=${stype}`;
      const r = await fetch(url, { headers:{'Cache-Control':'no-store'} });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const data = await r.json();
      const items = data.items || [];
      resSelect.innerHTML = '';
      if (!items.length) {
        resSelect.innerHTML = '<option value="">- no results -</option>';
        searchStat.textContent = 'No results';
        clear(legendBox); clear(matrixRoot);
        return;
      }
      // Sort: Columns first, then Ranks, then Units
      const cols  = items.filter(i => i.type === 'column');
      const ranks = items.filter(i => i.type === 'rank');
      const units = items.filter(i => i.type === 'unit');
      for (const it of [...cols, ...ranks, ...units]) {
        const opt = document.createElement('option');
        opt.value = it.id;
        const badge = it.type === 'rank' ? 'Rank'
          : it.type === 'unit' ? 'Unit'
          : 'Column';
        const extra = it.source === 'storage' ? ' \u23f3 (indexing)' : '';
        opt.textContent = `[${badge}] ${it.name||it.id} - ${it.id}${extra}`;
        // Highlight chrono vs litho
        const hint = ((it.name || '') + ' ' + (it.id || '')).toLowerCase();
        if (hint.includes('chrono')) {
          opt.style.background = '#a6e6a6';  // green
        } else if (hint.includes('litho')) {
          opt.style.background = '#d6e4f0';  // blue-grey
        }
        resSelect.appendChild(opt);
      }
      resSelect.selectedIndex = 0;
      const nCols = cols.length, nRanks = ranks.length, nUnits = units.length;
      const parts = [];
      if (nCols) parts.push(`${nCols} column(s)`);
      if (nRanks) parts.push(`${nRanks} rank(s)`);
      if (nUnits) parts.push(`${nUnits} unit(s)`);
      searchStat.textContent = `Found ${parts.join(', ') || '0 results'}`;
      if (stype !== 'unit') loadColumnById(resSelect.value);
    } catch(e) {
      console.warn(e);
      resSelect.innerHTML = '<option value="">- error -</option>';
      searchStat.textContent = 'Search failed: ' + e.message;
    }
  }

  btnSearch?.addEventListener('click', doSearch);
  resSelect?.addEventListener('change', () => {
    const id = resSelect.value || '';
    if (id) loadColumnById(id);
  });

  // Examples popup
  const btnEx = $('#btn-examples');
  const exPopup = $('#examples-popup');
  btnEx?.addEventListener('click', (e) => {
    e.stopPropagation();
    exPopup.classList.toggle('open');
  });
  exPopup?.querySelectorAll('.ex-item').forEach(item => {
    item.addEventListener('click', () => {
      const q = item.getAttribute('data-q');
      const inp = $('#strat-q');
      if (inp && q != null) inp.value = q;
      exPopup.classList.remove('open');
    });
  });
  document.addEventListener('click', () => exPopup?.classList.remove('open'));

  // Direct load by pasted ID
  const directIdInput = $('#direct-id');
  const btnDirectLoad = $('#btn-direct-load');
  btnDirectLoad?.addEventListener('click', () => {
    const id = (directIdInput?.value || '').trim();
    if (id) loadColumnById(id);
  });
  directIdInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const id = (directIdInput?.value || '').trim();
      if (id) loadColumnById(id);
    }
  });

  /* ================================================================ */
  /*  IMPORT / INGEST TAB UI                                          */
  /* ================================================================ */

  // Tab switching
  document.querySelectorAll('.imp-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.imp-tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.imp-body').forEach(b => b.classList.remove('active'));
      tab.classList.add('active');
      const body = document.getElementById('imp-' + tab.dataset.tab);
      if (body) body.classList.add('active');
    });
  });

  function impStatus(id, msg, cls) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = msg;
    el.className = 'imp-status ' + (cls || 'info');
    el.style.display = 'block';
  }

  function impPreview(id, bundle) {
    const el = document.getElementById(id);
    if (!el) return;
    const recs = (bundle && bundle.records) || [];
    const kinds = {};
    recs.forEach(r => { const k = (r.kind||'').split('--').pop().split(':')[0]; kinds[k] = (kinds[k]||0)+1; });
    let html = `<strong>${recs.length} records</strong><br>`;
    for (const [k,v] of Object.entries(kinds)) html += `&bull; ${k}: ${v}<br>`;
    html += `<details style="margin-top:.4rem;"><summary class="muted">Raw JSON (first 3 records)</summary>`;
    html += `<pre style="max-height:200px;overflow:auto;font-size:11.5px;">${JSON.stringify(recs.slice(0,3), null, 2)}</pre></details>`;
    el.innerHTML = html;
  }

  function downloadJSON(obj, filename) {
    const blob = new Blob([JSON.stringify(obj, null, 2)], {type:'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // Shared ingest function - sends records to OSDU Storage API
  async function doIngest(bundle, partition, statusId) {
    impStatus(statusId, 'Sending to OSDU…', 'info');
    try {
      const r = await fetch('/api/strat/storage/put', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({bundle, partition}),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || r.statusText);
      impStatus(statusId, `${data.status}: ${data.created || data.totalRecords || '?'} records sent to OSDU`, 'ok');

      // Auto-refresh search - backend discovers un-indexed columns via Rank records
      setTimeout(() => doSearch(), 500);
    } catch(e) {
      impStatus(statusId, 'Send failed: ' + e.message, 'err');
    }
  }

  /* ---- OpenWorks tab ---- */
  let owBundle = null;
  const btnOwConvert  = document.getElementById('btn-ow-convert');
  const btnOwStorage  = document.getElementById('btn-ow-storage');
  const btnOwDownload = document.getElementById('btn-ow-download');

  btnOwConvert?.addEventListener('click', async () => {
    const fileInput = document.getElementById('ow-file');
    const file = fileInput?.files?.[0];
    if (!file) { impStatus('ow-status', 'Select a JSON file first', 'err'); return; }
    const partition = document.getElementById('ow-partition')?.value || 'data';
    impStatus('ow-status', 'Converting…', 'info');
    const fd = new FormData();
    fd.append('file', file);
    fd.append('partition', partition);
    try {
      const r = await fetch('/api/strat/import/ow', {method:'POST', body:fd});
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || r.statusText);
      owBundle = data.bundle;
      impStatus('ow-status', `Converted: "${data.columnName}" - ${data.rankCount} ranks, ${data.unitCount} units`, 'ok');
      impPreview('ow-preview', owBundle);
      btnOwStorage.disabled = false;
      btnOwDownload.disabled = false;
    } catch(e) {
      owBundle = null;
      impStatus('ow-status', 'Conversion failed: ' + e.message, 'err');
    }
  });
  btnOwStorage?.addEventListener('click', () => {
    if (owBundle) doIngest(owBundle, document.getElementById('ow-partition')?.value, 'ow-status');
  });
  btnOwDownload?.addEventListener('click', () => {
    if (owBundle) downloadJSON(owBundle, 'strat_column_osdu_bundle.json');
  });

  /* ---- SMDA tab ---- */
  let smdaBundle = null;
  const btnSmdaList    = document.getElementById('btn-smda-list');
  const btnSmdaFetch   = document.getElementById('btn-smda-fetch');
  const btnSmdaStorage = document.getElementById('btn-smda-storage');
  const btnSmdaDownload= document.getElementById('btn-smda-download');

  // Check SMDA auth status and update hint
  (async () => {
    try {
      const r = await fetch('/auth');
      const d = await r.json();
      const hint = document.getElementById('smda-auth-hint');
      if (!hint) return;
      if (d.smda_api_id) {
        hint.innerHTML = '<span style="color:#4caf50;">&#x2713; SMDA configured (az CLI auth)</span>';
      } else {
        hint.innerHTML = '<span style="color:#e65100;">&#x26A0; SMDA_CLIENT_ID not set</span>';
      }
    } catch(e) {}
  })();

  let smdaColumnsDetails = [];   // enriched column metadata from SMDA

  btnSmdaList?.addEventListener('click', async () => {
    const smdaUrl = document.getElementById('smda-url')?.value || '';
    impStatus('smda-status', 'Listing columns…', 'info');
    try {
      const r = await fetch(`/api/strat/smda/columns.json?smda_url=${encodeURIComponent(smdaUrl)}`);
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || r.statusText);
      smdaColumnsDetails = data.details || (data.columns || []).map(c => ({name:c}));
      _renderSmdaColumns(smdaColumnsDetails);
      document.getElementById('smda-columns-list').style.display = 'block';
      impStatus('smda-status', `Found ${data.total} column identifiers`, 'ok');
    } catch(e) {
      impStatus('smda-status', 'List failed: ' + e.message, 'err');
    }
  });

  function _renderSmdaColumns(items, filter) {
    const sel = document.getElementById('smda-columns-sel');
    const countEl = document.getElementById('smda-columns-count');
    sel.innerHTML = '';
    const filt = (filter || '').toLowerCase();
    let shown = 0;
    items.forEach(c => {
      const name = c.name || c;
      const typeBadge = c.type ? ` [${c.type}]` : '';
      const areaBadge = c.area ? ` (${c.area})` : '';
      const label = `${name}${typeBadge}${areaBadge}`;
      if (filt && !label.toLowerCase().includes(filt)) return;
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = label;
      sel.appendChild(opt);
      shown++;
    });
    if (countEl) countEl.textContent = filt ? `${shown} / ${items.length}` : `${items.length} columns`;
  }

  document.getElementById('smda-columns-filter')?.addEventListener('input', function() {
    _renderSmdaColumns(smdaColumnsDetails, this.value);
  });

  document.getElementById('smda-columns-sel')?.addEventListener('change', function() {
    const opts = Array.from(this.selectedOptions).map(o => o.value);
    document.getElementById('smda-col').value = opts[0] || '';
    const batchBtn = document.getElementById('btn-smda-batch');
    if (batchBtn) batchBtn.textContent = opts.length > 1
      ? `Batch Fetch & Ingest (${opts.length})`
      : 'Batch Fetch & Ingest Selected';
  });

  btnSmdaFetch?.addEventListener('click', async () => {
    const col = document.getElementById('smda-col')?.value?.trim();
    if (!col) { impStatus('smda-status', 'Enter a column identifier', 'err'); return; }
    const smdaUrl = document.getElementById('smda-url')?.value || '';
    const partition = document.getElementById('smda-partition')?.value || 'data';
    impStatus('smda-status', `Fetching "${col}" from SMDA…`, 'info');
    const fd = new FormData();
    fd.append('column', col);
    fd.append('smda_url', smdaUrl);
    fd.append('partition', partition);
    try {
      const r = await fetch('/api/strat/import/smda', {method:'POST', body:fd});
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || r.statusText);
      smdaBundle = data.bundle;
      impStatus('smda-status', `Fetched: "${data.columnName}" - ${data.rankCount} ranks, ${data.unitCount} units`, 'ok');
      impPreview('smda-preview', smdaBundle);
      btnSmdaStorage.disabled = false;
      btnSmdaDownload.disabled = false;
      // Show RDDMS push panel
      const rddmsPanel = document.getElementById('smda-rddms-panel');
      if (rddmsPanel) rddmsPanel.style.display = 'block';
    } catch(e) {
      smdaBundle = null;
      impStatus('smda-status', 'Fetch failed: ' + e.message, 'err');
    }
  });
  btnSmdaStorage?.addEventListener('click', () => {
    if (smdaBundle) doIngest(smdaBundle, document.getElementById('smda-partition')?.value, 'smda-status');
  });
  btnSmdaDownload?.addEventListener('click', () => {
    if (smdaBundle) downloadJSON(smdaBundle, 'smda_strat_osdu_bundle.json');
  });

  /* ---- SMDA batch fetch & ingest ---- */
  let _batchRunning = false;
  document.getElementById('btn-smda-batch')?.addEventListener('click', async () => {
    const sel = document.getElementById('smda-columns-sel');
    const cols = Array.from(sel.selectedOptions).map(o => o.value);
    if (!cols.length) { impStatus('smda-status', 'Select one or more columns from the list first', 'err'); return; }
    if (_batchRunning) { impStatus('smda-status', 'Batch already running…', 'err'); return; }
    _batchRunning = true;
    const smdaUrl = document.getElementById('smda-url')?.value || '';
    const partition = document.getElementById('smda-partition')?.value || 'data';
    const batchBtn = document.getElementById('btn-smda-batch');
    batchBtn.disabled = true;
    let ok = 0, fail = 0;
    const errors = [];
    for (let i = 0; i < cols.length; i++) {
      const col = cols[i];
      impStatus('smda-status', `[${i+1}/${cols.length}] Fetching "${col}" from SMDA…`, 'info');
      try {
        // 1. Fetch & convert
        const fd = new FormData();
        fd.append('column', col);
        fd.append('smda_url', smdaUrl);
        fd.append('partition', partition);
        const r1 = await fetch('/api/strat/import/smda', {method:'POST', body:fd});
        const d1 = await r1.json();
        if (!r1.ok) throw new Error(d1.detail || r1.statusText);
        // 2. Ingest to OSDU Storage
        impStatus('smda-status', `[${i+1}/${cols.length}] Ingesting "${d1.columnName}" to OSDU…`, 'info');
        const r2 = await fetch('/api/strat/storage/put', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({bundle: d1.bundle, partition}),
        });
        const d2 = await r2.json();
        if (!r2.ok) throw new Error(d2.detail || r2.statusText);
        ok++;
      } catch(e) {
        fail++;
        errors.push(`${col}: ${e.message}`);
      }
    }
    _batchRunning = false;
    batchBtn.disabled = false;
    let msg = `Batch complete: ${ok} ingested`;
    if (fail) msg += `, ${fail} failed`;
    impStatus('smda-status', msg, fail ? 'err' : 'ok');
    if (errors.length) {
      const prev = document.getElementById('smda-preview');
      prev.innerHTML = `<strong>Errors:</strong><br>${errors.map(e => `&bull; ${e}`).join('<br>')}`;
    }
    setTimeout(() => doSearch(), 500);
  });

  /* ---- SMDA → RDDMS push ---- */
  const smdaRddmsDs       = document.getElementById('smda-rddms-ds');
  const smdaRddmsDsSel    = document.getElementById('smda-rddms-ds-sel');
  const smdaRddmsDsPicker = document.getElementById('smda-rddms-ds-picker');
  const btnSmdaRddmsList  = document.getElementById('btn-smda-rddms-list');
  const btnSmdaRddmsPush  = document.getElementById('btn-smda-rddms-push');
  const smdaRddmsStatus   = document.getElementById('smda-rddms-status');
  const smdaRddmsResult   = document.getElementById('smda-rddms-result');

  function smdaRddmsSetStatus(msg, cls) {
    if (smdaRddmsStatus) { smdaRddmsStatus.textContent = msg; smdaRddmsStatus.className = cls || 'muted'; }
  }
  function smdaRddmsShowResult(html, cls) {
    if (!smdaRddmsResult) return;
    smdaRddmsResult.innerHTML = html;
    smdaRddmsResult.style.display = 'block';
    smdaRddmsResult.style.background = cls === 'ok' ? '#e8f5e9' : cls === 'err' ? '#fce4ec' : '#e3f2fd';
    smdaRddmsResult.style.border = '1px solid ' + (cls === 'ok' ? '#4caf50' : cls === 'err' ? '#e53935' : '#1976d2');
  }

  // List dataspaces (reuses same endpoint)
  btnSmdaRddmsList?.addEventListener('click', async () => {
    smdaRddmsSetStatus('Loading dataspaces\u2026');
    try {
      const r = await fetch('/api/strat/dataspaces.json', { headers:{'Cache-Control':'no-store'} });
      const data = await r.json();
      if (data.error) throw new Error(data.error);
      const items = data.dataspaces || [];
      if (!items.length) { smdaRddmsSetStatus('No dataspaces found'); return; }
      smdaRddmsDsSel.innerHTML = '';
      for (const ds of items) {
        const opt = document.createElement('option');
        opt.value = ds.path; opt.textContent = ds.label;
        smdaRddmsDsSel.appendChild(opt);
      }
      smdaRddmsDsPicker.style.display = 'block';
      smdaRddmsSetStatus(`Found ${items.length} dataspaces`);
    } catch(e) {
      smdaRddmsSetStatus('List failed: ' + e.message, 'muted');
    }
  });

  smdaRddmsDsSel?.addEventListener('change', function() {
    if (smdaRddmsDs) smdaRddmsDs.value = this.value;
  });

  // Push SMDA column directly to RDDMS
  btnSmdaRddmsPush?.addEventListener('click', async () => {
    const col = document.getElementById('smda-col')?.value?.trim();
    if (!col) { smdaRddmsSetStatus('Fetch a column first'); return; }
    const ds = (smdaRddmsDs?.value || '').trim();
    if (!ds) { smdaRddmsSetStatus('Enter a dataspace path'); return; }
    const smdaUrl = document.getElementById('smda-url')?.value || '';
    const createDs = document.getElementById('smda-rddms-create-ds')?.checked || false;

    smdaRddmsSetStatus('Pushing to RDDMS\u2026');
    if (smdaRddmsResult) smdaRddmsResult.style.display = 'none';
    btnSmdaRddmsPush.disabled = true;

    try {
      const r = await fetch('/api/strat/smda/push-rddms', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          column: col,
          smdaUrl: smdaUrl,
          dataspace: ds,
          createDataspace: createDs,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || r.statusText);

      const types = data.types || {};
      const typeList = Object.entries(types).map(([k,v]) => {
        const short = k.replace('resqml20.obj_','');
        return `<tr><td style="font-family:monospace;font-size:12px;">${short}</td><td style="text-align:right;">${v}</td></tr>`;
      }).join('');

      const pushed = data.totalPushed ?? data.totalObjects;
      const failed = data.totalFailed ?? 0;
      const icon = data.status === 'ok' ? '\u2705' : (data.status === 'error' ? '\u274c' : '\u26a0\ufe0f');
      let html = `<strong>${icon} ${data.status.toUpperCase()}</strong> - `;
      html += `"${data.columnName}" \u2192 <code>${data.dataspace}</code><br>`;
      html += `<strong>${pushed}</strong> RESQML objects pushed`;
      if (failed > 0) html += `, <strong style="color:#c62828;">${failed} failed</strong>`;
      html += ` (${data.totalObjects} generated)`;
      if (typeList) {
        html += `<table style="margin-top:.4rem;border-collapse:collapse;"><thead><tr><th style="text-align:left;">Type</th><th style="text-align:right;">Count</th></tr></thead><tbody>${typeList}</tbody></table>`;
      }
      if (data.errors && data.errors.length) {
        const has404 = data.errors.some(e => e.httpStatus === 404);
        html += `<details style="margin-top:.4rem;" open><summary style="color:#c62828;">Errors (${data.errors.length})</summary>`;
        if (has404) html += `<p style="font-size:12px;color:#c62828;margin:.3rem 0;">The Reservoir DDMS v2 API does not support PUT for some RESQML types (404). These stratigraphic types may not be registered in this RDDMS deployment.</p>`;
        html += `<pre style="font-size:11px;max-height:150px;overflow:auto;">${JSON.stringify(data.errors, null, 2)}</pre></details>`;
      }
      smdaRddmsSetStatus(data.status === 'ok' ? 'Done' : (data.status === 'error' ? 'All pushes failed' : 'Completed with errors'));
      smdaRddmsShowResult(html, data.status === 'ok' ? 'ok' : 'err');
    } catch(e) {
      smdaRddmsSetStatus('Push failed: ' + e.message, 'muted');
      smdaRddmsShowResult(`<strong>\u274c Push failed</strong><br>${e.message}`, 'err');
    } finally {
      btnSmdaRddmsPush.disabled = false;
    }
  });

  /* ---- OSDU Bundle file tab ---- */
  let fileBundle = null;
  const btnBundleStorage = document.getElementById('btn-bundle-storage');

  document.getElementById('bundle-file')?.addEventListener('change', async function() {
    const file = this.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const doc = JSON.parse(text);
      fileBundle = doc;
      const recs = doc.records || [];
      impStatus('bundle-status', `Loaded ${recs.length} records from ${file.name}`, 'ok');
      impPreview('bundle-preview', doc);
    } catch(e) {
      fileBundle = null;
      impStatus('bundle-status', 'Invalid JSON: ' + e.message, 'err');
    }
  });
  btnBundleStorage?.addEventListener('click', () => {
    if (fileBundle) doIngest(fileBundle, document.getElementById('bundle-partition')?.value, 'bundle-status');
  });

  /* ================================================================ */
  /*  RDDMS PUSH (RESQML ingest to Reservoir DDMS dataspace)          */
  /* ================================================================ */

  const rddmsDs       = document.getElementById('rddms-ds');
  const rddmsDsSel    = document.getElementById('rddms-ds-sel');
  const rddmsDsPicker = document.getElementById('rddms-ds-picker');
  const btnRddmsListDs = document.getElementById('btn-rddms-list-ds');
  const btnRddmsPush  = document.getElementById('btn-rddms-push');
  const rddmsStatus   = document.getElementById('rddms-status');
  const rddmsResult   = document.getElementById('rddms-result');

  function rddmsSetStatus(msg, cls) {
    if (rddmsStatus) { rddmsStatus.textContent = msg; rddmsStatus.className = cls || 'muted'; }
  }
  function rddmsShowResult(html, cls) {
    if (!rddmsResult) return;
    rddmsResult.innerHTML = html;
    rddmsResult.style.display = 'block';
    rddmsResult.style.background = cls === 'ok' ? '#e8f5e9' : cls === 'err' ? '#fce4ec' : '#e3f2fd';
    rddmsResult.style.border = '1px solid ' + (cls === 'ok' ? '#4caf50' : cls === 'err' ? '#e53935' : '#1976d2');
  }

  // List dataspaces
  btnRddmsListDs?.addEventListener('click', async () => {
    rddmsSetStatus('Loading dataspaces\u2026');
    try {
      const r = await fetch('/api/strat/dataspaces.json', { headers:{'Cache-Control':'no-store'} });
      const data = await r.json();
      if (data.error) throw new Error(data.error);
      const items = data.dataspaces || [];
      if (!items.length) { rddmsSetStatus('No dataspaces found'); return; }
      rddmsDsSel.innerHTML = '';
      for (const ds of items) {
        const opt = document.createElement('option');
        opt.value = ds.path;
        opt.textContent = ds.label;
        rddmsDsSel.appendChild(opt);
      }
      rddmsDsPicker.style.display = 'block';
      rddmsSetStatus(`Found ${items.length} dataspaces`);
    } catch(e) {
      rddmsSetStatus('List failed: ' + e.message, 'muted');
    }
  });

  // Select dataspace from picker
  rddmsDsSel?.addEventListener('change', function() {
    if (rddmsDs) rddmsDs.value = this.value;
  });

  // Push to RDDMS
  btnRddmsPush?.addEventListener('click', async () => {
    if (!currentColumnId) { rddmsSetStatus('No column loaded'); return; }
    const ds = (rddmsDs?.value || '').trim();
    if (!ds) { rddmsSetStatus('Enter a dataspace path'); return; }
    const createDs = document.getElementById('rddms-create-ds')?.checked || false;

    rddmsSetStatus('Pushing to RDDMS\u2026');
    if (rddmsResult) rddmsResult.style.display = 'none';
    btnRddmsPush.disabled = true;

    try {
      const r = await fetch('/api/strat/ingest/rddms', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          columnId: currentColumnId,
          dataspace: ds,
          createDataspace: createDs,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || r.statusText);

      const types = data.types || {};
      const typeList = Object.entries(types).map(([k,v]) => {
        const short = k.replace('resqml20.obj_','');
        return `<tr><td style="font-family:monospace;font-size:12px;">${short}</td><td style="text-align:right;">${v}</td></tr>`;
      }).join('');

      const pushed = data.totalPushed ?? data.totalObjects;
      const failed = data.totalFailed ?? 0;
      const icon = data.status === 'ok' ? '\u2705' : (data.status === 'error' ? '\u274c' : '\u26a0\ufe0f');
      let html = `<strong>${icon} ${data.status.toUpperCase()}</strong> - `;
      html += `"${data.columnName}" \u2192 <code>${data.dataspace}</code><br>`;
      html += `<strong>${pushed}</strong> RESQML objects pushed`;
      if (failed > 0) html += `, <strong style="color:#c62828;">${failed} failed</strong>`;
      html += ` (${data.totalObjects} generated)`;
      if (typeList) {
        html += `<table style="margin-top:.4rem;border-collapse:collapse;"><thead><tr><th style="text-align:left;">Type</th><th style="text-align:right;">Count</th></tr></thead><tbody>${typeList}</tbody></table>`;
      }
      if (data.errors && data.errors.length) {
        const has404 = data.errors.some(e => e.httpStatus === 404);
        html += `<details style="margin-top:.4rem;" open><summary style="color:#c62828;">Errors (${data.errors.length})</summary>`;
        if (has404) html += `<p style="font-size:12px;color:#c62828;margin:.3rem 0;">The Reservoir DDMS v2 API does not support PUT for some RESQML types (404). These stratigraphic types may not be registered in this RDDMS deployment.</p>`;
        html += `<pre style="font-size:11px;max-height:150px;overflow:auto;">${JSON.stringify(data.errors, null, 2)}</pre></details>`;
      }

      rddmsSetStatus(data.status === 'ok' ? 'Done' : (data.status === 'error' ? 'All pushes failed' : 'Completed with errors'));
      rddmsShowResult(html, data.status === 'ok' ? 'ok' : 'err');
    } catch(e) {
      rddmsSetStatus('Push failed: ' + e.message, 'muted');
      rddmsShowResult(`<strong>\u274c Push failed</strong><br>${e.message}`, 'err');
    } finally {
      btnRddmsPush.disabled = false;
    }
  });

  /* ------------------------------------------------------------------ */
  /*  HORIZON GENERATION                                                */
  /* ------------------------------------------------------------------ */
  async function _doHorizonRequest(ingest) {
    if (!currentColumnId) return;
    const statusEl = document.getElementById('horizon-status');
    const resultEl = document.getElementById('horizon-result');
    const partition = window.__STRAT_PARTITION || 'data';

    if (statusEl) statusEl.textContent = ingest ? 'Generating & ingesting\u2026' : 'Generating preview\u2026';
    if (resultEl) resultEl.style.display = 'none';

    try {
      const r = await fetch('/api/strat/generate-horizons', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          columnId: currentColumnId,
          partition: partition,
          ingest: !!ingest,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || r.statusText);

      const s = data.stats || {};
      let html = `<strong>${s.horizonCount || 0} new horizon(s)</strong> from ${s.uniqueAges || 0} distinct ages, `;
      html += `${s.unitsPatchable || 0} units linkable`;
      if (s.existingHorizons) html += `<br><span class="muted">${s.existingHorizons} existing horizon(s) kept, ${s.skippedAges || 0} age(s) skipped (already linked)</span>`;
      if (s.horizonCount === 0 && s.existingHorizons > 0) html += `<br><em>All boundary ages already have horizons - nothing to generate.</em>`;

      if (ingest && data.ingest) {
        const ig = data.ingest;
        html += `<br><strong>Ingested:</strong> ${ig.created || 0} records to OSDU Storage`;
        if (ig.errors && ig.errors.length) {
          html += ` <span style="color:#c62828;">(${ig.errors.length} errors)</span>`;
        }
      }

      // Show a few sample horizons
      if (data.horizons && data.horizons.length) {
        const samples = data.horizons.slice(0, 5);
        html += '<details style="margin-top:.4rem;"><summary>Sample horizons</summary><ul style="font-size:12px;margin:.3rem 0;">';
        for (const h of samples) {
          const hd = h.data || {};
          html += `<li><strong>${hd.Name}</strong> - ${hd.MeanPossibleAge} Ma</li>`;
        }
        if (data.horizons.length > 5) html += `<li>\u2026 and ${data.horizons.length - 5} more</li>`;
        html += '</ul></details>';
      }

      if (resultEl) {
        resultEl.innerHTML = html;
        resultEl.style.display = 'block';
        resultEl.style.background = '#e8f5e9';
        resultEl.style.border = '1px solid #4caf50';
      }
      if (statusEl) statusEl.textContent = ingest ? 'Done - horizons ingested' : 'Preview ready';

      // Auto-refresh column to show horizon data
      if (ingest) setTimeout(() => loadColumnById(currentColumnId), 2000);
    } catch(e) {
      if (statusEl) statusEl.textContent = 'Failed: ' + e.message;
      if (resultEl) {
        resultEl.innerHTML = `<strong>\u274c Error</strong>: ${e.message}`;
        resultEl.style.display = 'block';
        resultEl.style.background = '#fce4ec';
        resultEl.style.border = '1px solid #e53935';
      }
    }
  }

  document.getElementById('btn-horizon-preview')?.addEventListener('click', () => _doHorizonRequest(false));
  document.getElementById('btn-horizon-ingest')?.addEventListener('click', () => _doHorizonRequest(true));

  /* ------------------------------------------------------------------ */
  /*  UNIT GENERATION (inverse: horizons → units)                       */
  /* ------------------------------------------------------------------ */
  async function _doUnitGenRequest(ingest) {
    if (!currentColumnId) return;
    const statusEl = document.getElementById('unitgen-status');
    const resultEl = document.getElementById('unitgen-result');
    const partition = window.__STRAT_PARTITION || 'data';

    if (statusEl) statusEl.textContent = ingest ? 'Generating & ingesting\u2026' : 'Generating preview\u2026';
    if (resultEl) resultEl.style.display = 'none';

    try {
      const r = await fetch('/api/strat/generate-units', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          columnId: currentColumnId,
          partition: partition,
          ingest: !!ingest,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || r.statusText);

      const s = data.stats || {};
      let html = `<strong>${s.unitCount || 0} new unit(s)</strong> derived from ${s.horizonCount || 0} horizon boundaries`;
      if (s.existingUnits) html += `<br><span class="muted">${s.existingUnits} existing unit(s) kept, ${s.skippedIntervals || 0} interval(s) skipped (already covered)</span>`;
      if (s.unitCount === 0 && s.existingUnits > 0) html += `<br><em>All intervals already have units - nothing to generate.</em>`;

      if (ingest && data.ingest) {
        const ig = data.ingest;
        html += `<br><strong>Ingested:</strong> ${ig.created || 0} records to OSDU Storage`;
        if (ig.errors && ig.errors.length) {
          html += ` <span style="color:#c62828;">(${ig.errors.length} errors)</span>`;
        }
      }

      // Show a few sample units
      if (data.units && data.units.length) {
        const samples = data.units.slice(0, 5);
        html += '<details style="margin-top:.4rem;"><summary>Sample units</summary><ul style="font-size:12px;margin:.3rem 0;">';
        for (const u of samples) {
          const ud = u.data || {};
          html += `<li><strong>${ud.Name}</strong> - ${ud.OlderPossibleAge}\u2013${ud.YoungerPossibleAge} Ma</li>`;
        }
        if (data.units.length > 5) html += `<li>\u2026 and ${data.units.length - 5} more</li>`;
        html += '</ul></details>';
      }

      if (resultEl) {
        resultEl.innerHTML = html;
        resultEl.style.display = 'block';
        resultEl.style.background = '#e3f2fd';
        resultEl.style.border = '1px solid #1976d2';
      }
      if (statusEl) statusEl.textContent = ingest ? 'Done - units ingested' : 'Preview ready';

      // Auto-refresh column after ingest
      if (ingest) setTimeout(() => loadColumnById(currentColumnId), 2000);
    } catch(e) {
      if (statusEl) statusEl.textContent = 'Failed: ' + e.message;
      if (resultEl) {
        resultEl.innerHTML = `<strong>\u274c Error</strong>: ${e.message}`;
        resultEl.style.display = 'block';
        resultEl.style.background = '#fce4ec';
        resultEl.style.border = '1px solid #e53935';
      }
    }
  }

  document.getElementById('btn-unitgen-preview')?.addEventListener('click', () => _doUnitGenRequest(false));
  document.getElementById('btn-unitgen-ingest')?.addEventListener('click', () => _doUnitGenRequest(true));

})();
