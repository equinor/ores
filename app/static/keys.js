    const $ = (id) => document.getElementById(id);
    const dsSel = $('ds'), typSel = $('typ'), objSel = $('obj');
    const dsF1 = $('ds-f1'), dsF2 = $('ds-f2'), dsCountEl = $('ds-count');
    const msg = $('msg'), summaryEl = $('summary'), metaEl = $('meta'),
          edgesEl = $('edges'), arraysEl = $('arrays'),
          metadataSection = $('metadata-section'), metadataPairs = $('metadata-pairs'),
          extrametaSection = $('extrameta-section'), extrametaEl = $('extrameta'),
          aliasesSection = $('aliases-section'), aliasesEl = $('aliases'),
          grid2dSection = $('grid2d-section'), grid2dControls = $('grid2d-controls'),
          grid2dView = $('grid2d-view'), grid2dStatus = $('grid2d-status'),
          grid2dBadge = $('grid2d-badge'),
          btnTable = $('btn-table'), btnMap = $('btn-map'), btn3d = $('btn-3d');

    // All dataspace items (cached for filtering)
    let _allDsItems = [];

    // Escape HTML to prevent XSS
    function esc(s) {
      const d = document.createElement('div');
      d.textContent = s || '';
      return d.innerHTML;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // EASY MODE: Visual Query Builder + Colored Result Cards
    // ═══════════════════════════════════════════════════════════════════════════

    // Category → color mapping for badges
    const TYPE_COLORS = {
      Grid: { bg: '#e8f5e9', fg: '#2e7d32', border: '#a5d6a7' },
      Surface: { bg: '#e3f2fd', fg: '#1565c0', border: '#90caf9' },
      Well: { bg: '#fff3e0', fg: '#e65100', border: '#ffcc80' },
      Property: { bg: '#f3e5f5', fg: '#6a1b9a', border: '#ce93d8' },
      Stratigraphy: { bg: '#fce4ec', fg: '#880e4f', border: '#f48fb1' },
      Organization: { bg: '#e0f2f1', fg: '#004d40', border: '#80cbc4' },
      CRS: { bg: '#eceff1', fg: '#37474f', border: '#b0bec5' },
      Provenance: { bg: '#fff8e1', fg: '#f57f17', border: '#ffe082' },
    };
    const DEFAULT_COLOR = { bg: '#f5f5f5', fg: '#424242', border: '#e0e0e0' };

    // Reference data (loaded from /api/graphql/reference)
    let _refData = { propertyKinds: [], resqmlTypes: [], operators: [], aliasMap: {} };

    async function loadReferenceData() {
      try {
        const r = await fetch('/api/graphql/reference');
        _refData = await r.json();
        populateEasyForm();
      } catch (e) {
        console.warn('Failed to load reference data:', e);
      }
    }

    function populateEasyForm() {
      // Populate type dropdown
      const ezType = $('ez-type');
      ezType.innerHTML = '';
      const categories = [...new Set(_refData.resqmlTypes.map(t => t.category))];
      categories.forEach(cat => {
        const og = document.createElement('optgroup');
        og.label = cat;
        _refData.resqmlTypes.filter(t => t.category === cat).forEach(t => {
          const o = document.createElement('option');
          o.value = t.name;
          o.textContent = `${t.short} - ${t.description}`;
          o.dataset.category = cat;
          og.appendChild(o);
        });
        ezType.appendChild(og);
      });
      // Default to IjkGrid
      ezType.value = 'resqml20.obj_IjkGridRepresentation';
      updateTypeBadge();

      // Populate operator dropdown
      const ezOp = $('ez-op');
      ezOp.innerHTML = '<option value="">-</option>';
      _refData.operators.forEach(op => {
        const o = document.createElement('option');
        o.value = op.value;
        o.textContent = op.symbol;
        o.title = op.label;
        ezOp.appendChild(o);
      });

      // Show/hide range inputs when BETWEEN is selected
      ezOp.addEventListener('change', () => {
        const isBetween = ezOp.value === 'BETWEEN';
        $('ez-threshold-high').style.display = isBetween ? '' : 'none';
        $('ez-range-sep').style.display = isBetween ? '' : 'none';
        $('ez-filter-hint').textContent = isBetween ? '(e.g. 0.15 to 0.30)' : '(e.g. 0.25, 500)';
        $('ez-threshold').placeholder = isBetween ? 'low' : 'threshold value';
      });

      // Populate property picker dropdown
      const propPick = $('ez-prop-pick');
      propPick.innerHTML = '<option value="">(pick or type below)</option>';
      _refData.propertyKinds.forEach(pk => {
        const o = document.createElement('option');
        o.value = pk.aliases[0] || pk.name;
        o.textContent = `${pk.name} [${pk.uom}]`;
        o.title = pk.description + ' - aliases: ' + pk.aliases.join(', ');
        propPick.appendChild(o);
      });
      propPick.addEventListener('change', () => {
        if (propPick.value) {
          $('ez-prop').value = propPick.value;
          resolvePropertyAlias();
        }
      });
    }

    function updateTypeBadge() {
      const sel = $('ez-type');
      const opt = sel.selectedOptions[0];
      const cat = opt ? opt.dataset.category : '';
      const badge = $('ez-type-cat');
      const colors = TYPE_COLORS[cat] || DEFAULT_COLOR;
      badge.textContent = cat;
      badge.style.background = colors.bg;
      badge.style.color = colors.fg;
      badge.style.border = `1px solid ${colors.border}`;
    }

    function resolvePropertyAlias() {
      const term = $('ez-prop').value.trim().toLowerCase();
      const resolved = $('ez-prop-resolved');
      if (!term) { resolved.textContent = ''; return; }
      const canonical = _refData.aliasMap[term];
      if (canonical) {
        const pk = _refData.propertyKinds.find(p => p.name === canonical);
        resolved.textContent = `→ ${canonical}` + (pk ? ` (${pk.uom})` : '');
        resolved.style.color = '#107c10';
      } else {
        // Fuzzy search
        const matches = _refData.propertyKinds.filter(pk =>
          pk.name.includes(term) || pk.aliases.some(a => a.includes(term))
        );
        if (matches.length === 1) {
          resolved.textContent = `→ ${matches[0].name} (${matches[0].uom})`;
          resolved.style.color = '#107c10';
        } else if (matches.length > 1) {
          resolved.textContent = `? ${matches.length} matches`;
          resolved.style.color = '#795548';
        } else {
          resolved.textContent = '(custom term)';
          resolved.style.color = '#605e5c';
        }
      }
    }

    function buildEasyQuery() {
      const action = $('ez-action').value;
      const typeName = $('ez-type').value;
      const prop = $('ez-prop').value.trim();
      const op = $('ez-op').value;
      const threshold = $('ez-threshold').value;
      const thresholdHigh = $('ez-threshold-high').value;
      const stats = $('ez-stats').checked;
      const relations = $('ez-relations').checked;
      const sample = $('ez-sample').checked;
      const limit = parseInt($('ez-limit').value) || 5;
      const matchMode = $('ez-match-mode').value;

      // Get dataspaces
      const dsList = Array.from(dsSel.selectedOptions).map(o => o.value);
      const dsArg = dsList.length > 0 ? `dataspaces: ${JSON.stringify(dsList)}` : `dataspace: "maap/drogon"`;
      const singleDs = dsList.length > 0 ? dsList[0] : 'maap/drogon';

      if (action === 'deep_search') {
        let propFilter = '';
        if (prop) {
          const filterField = matchMode === 'strict' ? 'kind' : 'titleContains';
          propFilter = `propertyFilter: { ${filterField}: "${prop}"`;
          if (op && threshold) {
            let af = `threshold: ${parseFloat(threshold)}, operator: ${op}`;
            if (op === 'BETWEEN' && thresholdHigh) {
              af += `, thresholdHigh: ${parseFloat(thresholdHigh)}`;
            }
            propFilter += `, arrayFilter: { ${af} }`;
          }
          propFilter += ' }';
        }
        return `{
  deepSearch(
    ${dsArg}
    typeName: "${typeName}"
    ${propFilter ? propFilter : ''}
    includeStatistics: ${stats}
    includeSampleValues: ${sample}
    limit: ${limit}
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title typeName
      properties {
        title kind uom
        ${stats ? 'statistics { count minValue maxValue mean stdDev }' : ''}
        ${(op && threshold) ? 'matchingCells { count total fraction }' : ''}
        ${sample ? 'sampleValues' : ''}
      }
    }
  }
}`;
      } else if (action === 'browse') {
        return `{
  resqmlObjects(
    dataspace: "${singleDs}"
    typeName: "${typeName}"
    limit: ${limit}
  ) {
    uuid title typeName
  }
}`;
      } else if (action === 'relations') {
        return `# Select an object UUID from the browse results above, then paste it below
{
  objectRelations(
    dataspace: "${singleDs}"
    typeName: "${typeName}"
    uuid: "PASTE-UUID-HERE"
    direction: "both"
  ) {
    uuid name typeName direction contentType
  }
}`;
      } else if (action === 'federated') {
        return `{
  federatedSearch(
    text: "${prop || '*'}"
    ${dsArg}
    typeName: "${typeName}"
    searchCatalog: true
    searchRddms: true
    searchRemoteRddms: true
    includeRelations: ${relations}
    includeProperties: ${stats}
    includeStatistics: ${stats}
    limit: ${limit}
  ) {
    totalCatalog totalLocalRddms totalRemoteRddms totalMerged sources
    hits {
      uuid title typeName dataspace
      foundInCatalog foundInLocalRddms foundInRemoteRddms
      ${relations ? 'relations { uuid name typeName direction }' : ''}
      ${stats ? 'properties { title kind statistics { count minValue maxValue mean } }' : ''}
    }
  }
}`;
      } else if (action === 'cross_system') {
        // Cross-system: find objects in both systems, show presence flags + full lineage
        let propFilter = '';
        if (prop && op && threshold) {
          const filterField = matchMode === 'strict' ? 'kind' : 'titleContains';
          let af = `threshold: ${parseFloat(threshold)}, operator: ${op}`;
          if (op === 'BETWEEN' && thresholdHigh) af += `, thresholdHigh: ${parseFloat(thresholdHigh)}`;
          propFilter = `propertyFilter: { ${filterField}: "${prop}", arrayFilter: { ${af} } }`;
        } else if (prop) {
          const filterField = matchMode === 'strict' ? 'kind' : 'titleContains';
          propFilter = `propertyFilter: { ${filterField}: "${prop}" }`;
        }
        return `# Cross-system query: catalog ↔ RDDMS comparison + full lineage
# Objects appear with flags showing WHERE they exist.
# foundInCatalog=false → RDDMS orphan (not indexed)
# foundInLocalRddms=false → catalog ghost (no backing data)
{
  federatedSearch(
    text: "*"
    ${dsArg}
    typeName: "${typeName}"
    searchCatalog: true
    searchRddms: true
    searchRemoteRddms: true
    includeRelations: true
    includeProperties: true
    includeStatistics: true
    ${propFilter}
    limit: ${limit}
  ) {
    totalCatalog totalLocalRddms totalRemoteRddms totalMerged
    sources queryDescription
    hits {
      uuid title typeName dataspace
      foundInCatalog foundInLocalRddms foundInRemoteRddms
      osduId osduKind
      relations { uuid name typeName direction }
      properties {
        title kind uom
        statistics { count minValue maxValue mean stdDev }
        ${(op && threshold) ? 'matchingCells { count total fraction }' : ''}
      }
    }
  }
}`;
      }
      return '{ status }';
    }

    // ── Colored Result Cards ─────────────────────────────────────────────────

    function renderResultCards(data) {
      const container = $('ez-results');
      if (!data || !data.data) {
        container.innerHTML = '<p class="muted">No results</p>';
        return;
      }

      const d = data.data;
      let html = '';

      // Deep search results
      if (d.deepSearch) {
        const ds = d.deepSearch;
        html += `<div style="margin-bottom:8px;padding:8px 12px;background:#e8f5e9;border-radius:4px;border-left:4px solid #4caf50;font-size:13px;">
          <strong>${ds.totalMatched}</strong> matched / <strong>${ds.totalScanned}</strong> scanned
          &nbsp;|&nbsp; <span style="color:#605e5c;">${esc(ds.queryDescription)}</span>
          &nbsp;|&nbsp; <span class="tag">${esc(ds.backend)}</span>
        </div>`;
        (ds.objects || []).forEach(obj => {
          html += renderObjectCard(obj);
        });
      }

      // Federated results
      if (d.federatedSearch) {
        const fs = d.federatedSearch;
        html += `<div style="margin-bottom:8px;padding:8px 12px;background:#e3f2fd;border-radius:4px;border-left:4px solid #1976d2;font-size:13px;">
          <strong>${fs.totalMerged}</strong> merged results
          &nbsp;|&nbsp; Catalog: ${fs.totalCatalog || 0} &nbsp; Local: ${fs.totalLocalRddms || 0} &nbsp; Remote: ${fs.totalRemoteRddms || 0}
          &nbsp;|&nbsp; Sources: ${(fs.sources || []).map(s => `<span class="tag">${esc(s)}</span>`).join(' ')}
        </div>`;
        (fs.hits || []).forEach(hit => {
          html += renderFederatedCard(hit);
        });
      }

      // Browse results
      if (d.resqmlObjects) {
        html += `<div style="margin-bottom:8px;padding:8px 12px;background:#f3e5f5;border-radius:4px;border-left:4px solid #9c27b0;font-size:13px;">
          <strong>${d.resqmlObjects.length}</strong> objects found
        </div>`;
        d.resqmlObjects.forEach(obj => {
          const tShort = (obj.typeName || '').replace(/^resqml\d+\.obj_/, '');
          const cat = (_refData.resqmlTypes.find(t => t.name === obj.typeName) || {}).category || '';
          const colors = TYPE_COLORS[cat] || DEFAULT_COLOR;
          html += `<div style="margin-bottom:6px;padding:8px 12px;background:${colors.bg};border:1px solid ${colors.border};border-radius:4px;display:flex;align-items:center;gap:10px;">
            <span style="font-size:11px;font-family:monospace;color:#605e5c;user-select:all;flex-shrink:0;">${esc(obj.uuid)}</span>
            <strong style="color:${colors.fg};">${esc(obj.title)}</strong>
            <span class="tag" style="background:${colors.bg};color:${colors.fg};border:1px solid ${colors.border};">${tShort}</span>
          </div>`;
        });
      }

      // Relation results
      if (d.objectRelations) {
        const rels = d.objectRelations;
        const targets = rels.filter(r => r.direction === 'target');
        const sources = rels.filter(r => r.direction === 'source');
        html += `<div style="margin-bottom:8px;padding:8px 12px;background:#fff3e0;border-radius:4px;border-left:4px solid #ff9800;font-size:13px;">
          <strong>${rels.length}</strong> relations (${targets.length} targets, ${sources.length} sources)
        </div>`;
        rels.forEach(rel => {
          const tShort = (rel.typeName || '').replace(/^resqml\d+\.obj_/, '');
          const dirColor = rel.direction === 'target' ? '#1565c0' : '#2e7d32';
          const dirIcon = rel.direction === 'target' ? '→' : '←';
          html += `<div style="margin-bottom:4px;padding:6px 10px;background:#fff;border:1px solid #e1dfdd;border-radius:4px;display:flex;align-items:center;gap:8px;font-size:12px;">
            <span style="color:${dirColor};font-weight:bold;font-size:14px;">${dirIcon}</span>
            <span style="font-family:monospace;font-size:10px;color:#999;flex-shrink:0;">${esc(rel.uuid).substring(0, 8)}…</span>
            <strong>${esc(rel.name)}</strong>
            <span class="tag">${tShort}</span>
            <span style="color:#605e5c;font-size:11px;">${esc(rel.contentType || '')}</span>
          </div>`;
        });
      }

      container.innerHTML = html || '<p class="muted">Query returned no renderable results. Check JSON tab for raw output.</p>';

      // Check for 3D-renderable objects and show "Show 3D Results" button
      const renderableObjs = extractRenderableObjects(data);
      if (renderableObjs.length > 0) {
        insertShow3DButton(container, renderableObjs);
      }
    }

    function renderObjectCard(obj) {
      const tShort = (obj.typeName || '').replace(/^resqml\d+\.obj_/, '');
      const cat = (_refData.resqmlTypes.find(t => t.name === obj.typeName) || {}).category || 'Grid';
      const colors = TYPE_COLORS[cat] || DEFAULT_COLOR;

      let html = `<div style="margin-bottom:10px;border:1px solid ${colors.border};border-radius:6px;overflow:hidden;">
        <div style="padding:8px 12px;background:${colors.bg};display:flex;align-items:center;gap:10px;border-bottom:1px solid ${colors.border};">
          <span style="font-size:11px;font-family:monospace;color:#605e5c;user-select:all;">${esc(obj.uuid)}</span>
          <strong style="color:${colors.fg};font-size:14px;">${esc(obj.title)}</strong>
          <span class="tag" style="background:${colors.bg};color:${colors.fg};border:1px solid ${colors.border};">${tShort}</span>
        </div>`;

      if (obj.properties && obj.properties.length) {
        html += '<div style="padding:8px 12px;">';
        obj.properties.forEach(p => {
          html += renderPropertyCard(p);
        });
        html += '</div>';
      }
      html += '</div>';
      return html;
    }

    function renderPropertyCard(p) {
      const stats = p.statistics;
      const match = p.matchingCells;
      let html = `<div style="margin-bottom:6px;padding:6px 10px;background:#fafafa;border:1px solid #e8e8e8;border-radius:4px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
          <strong style="color:#37474f;">${esc(p.title)}</strong>
          ${p.kind ? `<span style="font-size:11px;color:#795548;background:#efebe9;padding:1px 5px;border-radius:3px;">${esc(p.kind)}</span>` : ''}
          ${p.uom ? `<span style="font-size:11px;color:#605e5c;">[${esc(p.uom)}]</span>` : ''}
        </div>`;

      if (stats) {
        const range = (stats.maxValue != null && stats.minValue != null) ? stats.maxValue - stats.minValue : 0;
        const meanPct = range > 0 ? ((stats.mean - stats.minValue) / range * 100) : 50;
        html += `<div style="display:flex;align-items:center;gap:12px;font-size:12px;color:#424242;">
          <span>min: <b>${fmtNum(stats.minValue)}</b></span>
          <div style="flex:1;height:6px;background:#e0e0e0;border-radius:3px;position:relative;min-width:80px;">
            <div style="position:absolute;left:${meanPct.toFixed(1)}%;top:-2px;width:2px;height:10px;background:#1976d2;border-radius:1px;" title="mean=${fmtNum(stats.mean)}"></div>
          </div>
          <span>max: <b>${fmtNum(stats.maxValue)}</b></span>
          <span style="color:#1976d2;">μ=${fmtNum(stats.mean)}</span>
          ${stats.stdDev != null ? `<span style="color:#7b1fa2;">σ=${fmtNum(stats.stdDev)}</span>` : ''}
          <span style="color:#605e5c;">(n=${stats.count?.toLocaleString() || '?'})</span>
        </div>`;
      }

      if (match) {
        const pct = (match.fraction * 100).toFixed(1);
        const barColor = match.fraction > 0.5 ? '#4caf50' : match.fraction > 0.2 ? '#ff9800' : '#f44336';
        html += `<div style="margin-top:4px;display:flex;align-items:center;gap:8px;font-size:11px;">
          <span style="color:#605e5c;">Matching cells:</span>
          <div style="flex:1;max-width:120px;height:5px;background:#e0e0e0;border-radius:3px;overflow:hidden;">
            <div style="width:${pct}%;height:100%;background:${barColor};border-radius:3px;"></div>
          </div>
          <span><b>${match.count?.toLocaleString()}</b> / ${match.total?.toLocaleString()} (${pct}%)</span>
        </div>`;
      }

      html += '</div>';
      return html;
    }

    function renderFederatedCard(hit) {
      const tShort = (hit.typeName || '').replace(/^resqml\d+\.obj_/, '');
      const cat = (_refData.resqmlTypes.find(t => t.name === hit.typeName) || {}).category || '';
      const colors = TYPE_COLORS[cat] || DEFAULT_COLOR;

      let sourceFlags = '';
      if (hit.foundInCatalog) sourceFlags += '<span style="background:#e3f2fd;color:#1565c0;padding:1px 5px;border-radius:3px;font-size:10px;margin-right:3px;">Catalog</span>';
      if (hit.foundInLocalRddms) sourceFlags += '<span style="background:#e8f5e9;color:#2e7d32;padding:1px 5px;border-radius:3px;font-size:10px;margin-right:3px;">Local PG</span>';
      if (hit.foundInRemoteRddms) sourceFlags += '<span style="background:#fff3e0;color:#e65100;padding:1px 5px;border-radius:3px;font-size:10px;margin-right:3px;">Remote</span>';

      let html = `<div style="margin-bottom:6px;padding:8px 12px;background:${colors.bg};border:1px solid ${colors.border};border-radius:4px;">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <strong style="color:${colors.fg};">${esc(hit.title)}</strong>
          <span class="tag" style="background:${colors.bg};color:${colors.fg};border:1px solid ${colors.border};">${tShort}</span>
          ${sourceFlags}
          ${hit.dataspace ? `<span style="font-size:11px;color:#605e5c;">ds: ${esc(hit.dataspace)}</span>` : ''}
          <span style="font-size:10px;font-family:monospace;color:#999;user-select:all;">${esc(hit.uuid)}</span>
        </div>`;

      if (hit.properties && hit.properties.length) {
        html += '<div style="margin-top:6px;padding-left:8px;">';
        hit.properties.forEach(p => { html += renderPropertyCard(p); });
        html += '</div>';
      }
      if (hit.relations && hit.relations.length) {
        html += `<div style="margin-top:4px;font-size:11px;color:#605e5c;padding-left:8px;">
          ${hit.relations.length} relations: ${hit.relations.slice(0, 3).map(r => esc(r.name)).join(', ')}${hit.relations.length > 3 ? '…' : ''}
        </div>`;
      }
      html += '</div>';
      return html;
    }

    function fmtNum(v) {
      if (v == null) return '?';
      if (Math.abs(v) >= 1000) return v.toFixed(1);
      if (Math.abs(v) >= 1) return v.toFixed(3);
      if (Math.abs(v) >= 0.001) return v.toFixed(4);
      return v.toExponential(2);
    }

    // ── Mode switching ────────────────────────────────────────────────────────

    $('mode-easy').addEventListener('click', () => {
      $('easy-panel').style.display = '';
      $('advanced-panel').style.display = 'none';
      $('mode-easy').style.background = 'transparent'; $('mode-easy').style.color = 'var(--eq-red, #FF1243)'; $('mode-easy').style.fontWeight = '600'; $('mode-easy').style.borderBottom = '2px solid var(--eq-red, #FF1243)';
      $('mode-advanced').style.background = 'transparent'; $('mode-advanced').style.color = '#605e5c'; $('mode-advanced').style.fontWeight = '500'; $('mode-advanced').style.borderBottom = '2px solid transparent';
    });
    $('mode-advanced').addEventListener('click', () => {
      $('easy-panel').style.display = 'none';
      $('advanced-panel').style.display = '';
      $('mode-advanced').style.background = 'transparent'; $('mode-advanced').style.color = 'var(--eq-red, #FF1243)'; $('mode-advanced').style.fontWeight = '600'; $('mode-advanced').style.borderBottom = '2px solid var(--eq-red, #FF1243)';
      $('mode-easy').style.background = 'transparent'; $('mode-easy').style.color = '#605e5c'; $('mode-easy').style.fontWeight = '500'; $('mode-easy').style.borderBottom = '2px solid transparent';
    });

    // ── Easy Mode event handlers ──────────────────────────────────────────────

    $('ez-type').addEventListener('change', updateTypeBadge);
    $('ez-prop').addEventListener('input', resolvePropertyAlias);

    $('ez-show-gql').addEventListener('click', () => {
      const q = buildEasyQuery();
      $('gql-editor').value = q;
      $('mode-advanced').click();
      autoSizeEditor();
    });

    $('ez-run').addEventListener('click', async () => {
      const query = buildEasyQuery();
      $('ez-status').textContent = 'Running…';
      $('ez-results').innerHTML = '';
      try {
        const resp = await fetch('/api/graphql/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query }),
        });
        const data = await resp.json();
        if (data.errors && data.errors.length) {
          $('ez-status').textContent = `Error: ${data.errors[0].message}`;
          $('ez-results').innerHTML = `<pre style="color:#a80000;font-size:12px;padding:8px;background:#fde7e9;border-radius:4px;">${esc(JSON.stringify(data.errors, null, 2))}</pre>`;
        } else {
          const count = countResults(data);
          $('ez-status').textContent = `Done – ${count} result(s)`;
          renderResultCards(data);
        }
        // Also populate the advanced view
        $('gql-output').textContent = JSON.stringify(data, null, 2);
        $('gql-editor').value = query;
        renderMermaidFromResponse(data);
      } catch (e) {
        $('ez-status').textContent = 'Request failed: ' + e.message;
      }
    });

    function countResults(data) {
      if (!data || !data.data) return 0;
      const d = data.data;
      if (d.deepSearch) return (d.deepSearch.objects || []).length;
      if (d.federatedSearch) return (d.federatedSearch.hits || []).length;
      if (d.resqmlObjects) return d.resqmlObjects.length;
      if (d.objectRelations) return d.objectRelations.length;
      return Object.keys(d).length;
    }

    // Show/hide filter row and prop row based on action
    $('ez-action').addEventListener('change', () => {
      const action = $('ez-action').value;
      $('ez-prop-row').style.display = (action === 'browse') ? 'none' : '';
      $('ez-filter-row').style.display = (action === 'deep_search') ? '' : 'none';
    });

    // Load reference data on init
    loadReferenceData();

    // ═══════════════════════════════════════════════════════════════════════════

    function setMsg(text) {
      msg.textContent = text || '';
      msg.style.display = text ? 'block' : 'none';
    }

    function clearDetails() {
      summaryEl.innerHTML = '';
      metaEl.textContent = '';
      edgesEl.innerHTML = '';
      arraysEl.innerHTML = '';
      metadataSection.style.display = 'none';
      metadataPairs.innerHTML = '';
      extrametaSection.style.display = 'none';
      extrametaEl.innerHTML = '';
      aliasesSection.style.display = 'none';
      aliasesEl.innerHTML = '';
      grid2dSection.style.display = 'none';
      grid2dView.innerHTML = '';
      grid2dStatus.textContent = '';
      btn3d.style.display = 'none';
      btnTable.style.display = 'none';
      btnMap.style.display = 'none';
      dispose3D();
    }

    function populateDataspaces(items) {
      _allDsItems = (items || []).filter(x => x && x.path);
      _applyDsFilter();
    }

    function _applyDsFilter() {
      const q1 = (dsF1.value || '').trim().toLowerCase();
      const q2 = (dsF2.value || '').trim().toLowerCase();
      const prev = dsSel.value;
      dsSel.innerHTML = '';
      let matched = 0;
      _allDsItems.forEach(x => {
        const path = x.path.toLowerCase();
        const parts = path.split('/');
        const seg1 = parts[0] || '';
        const seg2 = parts.slice(1).join('/');
        if (q1 && !seg1.includes(q1)) return;
        if (q2 && !seg2.includes(q2)) return;
        const o = document.createElement('option');
        o.value = x.path;
        const src = x.source || '';
        if (src === 'local') {
          o.textContent = '\u25cf ' + x.path;
          o.style.color = '#107c10';
          o.title = 'Local RDDMS (PostgreSQL)';
        } else if (src === 'remote') {
          o.textContent = '\u25cb ' + x.path;
          o.style.color = '#004578';
          o.title = 'Remote OSDU RDDMS';
        } else {
          o.textContent = x.path;
        }
        dsSel.appendChild(o);
        matched++;
      });
      // Restore previous selection if still present
      if (prev) { for (const o of dsSel.options) { if (o.value === prev) { dsSel.value = prev; break; } } }
      dsCountEl.textContent = (q1 || q2) ? `${matched}/${_allDsItems.length}` : `${_allDsItems.length}`;
    }

    dsF1.addEventListener('input', _applyDsFilter);
    dsF2.addEventListener('input', _applyDsFilter);

    // Render key-value pairs as a table
    function renderPairsTable(pairs) {
      if (!pairs || !pairs.length) return '<p class="muted">No metadata.</p>';
      return `<table class="meta-table"><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody>${
        pairs.map(p => `<tr><td>${esc(p.name)}</td><td><code>${esc(String(p.value))}</code></td></tr>`).join('')
      }</tbody></table>`;
    }

    // Detect if the current type is a Grid2dRepresentation
    function isGrid2dType(typ) {
      const t = (typ || '').toLowerCase();
      return t.includes('grid2drepresentation') || t.includes('grid2d');
    }

    // Detect if a type supports 3D viewing
    const _3D_TYPE_KEYS = ['grid2drepresentation', 'triangulatedsetrepresentation',
      'pointsetrepresentation', 'wellboretrajectoryrepresentation',
      'wellboremarkerframerepresentation', 'polylinesetrepresentation',
      'deviationsurveyrepresentation'];
    function is3dType(typ) {
      const t = (typ || '').toLowerCase();
      return _3D_TYPE_KEYS.some(k => t.includes(k));
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 3D Results Popup – show all renderable GraphQL results in a Three.js viewer
    // ═══════════════════════════════════════════════════════════════════════════

    let _gql3dViewer = null;      // { renderer, scene, camera, animId }
    let _gql3dObjects = {};       // uuid → { mesh, geo, color, title, kind }
    let _gql3dAutoRotate = true;
    let _gql3dRotX = 0.55, _gql3dRotY = -0.6, _gql3dZoomDist = 3, _gql3dPanX = 0, _gql3dPanY = 0;
    let _gql3dTarget = null;
    let _gql3dGlobalMin = { x: Infinity, y: Infinity, z: Infinity };
    let _gql3dGlobalMax = { x: -Infinity, y: -Infinity, z: -Infinity };

    const _GQL3D_PALETTE = [
      '#4caf50', '#2196f3', '#ff9800', '#e91e63', '#9c27b0',
      '#00bcd4', '#ff5722', '#8bc34a', '#3f51b5', '#ffc107',
      '#795548', '#607d8b', '#cddc39', '#f44336', '#009688',
    ];

    function _gql3dColorZ(z, zmin, zmax) {
      const t = zmax > zmin ? Math.max(0, Math.min(1, (z - zmin) / (zmax - zmin))) : 0.5;
      let r, g, b;
      if (t < 0.25) { const s = t/0.25; r = 0.28*(1-s)+0.13*s; g = 0.0*(1-s)+0.57*s; b = 0.33*(1-s)+0.55*s; }
      else if (t < 0.5) { const s = (t-0.25)/0.25; r = 0.13*(1-s)+0.15*s; g = 0.57*(1-s)+0.73*s; b = 0.55*(1-s)+0.34*s; }
      else if (t < 0.75) { const s = (t-0.5)/0.25; r = 0.15*(1-s)+0.63*s; g = 0.73*(1-s)+0.85*s; b = 0.34*(1-s)+0.17*s; }
      else { const s = (t-0.75)/0.25; r = 0.63*(1-s)+0.99*s; g = 0.85*(1-s)+0.91*s; b = 0.17*(1-s)+0.14*s; }
      return [r, g, b];
    }

    function _gql3dUpdateCam() {
      if (!_gql3dViewer || !_gql3dTarget) return;
      const cam = _gql3dViewer.camera;
      cam.position.set(
        _gql3dTarget.x + _gql3dZoomDist * Math.sin(_gql3dRotY) * Math.cos(_gql3dRotX),
        _gql3dTarget.y + _gql3dZoomDist * Math.sin(_gql3dRotX),
        _gql3dTarget.z + _gql3dZoomDist * Math.cos(_gql3dRotY) * Math.cos(_gql3dRotX)
      );
      cam.lookAt(_gql3dTarget);
    }

    function _gql3dDispose() {
      if (_gql3dViewer) {
        cancelAnimationFrame(_gql3dViewer.animId);
        _gql3dViewer.renderer.dispose();
        _gql3dViewer.renderer.domElement.remove();
        _gql3dViewer = null;
      }
      _gql3dObjects = {};
      _gql3dGlobalMin = { x: Infinity, y: Infinity, z: Infinity };
      _gql3dGlobalMax = { x: -Infinity, y: -Infinity, z: -Infinity };
      _gql3dAutoRotate = true;
      _gql3dRotX = 0.55; _gql3dRotY = -0.6; _gql3dZoomDist = 3;
    }

    function _gql3dEnsureScene() {
      if (_gql3dViewer) return;
      const vp = $('gql3d-viewport');
      const W = vp.clientWidth, H = vp.clientHeight;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x1a1a2e);
      scene.add(new THREE.AmbientLight(0xffffff, 0.6));
      const dl = new THREE.DirectionalLight(0xffffff, 0.8);
      dl.position.set(2, 5, 3);
      scene.add(dl);

      // Ground grid
      const grid = new THREE.GridHelper(4, 20, 0x444466, 0x333355);
      grid.name = '__grid';
      scene.add(grid);

      const camera = new THREE.PerspectiveCamera(50, W / H, 0.01, 1e6);
      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setSize(W, H);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      vp.insertBefore(renderer.domElement, vp.firstChild);

      _gql3dTarget = new THREE.Vector3(0, 0, 0);

      // Orbit controls
      let drag = false, btn = -1, px = 0, py = 0;
      const el = renderer.domElement;
      el.addEventListener('contextmenu', e => e.preventDefault());
      el.addEventListener('mousedown', e => { drag = true; btn = e.button; px = e.clientX; py = e.clientY; _gql3dAutoRotate = false; });
      window.addEventListener('mouseup', () => { drag = false; btn = -1; });
      el.addEventListener('mousemove', e => {
        if (!drag) return;
        const dx = e.clientX - px, dy = e.clientY - py;
        px = e.clientX; py = e.clientY;
        if (btn === 0) {
          _gql3dRotY += dx * 0.008; _gql3dRotX += dy * 0.008;
          _gql3dRotX = Math.max(-Math.PI/2+0.01, Math.min(Math.PI/2-0.01, _gql3dRotX));
        } else if (btn === 2) {
          const ps = _gql3dZoomDist * 0.002;
          const right = new THREE.Vector3();
          right.crossVectors(camera.up, new THREE.Vector3().subVectors(_gql3dTarget, camera.position)).normalize();
          _gql3dTarget.addScaledVector(right, -dx * ps);
          _gql3dTarget.y += dy * ps;
        }
        _gql3dUpdateCam();
      });
      el.addEventListener('wheel', e => {
        e.preventDefault(); _gql3dAutoRotate = false;
        _gql3dZoomDist *= e.deltaY > 0 ? 1.1 : 0.9;
        _gql3dZoomDist = Math.max(0.3, Math.min(50, _gql3dZoomDist));
        _gql3dUpdateCam();
      }, { passive: false });

      // Touch support
      let lastPinch = 0;
      el.addEventListener('touchstart', e => {
        _gql3dAutoRotate = false;
        if (e.touches.length === 1) { drag = true; btn = 0; px = e.touches[0].clientX; py = e.touches[0].clientY; }
        else if (e.touches.length === 2) {
          drag = false;
          const dx = e.touches[1].clientX - e.touches[0].clientX, dy = e.touches[1].clientY - e.touches[0].clientY;
          lastPinch = Math.sqrt(dx*dx+dy*dy);
        }
      });
      el.addEventListener('touchmove', e => {
        e.preventDefault();
        if (e.touches.length === 1 && drag) {
          const dx = e.touches[0].clientX - px, dy = e.touches[0].clientY - py;
          _gql3dRotY += dx * 0.008; _gql3dRotX += dy * 0.008;
          _gql3dRotX = Math.max(-Math.PI/2+0.01, Math.min(Math.PI/2-0.01, _gql3dRotX));
          px = e.touches[0].clientX; py = e.touches[0].clientY;
          _gql3dUpdateCam();
        } else if (e.touches.length === 2) {
          const dx = e.touches[1].clientX - e.touches[0].clientX, dy = e.touches[1].clientY - e.touches[0].clientY;
          const dist = Math.sqrt(dx*dx+dy*dy);
          if (lastPinch > 0) { _gql3dZoomDist *= lastPinch/dist; _gql3dZoomDist = Math.max(0.3, Math.min(50, _gql3dZoomDist)); _gql3dUpdateCam(); }
          lastPinch = dist;
        }
      }, { passive: false });
      el.addEventListener('touchend', () => { drag = false; lastPinch = 0; });

      // Resize observer
      new ResizeObserver(() => {
        const w = vp.clientWidth, h = vp.clientHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      }).observe(vp);

      _gql3dUpdateCam();

      // Animate
      function animate() {
        const id = requestAnimationFrame(animate);
        _gql3dViewer.animId = id;
        if (_gql3dAutoRotate) { _gql3dRotY += 0.002; _gql3dUpdateCam(); }
        renderer.render(scene, camera);
      }
      _gql3dViewer = { renderer, scene, camera, animId: 0 };
      animate();
    }

    function _gql3dAddToScene(uuid, geo, hexColor, title) {
      _gql3dEnsureScene();
      const scene = _gql3dViewer.scene;
      const kind = geo.kind;
      const positions = geo.positions || [];
      const indices = geo.indices || [];
      const zmin = geo.zmin || 0, zmax = geo.zmax || 1;
      const nVerts = positions.length / 3;
      if (nVerts === 0) return;

      // Update global bounds
      for (let i = 0; i < positions.length; i += 3) {
        const x = positions[i], y = positions[i+1], z = positions[i+2];
        if (!isFinite(x) || !isFinite(y) || !isFinite(z)) continue;
        _gql3dGlobalMin.x = Math.min(_gql3dGlobalMin.x, x); _gql3dGlobalMax.x = Math.max(_gql3dGlobalMax.x, x);
        _gql3dGlobalMin.y = Math.min(_gql3dGlobalMin.y, y); _gql3dGlobalMax.y = Math.max(_gql3dGlobalMax.y, y);
        _gql3dGlobalMin.z = Math.min(_gql3dGlobalMin.z, z); _gql3dGlobalMax.z = Math.max(_gql3dGlobalMax.z, z);
      }

      const cx = (_gql3dGlobalMin.x + _gql3dGlobalMax.x) / 2;
      const cy = (_gql3dGlobalMin.y + _gql3dGlobalMax.y) / 2;
      const cz = (_gql3dGlobalMin.z + _gql3dGlobalMax.z) / 2;
      const extLateral = Math.max(_gql3dGlobalMax.x - _gql3dGlobalMin.x, _gql3dGlobalMax.y - _gql3dGlobalMin.y) || 1;
      const extZ = _gql3dGlobalMax.z - _gql3dGlobalMin.z;
      let zExag = 1;
      if (extZ > 0) {
        const ratio = extZ / extLateral;
        if (ratio < 0.4) zExag = Math.max(2, Math.min(15, 0.4 / ratio));
      }

      const baseColor = new THREE.Color(hexColor);
      const normPos = new Float32Array(positions.length);
      const colors = new Float32Array(positions.length);
      for (let i = 0; i < nVerts; i++) {
        normPos[i*3]     = (positions[i*3]     - cx) / extLateral * 2;
        normPos[i*3 + 1] = (positions[i*3 + 2] - cz) / extLateral * 2 * zExag;
        normPos[i*3 + 2] = (positions[i*3 + 1] - cy) / extLateral * 2;
        if (kind === 'surface' || kind === 'points') {
          const z = positions[i*3+2];
          const [cr, cg, cb] = _gql3dColorZ(isFinite(z) ? z : cz, zmin, zmax);
          colors[i*3] = cr; colors[i*3+1] = cg; colors[i*3+2] = cb;
        } else {
          colors[i*3] = baseColor.r; colors[i*3+1] = baseColor.g; colors[i*3+2] = baseColor.b;
        }
      }

      const geom3 = new THREE.BufferGeometry();
      geom3.setAttribute('position', new THREE.BufferAttribute(normPos, 3));
      geom3.setAttribute('color', new THREE.BufferAttribute(colors, 3));

      let mesh;
      if (kind === 'surface') {
        if (indices.length) geom3.setIndex(indices);
        geom3.computeVertexNormals();
        mesh = new THREE.Mesh(geom3, new THREE.MeshPhongMaterial({
          vertexColors: true, side: THREE.DoubleSide, shininess: 30, flatShading: false,
        }));
      } else if (kind === 'points' || kind === 'markers') {
        mesh = new THREE.Points(geom3, new THREE.PointsMaterial({
          vertexColors: true, size: kind === 'markers' ? 0.04 : 0.015, sizeAttenuation: true,
        }));
      } else if (kind === 'trajectory') {
        mesh = new THREE.Line(geom3, new THREE.LineBasicMaterial({ vertexColors: true, linewidth: 2 }));
        const sg = new THREE.SphereGeometry(0.012, 6, 6);
        const s1 = new THREE.Mesh(sg, new THREE.MeshBasicMaterial({ color: hexColor }));
        s1.position.set(normPos[0], normPos[1], normPos[2]);
        scene.add(s1);
        if (nVerts > 1) {
          const s2 = new THREE.Mesh(sg, new THREE.MeshBasicMaterial({ color: 0xff4444 }));
          s2.position.set(normPos[(nVerts-1)*3], normPos[(nVerts-1)*3+1], normPos[(nVerts-1)*3+2]);
          scene.add(s2);
        }
      } else if (kind === 'polylines') {
        const counts = geo.counts || [];
        mesh = new THREE.Group();
        if (counts.length > 0) {
          let offset = 0;
          for (const cnt of counts) {
            const lp = new Float32Array(cnt*3), lc = new Float32Array(cnt*3);
            for (let j = 0; j < cnt && (offset+j) < nVerts; j++) {
              const idx = offset+j;
              lp[j*3]=normPos[idx*3]; lp[j*3+1]=normPos[idx*3+1]; lp[j*3+2]=normPos[idx*3+2];
              lc[j*3]=colors[idx*3]; lc[j*3+1]=colors[idx*3+1]; lc[j*3+2]=colors[idx*3+2];
            }
            offset += cnt;
            const lg = new THREE.BufferGeometry();
            lg.setAttribute('position', new THREE.BufferAttribute(lp, 3));
            lg.setAttribute('color', new THREE.BufferAttribute(lc, 3));
            mesh.add(new THREE.Line(lg, new THREE.LineBasicMaterial({ vertexColors: true })));
          }
        } else {
          mesh = new THREE.Line(geom3, new THREE.LineBasicMaterial({ vertexColors: true }));
        }
      }

      if (mesh) {
        mesh.userData.vizUuid = uuid;
        scene.add(mesh);
        _gql3dObjects[uuid] = { mesh, geo, color: hexColor, visible: true, title: title || uuid, kind };
      }
    }

    function _gql3dFitCamera() {
      if (!_gql3dViewer || Object.keys(_gql3dObjects).length === 0) return;
      const box = new THREE.Box3();
      _gql3dViewer.scene.traverse(obj => {
        if (obj.isMesh || obj.isLine || obj.isPoints) {
          const b = new THREE.Box3().setFromBufferAttribute(obj.geometry?.attributes?.position);
          if (!b.isEmpty()) box.union(b);
        }
      });
      if (box.isEmpty()) return;
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      _gql3dTarget.copy(center);
      _gql3dZoomDist = Math.max(size.x, size.y, size.z) * 1.8;
      _gql3dUpdateCam();

      const gridObj = _gql3dViewer.scene.getObjectByName('__grid');
      if (gridObj) {
        gridObj.position.y = box.min.y - 0.05;
        const gs = Math.max(size.x, size.z) * 1.3;
        gridObj.scale.set(gs/4, 1, gs/4);
      }
    }

    function _gql3dUpdateHud() {
      const hud = $('gql3d-hud');
      const count = Object.keys(_gql3dObjects).length;
      let totalVerts = 0;
      for (const o of Object.values(_gql3dObjects)) totalVerts += (o.geo.positions || []).length / 3;
      hud.innerHTML = `${count} objects · ${totalVerts.toLocaleString()} vertices<br>Drag: orbit · Right-drag: pan · Scroll: zoom`;
      hud.style.display = count > 0 ? '' : 'none';
    }

    function _gql3dUpdateLegend() {
      const legend = $('gql3d-legend');
      const entries = Object.values(_gql3dObjects);
      if (entries.length === 0) { legend.style.display = 'none'; return; }
      legend.style.display = '';
      const kindLabels = { surface:'Surface', points:'Points', trajectory:'Well', markers:'Markers', polylines:'Polylines' };
      legend.innerHTML = entries.map(o =>
        `<div class="gql3d-legend-item"><span class="gql3d-legend-dot" style="background:${o.color}"></span>${esc(o.title)} <span style="opacity:0.6;font-size:10px;">(${kindLabels[o.kind]||o.kind})</span></div>`
      ).join('');
    }

    /**
     * Extract renderable objects from GraphQL query result data.
     * Returns array of { uuid, title, typeName } for 3D-capable types.
     */
    function extractRenderableObjects(data) {
      if (!data || !data.data) return [];
      const d = data.data;
      const objs = [];

      if (d.deepSearch && d.deepSearch.objects) {
        d.deepSearch.objects.forEach(o => {
          if (is3dType(o.typeName)) objs.push({ uuid: o.uuid, title: o.title, typeName: o.typeName });
        });
      }
      if (d.federatedSearch && d.federatedSearch.hits) {
        d.federatedSearch.hits.forEach(h => {
          if (is3dType(h.typeName)) objs.push({ uuid: h.uuid, title: h.title, typeName: h.typeName });
        });
      }
      if (d.resqmlObjects) {
        d.resqmlObjects.forEach(o => {
          if (is3dType(o.typeName)) objs.push({ uuid: o.uuid, title: o.title, typeName: o.typeName });
        });
      }
      return objs;
    }

    /**
     * Build and insert the "Show 3D Results" button into a container element.
     * @param {HTMLElement} container – element to append button into
     * @param {Array} renderableObjs – [{uuid, title, typeName}]
     */
    function insertShow3DButton(container, renderableObjs) {
      if (!renderableObjs.length) return;
      const wrapper = document.createElement('div');
      wrapper.style.cssText = 'margin:10px 0 4px;display:flex;align-items:center;gap:10px;';
      wrapper.innerHTML = `<button class="btn-show3d-results" id="gql3d-trigger">
        <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
        Show 3D Results (${renderableObjs.length})
      </button>
      <span style="font-size:12px;color:#605e5c;">${renderableObjs.length} renderable object${renderableObjs.length > 1 ? 's' : ''} found</span>`;
      container.appendChild(wrapper);

      wrapper.querySelector('#gql3d-trigger').addEventListener('click', () => {
        openGql3DPopup(renderableObjs);
      });
    }

    /**
     * Open the 3D popup and load geometry for the given objects.
     */
    async function openGql3DPopup(renderableObjs) {
      const overlay = $('gql3d-overlay');
      overlay.classList.add('open');
      $('gql3d-loading').style.display = '';
      $('gql3d-loading').textContent = `Loading 3D geometry for ${renderableObjs.length} objects…`;
      _gql3dDispose();

      $('gql3d-title').textContent = `3D Results (${renderableObjs.length} objects)`;
      $('gql3d-status-hdr').textContent = 'Loading…';

      // Determine dataspaces to try
      const dsList = Array.from(dsSel.selectedOptions).map(o => o.value);
      if (!dsList.length) dsList.push('maap/drogon');  // fallback

      // Build batch requests: try each DS until we get geometry
      const batch = renderableObjs.map((o, i) => ({
        typ: o.typeName, uuid: o.uuid, title: o.title,
        color: _GQL3D_PALETTE[i % _GQL3D_PALETTE.length],
      }));

      let loaded = 0, failed = 0;

      for (const ds of dsList) {
        // Filter to objects not yet loaded
        const toLoad = batch.filter(b => !_gql3dObjects[b.uuid]);
        if (toLoad.length === 0) break;

        try {
          const r = await fetch('/keys/viz/batch.json', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ds, objects: toLoad.map(b => ({ typ: b.typ, uuid: b.uuid })) }),
          });
          const data = await r.json();
          const results = data.results || [];
          for (let j = 0; j < toLoad.length && j < results.length; j++) {
            const item = toLoad[j];
            const geo = results[j];
            if (geo && !geo.error && (geo.positions || []).length > 0) {
              _gql3dAddToScene(item.uuid, geo, item.color, item.title);
              loaded++;
            }
          }
        } catch (e) {
          console.error('3D batch fetch failed for ds=' + ds, e);
        }
        $('gql3d-loading').textContent = `Loading… ${loaded} loaded so far`;
      }

      // Count failures
      failed = renderableObjs.length - loaded;

      $('gql3d-loading').style.display = 'none';
      $('gql3d-status-hdr').textContent = loaded > 0
        ? `${loaded} loaded${failed > 0 ? ', ' + failed + ' failed' : ''}`
        : 'No geometry data available';

      if (loaded > 0) {
        _gql3dFitCamera();
        _gql3dUpdateHud();
        _gql3dUpdateLegend();
      } else {
        $('gql3d-loading').style.display = '';
        $('gql3d-loading').textContent = 'No 3D geometry data available for these objects. They may not have spatial data in the current dataspaces.';
      }
    }

    // Close popup
    $('gql3d-close').addEventListener('click', () => {
      $('gql3d-overlay').classList.remove('open');
      _gql3dDispose();
      $('gql3d-hud').style.display = 'none';
      $('gql3d-legend').style.display = 'none';
    });

    // Close on overlay click (outside modal)
    $('gql3d-overlay').addEventListener('click', (e) => {
      if (e.target === $('gql3d-overlay')) {
        $('gql3d-close').click();
      }
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && $('gql3d-overlay').classList.contains('open')) {
        $('gql3d-close').click();
      }
    });

    /**
     * Classify a Grid2dRepresentation as 'map', 'table', or 'both'.
     *
     * Map (spatial surface): real-world origin coords (large X/Y from UTM),
     *   real offset vectors with spatial spacing, linked CRS.
     * Table (resqpy DataFrame): origin at (0,0), ExtraMetadata with
     *   stl_columns/stl_uoms keys, linked StringTableLookup targets.
     */
    function classifyGrid2d(content) {
      const patch = content.Grid2dPatch || {};
      const geom = (patch.Geometry || {}).Points || {};
      const support = geom.SupportingGeometry || {};
      const origin = support.Origin || geom.Origin || {};
      const ox = Math.abs(parseFloat(origin.Coordinate1 || 0));
      const oy = Math.abs(parseFloat(origin.Coordinate2 || 0));

      // Check ExtraMetadata for table markers (resqpy DataFrame convention)
      const em = content.ExtraMetadata || [];
      const emKeys = em.map(e => (e.Name || e.name || '').toLowerCase());
      const hasStlMarkers = emKeys.some(k => k.startsWith('stl_'));

      // Spatial origin: UTM coords are typically > 1000
      const hasSpatialOrigin = ox > 1000 || oy > 1000;

      // Tables are rare - only when explicit STL markers exist and no spatial origin
      if (hasStlMarkers && !hasSpatialOrigin) return 'table';
      if (hasStlMarkers && hasSpatialOrigin) return 'both';
      // Default: treat as map (spatial surface) - the common case
      return 'map';
    }

    async function loadDataspaces() {
      // Check for prefetched cache from howto page
      const cachedLocal = sessionStorage.getItem('_ds_keys_local');
      const cachedRemote = sessionStorage.getItem('_ds_keys_remote');
      if (cachedLocal || cachedRemote) {
        sessionStorage.removeItem('_ds_keys_local');
        sessionStorage.removeItem('_ds_keys_remote');
        try {
          const localItems = cachedLocal ? JSON.parse(cachedLocal) : [];
          const remoteItems = cachedRemote ? JSON.parse(cachedRemote) : [];
          // Merge (dedup by path)
          const seen = new Set();
          const merged = [];
          for (const item of [...localItems, ...remoteItems]) {
            if (item.path && !seen.has(item.path)) { merged.push(item); seen.add(item.path); }
          }
          if (merged.length) {
            populateDataspaces(merged);
            setMsg('');
            // Still refresh remote in background for freshness
            fetch('/keys/dataspaces.json?source=remote', { credentials: 'same-origin' })
              .then(r => r.ok ? r.json() : null)
              .then(js => {
                if (js && js.items && js.items.length) {
                  const paths = new Set(_allDsItems.map(x => x.path));
                  const m2 = [..._allDsItems];
                  for (const item of js.items) {
                    if (item.path && !paths.has(item.path)) { m2.push(item); paths.add(item.path); }
                  }
                  populateDataspaces(m2);
                }
              })
              .catch(() => {});
            return true;
          }
        } catch (_) {}
      }

      // Progressive load: local first (instant), then remote in background
      const dsStatus = document.getElementById('ds-loading-status');
      const dsElapsed = document.getElementById('ds-loading-elapsed');
      let elapsed = 0;
      dsStatus.style.display = 'block';
      const timer = setInterval(() => { elapsed++; if (dsElapsed) dsElapsed.textContent = elapsed; }, 1000);

      let gotSome = false;
      try {
        // Phase 1: fast local PG dataspaces
        const rLocal = await fetch('/keys/dataspaces.json?source=local', { credentials: 'same-origin' });
        if (rLocal.ok) {
          const jsLocal = await rLocal.json();
          if (jsLocal.items && jsLocal.items.length > 0) {
            populateDataspaces(jsLocal.items);
            setMsg('');
            gotSome = true;
          }
        }
      } catch (e) {
        // Non-fatal - continue to remote
        console.debug('Local dataspaces failed:', e);
      }

      // Phase 2: fetch remote (with status update)
      if (dsStatus) dsStatus.innerHTML = '⏳ Loading remote dataspaces… <span id="ds-loading-elapsed">' + elapsed + '</span>s';
      const dsElapsed2 = document.getElementById('ds-loading-elapsed');
      clearInterval(timer);
      const timer2 = setInterval(() => { elapsed++; if (dsElapsed2) dsElapsed2.textContent = elapsed; }, 1000);

      (async () => {
        try {
          const rRemote = await fetch('/keys/dataspaces.json?source=remote', { credentials: 'same-origin' });
          if (rRemote.ok) {
            const jsRemote = await rRemote.json();
            if (jsRemote.items && jsRemote.items.length > 0) {
              // Merge with existing local items (dedup by path)
              const existingPaths = new Set(_allDsItems.map(x => x.path));
              const merged = [..._allDsItems];
              for (const item of jsRemote.items) {
                if (item.path && !existingPaths.has(item.path)) {
                  merged.push(item);
                  existingPaths.add(item.path);
                }
              }
              populateDataspaces(merged);
              gotSome = true;
            }
          }
        } catch (e) {
          console.debug('Remote dataspaces failed:', e);
        }
        clearInterval(timer2);
        if (dsStatus) dsStatus.style.display = 'none';
        // Final fallback if nothing loaded
        if (!gotSome) {
          if (Array.isArray(window.PREFILL_DS) && window.PREFILL_DS.length > 0) {
            populateDataspaces(window.PREFILL_DS);
            setMsg('');
          } else {
            setMsg('No dataspaces found.');
          }
        }
      })();

      // If local delivered results, we're good to proceed already
      if (!gotSome && Array.isArray(window.PREFILL_DS) && window.PREFILL_DS.length > 0) {
        populateDataspaces(window.PREFILL_DS);
        setMsg('');
        gotSome = true;
      }
      return gotSome;
    }

    async function loadTypes() {
      if (!dsSel.value) return;
      setMsg('Loading types…');
      showLoading('Loading types…');
      try {
        const r = await fetch(`/keys/types.json?ds=${encodeURIComponent(dsSel.value)}`, { credentials: 'same-origin' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const js = await r.json();
        typSel.innerHTML = '';
        (js.items || []).forEach(x => {
          if (!x || !x.name) return;
          const o = document.createElement('option');
          o.value = x.name;
          o.textContent = x.count ? `${x.name} (${x.count})` : x.name;
          typSel.appendChild(o);
        });
        objSel.innerHTML = '';
        clearDetails();
        setMsg(js.items && js.items.length ? '' : 'No types found in this dataspace.');
      } catch (e) {
        setMsg('Failed to load types.');
        console.error(e);
      } finally {
        hideLoading();
      }
    }

    async function loadObjects() {
      if (!dsSel.value || !typSel.value) return;
      setMsg('Loading objects…');
      showLoading('Loading objects…');
      try {
        const url = `/keys/objects.json?ds=${encodeURIComponent(dsSel.value)}&typ=${encodeURIComponent(typSel.value)}`;
        const r = await fetch(url, { credentials: 'same-origin' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const js = await r.json();
        objSel.innerHTML = '';
        (js.items || []).forEach(x => {
          const o = document.createElement('option');
          o.value = x.uuid;
          o.textContent = `${x.title || x.uuid} - ${x.uuid}`;
          o.setAttribute('data-uri', x.uri || '');
          objSel.appendChild(o);
        });
        clearDetails();
        setMsg(js.items && js.items.length ? '' : 'No objects in this type.');
      } catch (e) {
        setMsg('Failed to load objects.');
        console.error(e);
      } finally {
        hideLoading();
      }
    }

    async function loadDetails() {
      const ds = dsSel.value, typ = typSel.value, uuid = objSel.value;
      if (!ds || !typ || !uuid) { setMsg('Pick dataspace, type, and object.'); return; }
      setMsg('Loading object details…');
      showLoading('Loading object details…');
      clearDetails();
      try {
        // Fetch object details and graph in parallel
        const qp = `ds=${encodeURIComponent(ds)}&typ=${encodeURIComponent(typ)}&uuid=${encodeURIComponent(uuid)}`;
        const [objRes, graphRes] = await Promise.all([
          fetch(`/keys/object.json?${qp}`, { credentials: 'same-origin' }),
          fetch(`/keys/object/graph.json?${qp}`, { credentials: 'same-origin' }).catch(() => null),
        ]);
        if (!objRes.ok) throw new Error('HTTP ' + objRes.status);
        const js = await objRes.json();

        // --- Primary info ---
        const p = js.primary || {};
        const uri = p.uri || (objSel.selectedOptions[0] && objSel.selectedOptions[0].getAttribute('data-uri')) || '';
        const ct  = p.contentType || '';
        const title = p.title || uuid;

        summaryEl.innerHTML =
          `<div><b>Title:</b> ${esc(title)}</div>` +
          `<div><b>Dataspace:</b> <code>${esc(ds)}</code></div>` +
          `<div><b>Type:</b> <code>${esc(typ)}</code></div>` +
          `<div><b>UUID:</b> <code>${esc(uuid)}</code></div>` +
          `<div><b>URI:</b> <code>${esc(uri)}</code></div>` +
          `<div><b>ContentType:</b> <code>${esc(ct)}</code></div>`;

        // --- Structured Metadata (pairs) ---
        const md = js.metadata || {};
        const pairs = md.pairs || [];
        if (pairs.length) {
          metadataSection.style.display = '';
          metadataPairs.innerHTML = renderPairsTable(pairs);
        }

        // --- ExtraMetadata ---
        const em = md.extraMetadata || [];
        if (em.length) {
          extrametaSection.style.display = '';
          extrametaEl.innerHTML = `<table class="meta-table"><thead><tr><th>Name</th><th>Value</th></tr></thead><tbody>${
            em.map(e => `<tr><td>${esc(e.name)}</td><td><code>${esc(e.value)}</code></td></tr>`).join('')
          }</tbody></table>`;
        }

        // --- Aliases ---
        const al = md.aliases || [];
        if (al.length) {
          aliasesSection.style.display = '';
          aliasesEl.innerHTML = `<table class="meta-table"><thead><tr><th>Authority</th><th>Identifier</th></tr></thead><tbody>${
            al.map(a => `<tr><td>${esc(a.authority)}</td><td><code>${esc(a.identifier)}</code></td></tr>`).join('')
          }</tbody></table>`;
        }

        // --- Graph (Targets / Sources) ---
        if (graphRes && graphRes.ok) {
          try {
            const g = await graphRes.json();
            // Parse uri → type + uuid; use 'name' for title
            function parseEdge(e) {
              const uri = e.uri || '';
              let ct = e.contentType || e.$type || '';
              let uid = e.uuid || e.UUID || e.Uuid || '';
              let title = e.name || e.title || (e.Citation && e.Citation.Title) || '';
              // Extract from uri: .../resqml20.obj_Foo('uuid')
              const m = uri.match(/\/([^\/]+)\(([^)]+)\)\s*$/);
              if (m) { if (!ct) ct = m[1]; if (!uid) uid = m[2]; }
              return { ct, uid, title, uri };
            }
            const tgt = (g.targets || []).filter(e => typeof e === 'object').map(parseEdge);
            const src = (g.sources || []).filter(e => typeof e === 'object').map(parseEdge);
            const crs = g.crs;
            const edgeLi = (items) => items.length
              ? `<ul>${items.map(e => `<li><code>${esc(e.ct)}</code> - <code>${esc(e.uid)}</code> - ${esc(e.title)}</li>`).join('')}</ul>`
              : '<p class="muted">None</p>';
            edgesEl.innerHTML = `
              <details open>
                <summary><b>Targets</b> (${tgt.length})</summary>
                ${edgeLi(tgt)}
              </details>
              <details open>
                <summary><b>Sources</b> (${src.length})</summary>
                ${edgeLi(src)}
              </details>
              ${crs ? `<details><summary><b>CRS</b></summary><pre>${esc(JSON.stringify(crs, null, 2))}</pre></details>` : ''}
            `;
          } catch (ge) {
            edgesEl.innerHTML = '<p class="muted">Failed to load graph.</p>';
            console.warn('Graph error:', ge);
          }
        } else {
          edgesEl.innerHTML = '<p class="muted">Graph not available.</p>';
        }

        // --- Arrays ---
        const arr = js.arrays || [];
        arraysEl.innerHTML = arr.length
          ? `<ul>${
              arr.map(a => {
                const p = a.path || a.pathInResource || (a.uid && a.uid.pathInResource) || '';
                return `<li><code>${esc(p)}</code></li>`;
              }).join('')
            }</ul>`
          : '<p class="muted">No arrays.</p>';

        // --- Grid2d section (auto-detect table vs depth map) ---
        if (isGrid2dType(typ)) {
          grid2dSection.style.display = '';
          const mode = (arr.length > 0) ? classifyGrid2d(js.content || {}) : 'map';
          grid2dBadge.textContent = mode === 'table' ? 'Data Table'
                                 : mode === 'map'   ? 'Depth Map'
                                 : 'Grid2dRepresentation';
          grid2dStatus.textContent = '';
          btnTable.style.display = (mode === 'table' || mode === 'both') ? '' : 'none';
          btnMap.style.display   = (mode === 'map'   || mode === 'both') ? '' : 'none';
          btn3d.style.display = (mode === 'map' || mode === 'both') ? '' : 'none';
          const hint = mode === 'table' ? 'Detected as a data table (resqpy DataFrame).'
                     : mode === 'map'   ? 'Detected as a spatial depth surface.'
                     : 'Could not auto-detect - try either view.';
          grid2dView.innerHTML = `<p class="muted">${hint}</p>`;
        }
        // --- Other 3D-capable types ---
        else if (is3dType(typ)) {
          grid2dSection.style.display = '';
          const shortType = typ.replace(/.*obj_/, '').replace(/Representation$/, '');
          grid2dBadge.textContent = shortType;
          grid2dStatus.textContent = '';
          btnTable.style.display = 'none';
          // Show depth map for TriangulatedSet surfaces
          const isSurface = typ.toLowerCase().includes('triangulated');
          btnMap.style.display = isSurface ? '' : 'none';
          btn3d.style.display = '';
          const mapHint = isSurface ? ' Use "Show depth map" for a 2D top-down view.' : '';
          grid2dView.innerHTML = `<p class="muted">Click "View 3D" to render this ${esc(shortType)} interactively.${mapHint}</p>`;
        }

        // --- Raw JSON ---
        metaEl.textContent = JSON.stringify(js.content || {}, null, 2);

        setMsg('');
      } catch (e) {
        setMsg('Failed to load object: ' + e.message);
        console.error(e);
      } finally {
        hideLoading();
      }
    }

    async function loadMap() {
      const ds = dsSel.value, uuid = objSel.value, typ = typSel.value;
      if (!ds || !uuid) return;
      grid2dStatus.textContent = 'Loading map…';
      grid2dView.innerHTML = '';
      try {
        // First fetch metadata to show stats while PNG loads
        const metaUrl = `/keys/object/map.json?ds=${encodeURIComponent(ds)}&uuid=${encodeURIComponent(uuid)}&typ=${encodeURIComponent(typ)}`;
        const metaRes = await fetch(metaUrl, { credentials: 'same-origin' });
        let statsHtml = '';
        if (metaRes.ok) {
          const meta = await metaRes.json();
          const s = meta.stats || {};
          const c = meta.crs || {};
          const d = meta.dims || [0,0];
          const isTriset = meta.kind === 'triset';
          const dimLabel = isTriset ? `${d[0].toLocaleString()} verts · ${d[1].toLocaleString()} tris`
                                    : `${d[0]}×${d[1]}`;
          statsHtml = `<div style="font-size:13px;color:#605e5c;margin-bottom:6px;">`
            + `<b>${esc(meta.title || '')}</b> - ${dimLabel}`
            + (s.min !== undefined ? ` - z: ${s.min} … ${s.max} ${c.verticalUom || 'm'}` : '')
            + (c.projectedUom ? ` - xy: ${c.projectedUom}` : '')
            + `</div>`;
        }

        // Build PNG URL with controls
        let cmap = 'viridis_r', dpi = 120, w = 12, h = 9;
        const pngUrl = () => `/keys/object/map.png?ds=${encodeURIComponent(ds)}&uuid=${encodeURIComponent(uuid)}&typ=${encodeURIComponent(typ)}&cmap=${cmap}&dpi=${dpi}&w=${w}&h=${h}`;

        grid2dView.innerHTML = statsHtml
          + `<div class="map-controls">`
          + `<label>Colormap</label><select id="map-cmap">`
          + ['viridis_r','terrain','coolwarm','RdYlBu_r','plasma_r','cividis_r','Spectral_r']
              .map(c => `<option${c==='viridis_r'?' selected':''}>${c}</option>`).join('')
          + `</select>`
          + `<label>DPI</label><select id="map-dpi"><option>96</option><option selected>120</option><option>150</option><option>200</option></select>`
          + `</div>`
          + `<div class="map-wrap"><img id="map-img" alt="Loading depth map…" /></div>`;

        const img = $('map-img');
        img.src = pngUrl();
        img.onload = () => { grid2dStatus.textContent = 'Done'; };
        img.onerror = () => {
          grid2dStatus.textContent = 'Failed';
          grid2dView.innerHTML += '<p style="color:red;">Failed to render depth map. The server may not have z-values or CRS data for this surface.</p>';
        };

        // Wire controls
        $('map-cmap').onchange = function() { cmap = this.value; img.src = pngUrl(); grid2dStatus.textContent = 'Refreshing…'; };
        $('map-dpi').onchange = function() { dpi = parseInt(this.value); img.src = pngUrl(); grid2dStatus.textContent = 'Refreshing…'; };

      } catch (e) {
        grid2dStatus.textContent = 'Failed';
        grid2dView.innerHTML = `<p style="color:red;">${esc(e.message)}</p>`;
        console.error(e);
      }
    }

    async function loadTable() {
      const ds = dsSel.value, typ = typSel.value, uuid = objSel.value;
      if (!ds || !typ || !uuid) return;
      grid2dStatus.textContent = 'Reconstructing…';
      grid2dView.innerHTML = '';
      try {
        const url = `/keys/object/table.json?ds=${encodeURIComponent(ds)}&typ=${encodeURIComponent(typ)}&uuid=${encodeURIComponent(uuid)}`;
        const r = await fetch(url, { credentials: 'same-origin' });
        if (!r.ok) {
          const err = await r.text();
          throw new Error(`HTTP ${r.status}: ${err}`);
        }
        const js = await r.json();

        const cols = js.columns || [];
        const uoms = js.uoms || [];
        const rows = js.rows || [];
        const nRows = js.n_rows || rows.length;
        const nCols = js.n_cols || cols.length;
        const truncated = js.truncated || false;
        const maxRows = js.max_rows || 0;
        const lookups = js.string_lookups || {};

        // Truncation notice
        let notice = '';
        if (truncated) {
          notice = `<div class="truncation-notice">Showing first ${rows.length} of ${nRows} rows (max ${maxRows}). Full dataset has ${nRows} rows × ${nCols} columns.</div>`;
        }

        // Build header row
        const hasUoms = uoms.some(u => u && u !== '');
        let thead = '<tr>' + cols.map(c => `<th>${esc(String(c))}</th>`).join('') + '</tr>';
        if (hasUoms) {
          thead += '<tr class="uom-row">' + uoms.map(u => `<th>${esc(String(u || ''))}</th>`).join('') + '</tr>';
        }

        // Build data rows
        const tbody = rows.map(row => {
          if (!Array.isArray(row)) return '';
          return '<tr>' + row.map(cell => {
            const v = cell === null || cell === undefined ? '' : String(cell);
            return `<td>${esc(v)}</td>`;
          }).join('') + '</tr>';
        }).join('');

        // String lookups info
        let lookupInfo = '';
        const lookupKeys = Object.keys(lookups);
        if (lookupKeys.length) {
          lookupInfo = `<details style="margin-top:8px;"><summary><b>String Lookups</b> (${lookupKeys.length})</summary><ul>${
            lookupKeys.map(k => {
              const lu = lookups[k];
              const entries = Object.entries(lu || {});
              const preview = entries.slice(0, 8).map(([i,v]) => `${i}→${v}`).join(', ');
              const more = entries.length > 8 ? ` … +${entries.length - 8}` : '';
              return `<li><b>${esc(k)}</b> (${entries.length} entries): ${esc(preview + more)}</li>`;
            }).join('')
          }</ul></details>`;
        }

        grid2dView.innerHTML =
          notice +
          `<p class="muted">${nRows} rows × ${nCols} columns</p>` +
          `<table class="data-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table>` +
          lookupInfo;

        grid2dStatus.textContent = truncated ? `Showing ${rows.length}/${nRows} rows` : `${nRows} rows`;
      } catch (e) {
        grid2dStatus.textContent = 'Failed';
        grid2dView.innerHTML = `<p style="color:red;">${esc(e.message)}</p>`;
        console.error(e);
      }
    }

    // ── Three.js 3D Viewer ───────────────────────────────────────────────
    let _viewer3d = null;  // holds { renderer, scene, camera, controls, animId }

    function dispose3D() {
      if (_viewer3d) {
        cancelAnimationFrame(_viewer3d.animId);
        _viewer3d.controls.dispose();
        _viewer3d.renderer.dispose();
        _viewer3d = null;
      }
    }

    function colorFromZ(z, zmin, zmax) {
      // viridis-like gradient: purple → blue → teal → green → yellow
      const t = zmax > zmin ? Math.max(0, Math.min(1, (z - zmin) / (zmax - zmin))) : 0.5;
      // Piecewise for better contrast
      let r, g, b;
      if (t < 0.25) {
        const s = t / 0.25;
        r = 0.28 * (1-s) + 0.13 * s;
        g = 0.0  * (1-s) + 0.57 * s;
        b = 0.33 * (1-s) + 0.55 * s;
      } else if (t < 0.5) {
        const s = (t - 0.25) / 0.25;
        r = 0.13 * (1-s) + 0.15 * s;
        g = 0.57 * (1-s) + 0.73 * s;
        b = 0.55 * (1-s) + 0.34 * s;
      } else if (t < 0.75) {
        const s = (t - 0.5) / 0.25;
        r = 0.15 * (1-s) + 0.63 * s;
        g = 0.73 * (1-s) + 0.85 * s;
        b = 0.34 * (1-s) + 0.17 * s;
      } else {
        const s = (t - 0.75) / 0.25;
        r = 0.63 * (1-s) + 0.99 * s;
        g = 0.85 * (1-s) + 0.91 * s;
        b = 0.17 * (1-s) + 0.14 * s;
      }
      return [r, g, b];
    }

    async function load3D() {
      const ds = dsSel.value, typ = typSel.value, uuid = objSel.value;
      if (!ds || !typ || !uuid) return;
      grid2dStatus.textContent = 'Loading 3D geometry…';
      grid2dView.innerHTML = '';
      dispose3D();

      try {
        const url = `/keys/object/geometry3d.json?ds=${encodeURIComponent(ds)}&typ=${encodeURIComponent(typ)}&uuid=${encodeURIComponent(uuid)}`;
        const r = await fetch(url, { credentials: 'same-origin' });
        if (!r.ok) {
          const err = await r.text();
          throw new Error(`HTTP ${r.status}: ${err}`);
        }
        const geo = await r.json();
        const kind = geo.kind;  // 'surface', 'points', 'trajectory', 'markers'
        const positions = geo.positions || [];
        const indices = geo.indices || [];
        const zmin = geo.zmin || 0, zmax = geo.zmax || 1;
        const nVerts = positions.length / 3;

        if (nVerts === 0) {
          grid2dView.innerHTML = '<p style="color:orange;">No geometry data found for this object.</p>';
          grid2dStatus.textContent = 'No data';
          return;
        }

        // Build container
        grid2dView.innerHTML = `<div id="viewer3d-container">
          <div class="viewer3d-hud" id="viewer3d-hud"></div>
          <canvas id="viewer3d-legend" class="viewer3d-legend" width="24" height="200"></canvas>
          <div class="viewer3d-legend-labels" id="viewer3d-legend-labels"></div>
        </div>`;

        const container = $('viewer3d-container');
        const W = container.clientWidth, H = container.clientHeight;

        // Setup Three.js scene
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x1a1a2e);

        const camera = new THREE.PerspectiveCamera(50, W / H, 0.1, 1e7);
        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(W, H);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        container.insertBefore(renderer.domElement, container.firstChild);

        // OrbitControls (inline since module import may not work with CDN)
        // We'll use a simple manual orbit instead:
        let isDragging = false, prevX = 0, prevY = 0, dragBtn = -1;
        let rotX = 0.55, rotY = -0.6;   // angled oblique view
        let panX = 0, panY = 0;
        let zoomDist = 1;

        // Compute bounding box to center the scene
        let minX = Infinity, maxX = -Infinity;
        let minY = Infinity, maxY = -Infinity;
        let minZ = Infinity, maxZ = -Infinity;
        for (let i = 0; i < nVerts; i++) {
          const x = positions[i*3], y = positions[i*3+1], z = positions[i*3+2];
          if (isFinite(x) && isFinite(y) && isFinite(z)) {
            minX = Math.min(minX, x); maxX = Math.max(maxX, x);
            minY = Math.min(minY, y); maxY = Math.max(maxY, y);
            minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z);
          }
        }
        const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2, cz = (minZ + maxZ) / 2;
        const extX = maxX - minX, extY = maxY - minY, extZ = maxZ - minZ;
        const extLateral = Math.max(extX, extY) || 1;
        const extent = Math.max(extX, extY, extZ) || 1;
        // Z exaggeration: amplify depth relief so it's clearly visible in 3D
        // For subsurface surfaces the Z range is often <5% of lateral → exaggerate
        let zExag = 1;
        if (extZ > 0 && kind === 'surface') {
          const ratio = extZ / extLateral;
          // Auto-exaggerate so depth relief is clearly visible in 3D
          // No hard cap – the HUD shows the exaggeration factor
          if (ratio < 0.4) zExag = Math.max(3, 0.4 / ratio);
        }

        // Normalize positions to center and apply z-exaggeration
        const normPos = new Float32Array(positions.length);
        const colors = new Float32Array(positions.length);
        for (let i = 0; i < nVerts; i++) {
          normPos[i*3]     = (positions[i*3]     - cx) / extLateral * 2;
          normPos[i*3 + 1] = (positions[i*3 + 2] - cz) / extLateral * 2 * zExag;  // Z → Y (up)
          normPos[i*3 + 2] = (positions[i*3 + 1] - cy) / extLateral * 2;          // Y → Z (depth)
          const z = positions[i*3 + 2];
          const [cr, cg, cb] = colorFromZ(isFinite(z) ? z : cz, zmin, zmax);
          colors[i*3] = cr; colors[i*3+1] = cg; colors[i*3+2] = cb;
        }

        // Create geometry
        const geom3 = new THREE.BufferGeometry();
        geom3.setAttribute('position', new THREE.BufferAttribute(normPos, 3));
        geom3.setAttribute('color', new THREE.BufferAttribute(colors, 3));

        let mesh;
        if (kind === 'surface') {
          // Indexed triangle mesh
          if (indices.length) {
            geom3.setIndex(indices);
          }
          geom3.computeVertexNormals();
          const mat = new THREE.MeshPhongMaterial({
            vertexColors: true, side: THREE.DoubleSide,
            shininess: 30, flatShading: false,
          });
          mesh = new THREE.Mesh(geom3, mat);
        } else if (kind === 'points' || kind === 'markers') {
          const mat = new THREE.PointsMaterial({
            vertexColors: true, size: kind === 'markers' ? 0.04 : 0.015,
            sizeAttenuation: true,
          });
          mesh = new THREE.Points(geom3, mat);

          // For markers, add label sprites
          if (kind === 'markers' && geo.labels && geo.labels.length) {
            for (let i = 0; i < Math.min(geo.labels.length, nVerts); i++) {
              if (!geo.labels[i]) continue;
              const canvas = document.createElement('canvas');
              canvas.width = 256; canvas.height = 64;
              const ctx2 = canvas.getContext('2d');
              ctx2.fillStyle = '#fff';
              ctx2.font = '24px sans-serif';
              ctx2.fillText(geo.labels[i], 4, 40);
              const tex = new THREE.CanvasTexture(canvas);
              const spriteMat = new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 0.9 });
              const sprite = new THREE.Sprite(spriteMat);
              sprite.position.set(normPos[i*3] + 0.03, normPos[i*3+1] + 0.03, normPos[i*3+2]);
              sprite.scale.set(0.15, 0.04, 1);
              scene.add(sprite);
            }
          }
        } else if (kind === 'trajectory') {
          // Line
          const lineMat = new THREE.LineBasicMaterial({ vertexColors: true, linewidth: 2 });
          mesh = new THREE.Line(geom3, lineMat);

          // Add small spheres at start/end
          const sphereGeo = new THREE.SphereGeometry(0.015, 8, 8);
          const startMat = new THREE.MeshBasicMaterial({ color: 0x00ff88 });
          const endMat = new THREE.MeshBasicMaterial({ color: 0xff4444 });
          const startSphere = new THREE.Mesh(sphereGeo, startMat);
          startSphere.position.set(normPos[0], normPos[1], normPos[2]);
          scene.add(startSphere);
          if (nVerts > 1) {
            const endSphere = new THREE.Mesh(sphereGeo, endMat);
            endSphere.position.set(normPos[(nVerts-1)*3], normPos[(nVerts-1)*3+1], normPos[(nVerts-1)*3+2]);
            scene.add(endSphere);
          }
        } else if (kind === 'polylines') {
          // Multiple polylines – split by counts array
          const counts = geo.counts || [];
          if (counts.length > 0) {
            let offset = 0;
            for (const cnt of counts) {
              const linePos = new Float32Array(cnt * 3);
              const lineCol = new Float32Array(cnt * 3);
              for (let j = 0; j < cnt && (offset + j) < nVerts; j++) {
                const idx = offset + j;
                linePos[j*3] = normPos[idx*3]; linePos[j*3+1] = normPos[idx*3+1]; linePos[j*3+2] = normPos[idx*3+2];
                lineCol[j*3] = colors[idx*3]; lineCol[j*3+1] = colors[idx*3+1]; lineCol[j*3+2] = colors[idx*3+2];
              }
              offset += cnt;
              const lg = new THREE.BufferGeometry();
              lg.setAttribute('position', new THREE.BufferAttribute(linePos, 3));
              lg.setAttribute('color', new THREE.BufferAttribute(lineCol, 3));
              scene.add(new THREE.Line(lg, new THREE.LineBasicMaterial({ vertexColors: true, linewidth: 1 })));
            }
            mesh = new THREE.Group(); // placeholder
          } else {
            const lineMat2 = new THREE.LineBasicMaterial({ vertexColors: true, linewidth: 2 });
            mesh = new THREE.Line(geom3, lineMat2);
          }
        }

        scene.add(mesh);

        // ── Wireframe overlay for surfaces (subsampled for clarity) ──
        if (kind === 'surface' && indices.length > 0) {
          // Show every Nth edge to avoid solid-black look on dense meshes
          const maxWireTriangles = 3000;
          const wireStep = Math.max(1, Math.floor(indices.length / 3 / maxWireTriangles));
          const wireIdx = [];
          for (let t = 0; t < indices.length / 3; t += wireStep) {
            wireIdx.push(indices[t*3], indices[t*3+1], indices[t*3+2]);
          }
          const wireGeo = new THREE.BufferGeometry();
          wireGeo.setAttribute('position', new THREE.BufferAttribute(normPos, 3));
          wireGeo.setIndex(wireIdx);
          const wireMat = new THREE.MeshBasicMaterial({
            color: 0x000000, wireframe: true, transparent: true, opacity: 0.15,
          });
          scene.add(new THREE.Mesh(wireGeo, wireMat));
        }

        // Lighting
        const amb = new THREE.AmbientLight(0xffffff, 0.45);
        scene.add(amb);
        const dir = new THREE.DirectionalLight(0xffffff, 0.9);
        dir.position.set(2, 4, 3);
        scene.add(dir);
        const dir2 = new THREE.DirectionalLight(0x6688cc, 0.35);
        dir2.position.set(-2, -1, -1);
        scene.add(dir2);

        // ── Compute normalized scene bounds ──
        const yMin = (minZ - cz) / extLateral * 2 * zExag;
        const yMax = (maxZ - cz) / extLateral * 2 * zExag;
        const halfW = extX / extLateral;
        const halfD = extY / extLateral;

        // ── Ground grid ──
        const gridSize = Math.max(halfW, halfD) * 2.2;
        const gridHelper = new THREE.GridHelper(gridSize, 12, 0x5566aa, 0x3a3a6e);
        gridHelper.position.y = yMin - 0.08;
        scene.add(gridHelper);

        // ── Bounding box wireframe ──
        const bbW = extX / extLateral * 2;
        const bbH = (yMax - yMin) || 0.1;
        const bbD = extY / extLateral * 2;
        const bbGeo = new THREE.BoxGeometry(bbW, bbH, bbD);
        const bbEdges = new THREE.EdgesGeometry(bbGeo);
        const bbLine = new THREE.LineSegments(bbEdges,
          new THREE.LineBasicMaterial({ color: 0x8899bb, transparent: true, opacity: 0.6 }));
        bbLine.position.y = (yMin + yMax) / 2;
        scene.add(bbLine);

        // ── Vertical scale ticks on the bounding box ──
        const nTicks = 5;
        for (let t = 0; t <= nTicks; t++) {
          const frac = t / nTicks;
          const yPos = yMin + frac * (yMax - yMin);
          // Small horizontal tick line at each level
          const tickGeo = new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(-halfW, yPos, -halfD),
            new THREE.Vector3(-halfW - 0.06, yPos, -halfD - 0.06),
          ]);
          scene.add(new THREE.LineSegments(tickGeo,
            new THREE.LineBasicMaterial({ color: 0xaabbdd })));
        }

        // ── Axis labels (sprites) ──
        function makeLabel(text, pos, color, scale) {
          const c = document.createElement('canvas');
          c.width = 256; c.height = 64;
          const ctx2 = c.getContext('2d');
          ctx2.fillStyle = color || '#aabbcc';
          ctx2.font = 'bold 32px monospace';
          ctx2.textAlign = 'center';
          ctx2.fillText(text, 128, 44);
          const tex = new THREE.CanvasTexture(c);
          const mat = new THREE.SpriteMaterial({ map: tex, transparent: true });
          const spr = new THREE.Sprite(mat);
          spr.position.set(pos[0], pos[1], pos[2]);
          spr.scale.set(scale || 0.3, (scale || 0.3) * 0.35, 1);
          return spr;
        }
        scene.add(makeLabel('X →', [halfW + 0.2, yMin - 0.04, 0], '#ff6666'));
        scene.add(makeLabel('← Y', [0, yMin - 0.04, halfD + 0.2], '#66ff66'));
        scene.add(makeLabel('Depth', [-halfW - 0.25, (yMin + yMax) / 2, -halfD - 0.15], '#6699ff'));
        // Depth value labels
        scene.add(makeLabel(zmin.toFixed(0), [-halfW - 0.2, yMax + 0.04, -halfD - 0.1], '#aaccff', 0.22));
        scene.add(makeLabel(zmax.toFixed(0), [-halfW - 0.2, yMin - 0.01, -halfD - 0.1], '#aaccff', 0.22));

        // Camera
        zoomDist = 2.8;
        let target = new THREE.Vector3(0, 0, 0);
        function updateCamera() {
          camera.position.set(
            target.x + zoomDist * Math.sin(rotY) * Math.cos(rotX),
            target.y + zoomDist * Math.sin(rotX),
            target.z + zoomDist * Math.cos(rotY) * Math.cos(rotX)
          );
          camera.lookAt(target);
        }
        updateCamera();

        // Mouse interaction
        renderer.domElement.addEventListener('contextmenu', e => e.preventDefault());
        renderer.domElement.addEventListener('mousedown', e => {
          isDragging = true; dragBtn = e.button; prevX = e.clientX; prevY = e.clientY;
        });
        window.addEventListener('mouseup', () => { isDragging = false; dragBtn = -1; });
        renderer.domElement.addEventListener('mousemove', e => {
          if (!isDragging) return;
          const dx = e.clientX - prevX, dy = e.clientY - prevY;
          prevX = e.clientX; prevY = e.clientY;
          if (dragBtn === 0) {
            // Left button: orbit
            rotY += dx * 0.008;
            rotX += dy * 0.008;
            rotX = Math.max(-Math.PI/2 + 0.01, Math.min(Math.PI/2 - 0.01, rotX));
          } else if (dragBtn === 2) {
            // Right button: pan
            const panSpeed = zoomDist * 0.002;
            const right = new THREE.Vector3();
            const up = new THREE.Vector3();
            camera.getWorldDirection(new THREE.Vector3());
            right.crossVectors(camera.up, new THREE.Vector3().subVectors(target, camera.position)).normalize();
            up.copy(camera.up);
            target.addScaledVector(right, -dx * panSpeed);
            target.addScaledVector(up, dy * panSpeed);
          }
          updateCamera();
        });
        renderer.domElement.addEventListener('wheel', e => {
          e.preventDefault();
          zoomDist *= e.deltaY > 0 ? 1.1 : 0.9;
          zoomDist = Math.max(0.3, Math.min(30, zoomDist));
          updateCamera();
        }, { passive: false });

        // Touch support (1-finger orbit, 2-finger pinch-zoom)
        let lastPinchDist = 0;
        renderer.domElement.addEventListener('touchstart', e => {
          if (e.touches.length === 1) {
            isDragging = true; dragBtn = 0;
            prevX = e.touches[0].clientX; prevY = e.touches[0].clientY;
          } else if (e.touches.length === 2) {
            isDragging = false;
            const dx = e.touches[1].clientX - e.touches[0].clientX;
            const dy = e.touches[1].clientY - e.touches[0].clientY;
            lastPinchDist = Math.sqrt(dx*dx + dy*dy);
          }
        });
        renderer.domElement.addEventListener('touchmove', e => {
          e.preventDefault();
          if (e.touches.length === 1 && isDragging) {
            const dx = e.touches[0].clientX - prevX, dy = e.touches[0].clientY - prevY;
            rotY += dx * 0.008;
            rotX += dy * 0.008;
            rotX = Math.max(-Math.PI/2 + 0.01, Math.min(Math.PI/2 - 0.01, rotX));
            prevX = e.touches[0].clientX; prevY = e.touches[0].clientY;
            updateCamera();
          } else if (e.touches.length === 2) {
            const dx = e.touches[1].clientX - e.touches[0].clientX;
            const dy = e.touches[1].clientY - e.touches[0].clientY;
            const dist = Math.sqrt(dx*dx + dy*dy);
            if (lastPinchDist > 0) {
              zoomDist *= lastPinchDist / dist;
              zoomDist = Math.max(0.3, Math.min(30, zoomDist));
              updateCamera();
            }
            lastPinchDist = dist;
          }
        }, { passive: false });
        renderer.domElement.addEventListener('touchend', () => { isDragging = false; lastPinchDist = 0; });

        // Keyboard controls
        renderer.domElement.tabIndex = 0;  // make canvas focusable
        renderer.domElement.style.outline = 'none';
        renderer.domElement.focus();
        renderer.domElement.addEventListener('keydown', e => {
          autoRotate = false;
          const rotStep = 0.06, panStep = zoomDist * 0.04, zoomStep = 1.12;
          switch (e.key) {
            case 'ArrowLeft':  rotY -= rotStep; break;
            case 'ArrowRight': rotY += rotStep; break;
            case 'ArrowUp':    rotX = Math.min(Math.PI/2 - 0.01, rotX + rotStep); break;
            case 'ArrowDown':  rotX = Math.max(-Math.PI/2 + 0.01, rotX - rotStep); break;
            case 'w': case 'W': target.y += panStep; break;   // pan up
            case 's': case 'S': target.y -= panStep; break;   // pan down
            case 'a': case 'A': {                              // pan left
              const right = new THREE.Vector3();
              right.crossVectors(camera.up, new THREE.Vector3().subVectors(target, camera.position)).normalize();
              target.addScaledVector(right, panStep); break;
            }
            case 'd': case 'D': {                              // pan right
              const right = new THREE.Vector3();
              right.crossVectors(camera.up, new THREE.Vector3().subVectors(target, camera.position)).normalize();
              target.addScaledVector(right, -panStep); break;
            }
            case '+': case '=': zoomDist = Math.max(0.3, zoomDist / zoomStep); break;   // zoom in
            case '-': case '_': zoomDist = Math.min(30, zoomDist * zoomStep); break;      // zoom out
            case 'r': case 'R':                                // reset view
              rotX = 0.55; rotY = -0.6; zoomDist = 2.8;
              target.set(0, 0, 0); break;
            default: return;  // don't prevent default for other keys
          }
          e.preventDefault();
          updateCamera();
        });

        // Slow auto-rotation on load to demonstrate 3D (stops on first interaction)
        let autoRotate = true;
        const stopAutoRotate = () => { autoRotate = false; };
        renderer.domElement.addEventListener('mousedown', stopAutoRotate, { once: true });
        renderer.domElement.addEventListener('touchstart', stopAutoRotate, { once: true });
        renderer.domElement.addEventListener('wheel', stopAutoRotate, { once: true });

        // Animate
        function animate() {
          _viewer3d.animId = requestAnimationFrame(animate);
          if (autoRotate) {
            rotY += 0.003;
            updateCamera();
          }
          renderer.render(scene, camera);
        }
        _viewer3d = { renderer, scene, camera, controls: { dispose() {} }, animId: 0 };
        animate();

        // Resize
        const ro = new ResizeObserver(() => {
          const w = container.clientWidth, h = container.clientHeight;
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
          renderer.setSize(w, h);
        });
        ro.observe(container);

        // HUD
        const hud = $('viewer3d-hud');
        const kindLabel = { surface: 'Surface', points: 'Point Cloud', trajectory: 'Well Trajectory', markers: 'Well Markers', polylines: 'Polyline Set' };
        hud.innerHTML = `${esc(geo.title)} | ${kindLabel[kind] || kind} | ${nVerts.toLocaleString()} vertices`
          + (zExag > 1.01 ? ` | Z exag: ${zExag.toFixed(1)}×` : '')
          + `<br>Mouse: left-drag orbit · right-drag pan · scroll zoom`
          + `<br>Keys: ←→↑↓ orbit · WASD pan · +/- zoom · R reset`;

        // Legend
        const legendCanvas = $('viewer3d-legend');
        const lctx = legendCanvas.getContext('2d');
        for (let y = 0; y < 200; y++) {
          const t = 1 - y / 199;
          const z = zmin + t * (zmax - zmin);
          const [cr, cg, cb] = colorFromZ(z, zmin, zmax);
          lctx.fillStyle = `rgb(${cr*255|0},${cg*255|0},${cb*255|0})`;
          lctx.fillRect(0, y, 24, 1);
        }
        const labels = $('viewer3d-legend-labels');
        labels.innerHTML = `<span>${zmax.toFixed(1)}</span><span>${((zmin+zmax)/2).toFixed(1)}</span><span>${zmin.toFixed(1)}</span>`;

        grid2dStatus.textContent = `Done - ${nVerts.toLocaleString()} vertices`;
      } catch (e) {
        grid2dStatus.textContent = 'Failed';
        grid2dView.innerHTML = `<p style="color:red;">${esc(e.message)}</p>`;
        console.error(e);
      }
    }

    // Wire up events
    dsSel.addEventListener('change', loadTypes);
    typSel.addEventListener('change', loadObjects);
    $('load-details').addEventListener('click', loadDetails);
    btnTable.addEventListener('click', loadTable);
    btnMap.addEventListener('click', loadMap);
    btn3d.addEventListener('click', load3D);

    // ── GraphQL query panel ──────────────────────────────────────────────
    const gqlEditor = $('gql-editor');
    const gqlVars = $('gql-vars');
    const gqlOutput = $('gql-output');
    const gqlStatus = $('gql-status');
    const gqlPreset = $('gql-preset');
    const gqlRun = $('gql-run');

    const GQL_PRESETS = {
      // ─── Explore ───────────────────────────────────────────────────────
      status: `# Check backend: PostgreSQL version if connected, else REST API info
{
  status
}`,
      dataspaces: `# List all dataspaces (projects) in the store
{
  dataspaces {
    path
    uri
  }
}`,
      types: `# Count of each RESQML type stored in this dataspace
# Drogon has 29 types: IjkGrids, wells, horizons, faults, properties…
{
  resourceTypes(dataspace: "$DS") {
    name
    count
  }
}`,
      objects_grid: `# Browse IjkGrid representations (geocellular grids)
# Drogon has "Geogrid" (927k cells); remote instances may also include "Simgrid" (107k cells)
{
  resqmlObjects(
    dataspace: "$DS"
    typeName: "resqml20.obj_IjkGridRepresentation"
    limit: 10
  ) {
    uuid
    title
    typeName
  }
}`,
      objects_wells: `# Browse wellbore features
# Drogon has 18 wells: exploration (55/33-*) and production (OP*)
{
  resqmlObjects(
    dataspace: "$DS"
    typeName: "resqml20.obj_WellboreFeature"
    limit: 30
  ) {
    uuid
    title
    typeName
  }
}`,

      // ─── Relationships ────────────────────────────────────────────────
      rel_grid_targets: `# TARGETS: what does the Geogrid reference?
# Shows CRS and StratigraphicColumnRank links
{
  objectRelations(
    dataspace: "$DS"
    typeName: "resqml20.obj_IjkGridRepresentation"
    uuid: "2c6de928-7e08-4601-b979-34048bd68c02"
    direction: "targets"
  ) {
    uuid
    name
    typeName
    direction
    contentType
  }
}`,
      rel_grid_sources: `# SOURCES: what references the Geogrid? (attached properties)
# Returns ContinuousProperty and DiscreteProperty objects
{
  objectRelations(
    dataspace: "$DS"
    typeName: "resqml20.obj_IjkGridRepresentation"
    uuid: "2c6de928-7e08-4601-b979-34048bd68c02"
    direction: "sources"
  ) {
    uuid
    name
    typeName
    direction
    contentType
  }
}`,
      rel_well_chain: `# WELL CHAIN: follow WellboreFeature → Interpretation → Trajectory
# Step 1: Get sources of well "55_33-A-1" (finds Interpretation)
# Step 2: Copy the Interp UUID and query its sources (finds Trajectory)
#
# Start here:
{
  objectRelations(
    dataspace: "$DS"
    typeName: "resqml20.obj_WellboreFeature"
    uuid: "50495987-88f4-4e39-95c8-0b2624298c47"
    direction: "sources"
  ) {
    uuid
    name
    typeName
    contentType
  }
}

# Then query the Interpretation's sources to find Trajectory:
# {
#   objectRelations(
#     dataspace: "$DS"
#     typeName: "resqml20.obj_WellboreInterpretation"
#     uuid: "INTERPRETATION-UUID"
#     direction: "sources"
#   ) { uuid name typeName contentType }
# }`,

      // ─── Deep Search (IjkGrid) ───────────────────────────────────────
      deep_poro: `# Deep search: find IjkGrids with Porosity cells > 0.25
# Uses OSDU canonical kind "porosity" (matches PORO, PHIT, etc.)
# Drogon PORO ranges 0–0.36; this finds the high-porosity reservoir cells
# Tip: select multiple dataspaces above to search across all of them
#
# Note: arrayFilter requires PG or ETP backend for cell-value access.
# On REST-only backends, remove arrayFilter to get kind-matched results.
# Alternative: use titleContains: "PORO" to match by raw property name
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_IjkGridRepresentation"
    propertyFilter: {
      kind: "porosity"
      arrayFilter: { threshold: 0.25, operator: GT }
    }
    includeStatistics: true
    limit: 5
  ) {
    backend
    totalScanned
    totalMatched
    queryDescription
    objects {
      uuid
      title
      properties {
        title kind uom
        statistics { count minValue maxValue mean stdDev }
        matchingCells { count total fraction }
      }
    }
  }
}`,
      deep_perm: `# Deep search: IjkGrids with Permeability > 500 mD (high-perm zones)
# Kind filter "permeability" matches titles like "Horizontal Permeability"
# PERMX ranges 0–3830 mD on Geogrid, 0–4278 on Simgrid (if available)
#
# Note: arrayFilter requires PG or ETP backend for cell-value access.
# Alternative: use titleContains: "PERMX" to match only X-direction perm
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_IjkGridRepresentation"
    propertyFilter: {
      kind: "permeability"
      arrayFilter: { threshold: 500.0, operator: GT }
    }
    includeStatistics: true
    limit: 5
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title
      properties {
        title kind
        statistics { count minValue maxValue mean }
        matchingCells { count total fraction }
      }
    }
  }
}`,
      deep_sw: `# Deep search: IjkGrids where water saturation < 0.3
# Uses OSDU canonical kind "saturation" (matches SW, SO)
# Low saturation = oil/gas zone; high = water zone
#
# Note: arrayFilter requires PG or ETP backend for cell-value access.
# Alternative: use titleContains: "SW" to match by raw property name
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_IjkGridRepresentation"
    propertyFilter: {
      kind: "saturation"
      arrayFilter: { threshold: 0.3, operator: LT }
    }
    includeStatistics: true
    limit: 5
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title
      properties {
        title kind
        statistics { count minValue maxValue mean }
        matchingCells { count total fraction }
      }
    }
  }
}`,
      deep_all_props: `# List ALL properties on IjkGrids (no filter, just browse)
# Shows every ContinuousProperty and DiscreteProperty attached
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_IjkGridRepresentation"
    includeStatistics: true
    limit: 2
  ) {
    backend totalScanned totalMatched
    objects {
      uuid title
      properties {
        title kind uom
        statistics { count minValue maxValue mean }
      }
    }
  }
}`,

      // ─── Deep Search (Surfaces / Grid2D) ──────────────────────────────
      deep_grid2d_horizons: `# Grid2D surfaces → which horizon / boundary feature?
# Uses includeRelations to traverse the RESQML object graph:
#   Grid2D → target HorizonInterpretation → target GeneticBoundaryFeature
# Each surface points to exactly one horizon interpretation.
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_Grid2dRepresentation"
    includeRelations: true
    includeStatistics: false
    limit: 20
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title
      relations {
        uuid name typeName direction
      }
    }
  }
}`,
      deep_grid2d_arrays: `# Grid2D surface array statistics
# Grid2D nodes store the Z-values (depth or time) directly as arrays
# This shows the DS_interp surface for BaseVolantis
{
  objectArrays(
    dataspace: "$DS"
    typeName: "resqml20.obj_Grid2dRepresentation"
    uuid: "02a9d0b6-1f7c-4553-994b-5060cd725d6d"
    includeStatistics: true
    includeSampleValues: true
    sampleSize: 10
  ) {
    path
    dataType
    dimensions
    totalElements
    statistics { count minValue maxValue mean stdDev }
    sampleValues
  }
}`,

      // ─── Deep Search (Horizons) ───────────────────────────────────────
      deep_horizon_grid2d: `# Horizon → which Grid2D surfaces and representations?
# The reverse of deep_grid2d_horizons: start from horizons,
# find all Grid2Ds, PointSets, WellMarkers that reference them.
# Filter sources by typeName in results to distinguish surface types.
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_HorizonInterpretation"
    includeRelations: true
    includeStatistics: false
    limit: 10
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title
      relations {
        uuid name typeName direction
      }
    }
  }
}
# Drogon horizons:
#   TopVolantis, BaseVolantis, TopTherys, TopVolon, MSL, BaseVelmodel`,

      // ─── Stratigraphy (column hierarchy + horizon chain) ──────────────
      strat_column: `# Stratigraphic column hierarchy with relations
# Drogon has one strat column: "Stratigraphic Column (Geogrid)"
# Traverses: StratColumn → ColumnRankInterpretation → UnitInterpretations
#            + HorizonInterpretations linking units to surfaces
#
# The RDDMS column matches the catalog "Drogon-Volve Lithostratigraphy"
# via ResourceURI/UUID cross-references on StratigraphicUnitInterpretation.
{
  col: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_StratigraphicColumn"
    includeRelations: true
    limit: 5
  ) {
    backend totalScanned totalMatched
    objects {
      uuid title
      relations { uuid name typeName direction }
    }
  }
  rank: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_StratigraphicColumnRankInterpretation"
    includeRelations: true
    limit: 5
  ) {
    totalMatched
    objects {
      uuid title
      relations { uuid name typeName direction }
    }
  }
  units: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_StratigraphicUnitInterpretation"
    includeRelations: true
    limit: 20
  ) {
    totalMatched
    objects {
      uuid title
      relations { uuid name typeName direction }
    }
  }
}`,
      strat_horizons: `# Horizon → feature → surface chain (Representation → Interpretation → Feature)
# Shows the RESQML hierarchy for each horizon:
#   direction=target → GeneticBoundaryFeature (the geological concept)
#   direction=source → Grid2D / PointSet / WellboreMarkerFrame (representations)
#
# 4 horizons are stratigraphic (TopVolantis, TopTherys, TopVolon, BaseVolantis)
# 2 are technical boundaries (MSL, BaseVelmodel)
{
  horizons: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_HorizonInterpretation"
    includeRelations: true
    limit: 10
  ) {
    backend totalMatched
    objects {
      uuid title
      relations { uuid name typeName direction }
    }
  }
  features: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_GeneticBoundaryFeature"
    includeRelations: true
    limit: 10
  ) {
    totalMatched
    objects {
      uuid title
      relations { uuid name typeName direction }
    }
  }
}`,
      strat_boundaries: `# All boundary features - stratigraphic + tectonic (faults)
# GeneticBoundaryFeature = horizons (strat or technical datum)
# TectonicBoundaryFeature = faults (F1–F6 in Drogon)
# Stratigraphic boundaries have StratigraphicUnitFeature relations;
# technical ones (MSL, BaseVelmodel) and faults do not.
{
  genetic: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_GeneticBoundaryFeature"
    includeRelations: true
    limit: 10
  ) {
    totalMatched
    objects {
      uuid title
      relations { uuid name typeName direction }
    }
  }
  tectonic: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_TectonicBoundaryFeature"
    includeRelations: true
    limit: 10
  ) {
    totalMatched
    objects {
      uuid title
      relations { uuid name typeName direction }
    }
  }
  faults: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_FaultInterpretation"
    includeRelations: true
    limit: 10
  ) {
    totalMatched
    objects {
      uuid title
      relations { uuid name typeName direction }
    }
  }
}`,
      xref_strat_horizons: `# FEDERATED: Catalog horizon WPCs ↔ RDDMS object graph
#
# The gen_markers_strat_drogon.py script creates HorizonInterpretation
# WPC records with ResourceURI/UUID matching the RDDMS objects.
# This query finds them in both systems and enriches with RDDMS relations:
#   catalog metadata (OSDU id, kind) + RDDMS graph (Grid2D surfaces, features)
#
# relationFilter keeps only the interesting types (surfaces, features, rank).
# Without it you also get 9 WellboreMarkerFrame + Activity per horizon.
# To see ALL relations, remove the relationFilter parameter.
{
  federatedSearch(
    text: "*"
    kind: "osdu:wks:work-product-component--HorizonInterpretation:*"
    dataspaces: $DS_LIST
    typeName: "resqml20.obj_HorizonInterpretation"
    searchCatalog: true
    searchRddms: true
    includeRelations: true
    relationFilter: ["Grid2d", "PointSet", "Boundary", "Stratigraphic", "TriangulatedSet"]
    limit: 10
  ) {
    totalCatalog totalLocalRddms totalMerged sources
    hits {
      uuid title dataspace
      foundInCatalog foundInLocalRddms
      osduId osduKind
      relations {
        uuid name typeName direction
      }
    }
  }
}`,

      // ─── Deep Search (Well Logs) ──────────────────────────────────────
      deep_well_phit: `# Wells with Porosity > 0.25
# Uses OSDU canonical kind "porosity" (matches PORO, PHIT log curves)
# Searches WellboreFrameRepresentations for attached log properties
#
# Alternative: use titleContains: "PHIT" to match only total porosity
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_WellboreFrameRepresentation"
    propertyFilter: {
      kind: "porosity"
      arrayFilter: { threshold: 0.25, operator: GT }
    }
    includeStatistics: true
    limit: 10
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title
      properties {
        title kind
        statistics { count minValue maxValue mean }
        matchingCells { count total fraction }
      }
    }
  }
}`,
      deep_well_perm: `# Wells with Permeability > 100 mD
# Kind filter "permeability" matches titles like "KLOGH", "PERM*"
# KLOGH is the log-derived horizontal permeability
#
# Alternative: use titleContains: "KLOGH" to match only log permeability
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_WellboreFrameRepresentation"
    propertyFilter: {
      kind: "permeability"
      arrayFilter: { threshold: 100.0, operator: GT }
    }
    includeStatistics: true
    limit: 10
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title
      properties {
        title kind
        statistics { count minValue maxValue mean }
        matchingCells { count total fraction }
      }
    }
  }
}`,
      deep_well_all: `# All log properties on wells (browse curves available)
# Drogon wells have: PHIT, KLOGH, VSH, DENS, AI, VP, VS, Sw, Facies…
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_WellboreFrameRepresentation"
    includeStatistics: true
    limit: 3
  ) {
    backend totalScanned totalMatched
    objects {
      uuid title
      properties {
        title kind uom
        statistics { count minValue maxValue mean }
      }
    }
  }
}`,

      // ─── Numerical Data ───────────────────────────────────────────────
      array_stats: `# Get array metadata and statistics for the Geogrid
# (geometry pillars, cell connectivity, etc.)
{
  objectArrays(
    dataspace: "$DS"
    typeName: "resqml20.obj_IjkGridRepresentation"
    uuid: "2c6de928-7e08-4601-b979-34048bd68c02"
    includeStatistics: true
  ) {
    path
    dataType
    dimensions
    totalElements
    statistics {
      count minValue maxValue mean stdDev nanCount
    }
  }
}`,
      array_sample: `# Read sample values from Geogrid arrays (first 20 elements)
{
  objectArrays(
    dataspace: "$DS"
    typeName: "resqml20.obj_IjkGridRepresentation"
    uuid: "2c6de928-7e08-4601-b979-34048bd68c02"
    includeStatistics: true
    includeSampleValues: true
    sampleSize: 20
  ) {
    path
    dimensions
    totalElements
    statistics { minValue maxValue mean stdDev }
    sampleValues
  }
}`,
      // ─── Federated (Catalog + Local RDDMS + Remote RDDMS) ─────────────────
      fed_local: `# Search local RDDMS only (un-indexed PG data)
# Skips OSDU catalog and remote RDDMS
{
  federatedSearch(
    text: "*"
    searchCatalog: false
    searchRddms: true
    searchRemoteRddms: false
    dataspaces: $DS_LIST
    limit: 20
  ) {
    totalLocalRddms totalMerged sources queryDescription
    hits {
      uuid title typeName dataspace
      foundInLocalRddms
    }
  }
}`,
      fed_catalog: `# Search OSDU catalog only (metadata level)
# Uses project name from the selected dataspace to scope results.
# With text: "*" + wildcard kind the entire OSDU instance is searched
# (>1M records) – change "$DS_NAME" to "*" only if you want that.
{
  federatedSearch(
    text: "$DS_NAME"
    kind: "osdu:wks:work-product-component--*:*"
    dataspaces: $DS_LIST
    searchCatalog: true
    searchRddms: false
    searchRemoteRddms: false
    limit: 20
  ) {
    totalCatalog totalMerged sources queryDescription
    hits {
      uuid title typeName dataspace
      foundInCatalog
      osduId osduKind
    }
  }
}`,
      fed_both: `# Search ALL THREE: catalog + local PG + remote RDDMS
# Results merged by UUID – flags show where each was found
# Uses project name to scope catalog (wildcard kind + text:"*" = >1M hits)
{
  federatedSearch(
    text: "$DS_NAME"
    kind: "osdu:wks:work-product-component--*:*"
    dataspaces: $DS_LIST
    searchCatalog: true
    searchRddms: true
    searchRemoteRddms: true
    limit: 20
  ) {
    totalCatalog totalLocalRddms totalRemoteRddms totalRddms totalMerged
    sources queryDescription
    hits {
      uuid title typeName dataspace
      foundInCatalog foundInLocalRddms foundInRemoteRddms
      osduId osduKind
    }
  }
}`,
      fed_enrich: `# Full pipeline: all sources + relations + property stats
{
  federatedSearch(
    text: "*"
    dataspaces: $DS_LIST
    typeName: "resqml20.obj_IjkGridRepresentation"
    searchCatalog: true
    searchRddms: true
    searchRemoteRddms: true
    includeRelations: true
    includeProperties: true
    includeStatistics: true
    limit: 5
  ) {
    totalCatalog totalLocalRddms totalRemoteRddms totalMerged sources
    hits {
      uuid title typeName dataspace
      foundInCatalog foundInLocalRddms foundInRemoteRddms
      relations { uuid name typeName direction }
      properties {
        title kind
        statistics { count minValue maxValue mean }
      }
    }
  }
}`,
      // ─── Cross-System Queries (only answerable via GraphQL) ────────────────
      // These demonstrate the unique value of federated GraphQL:
      // correlating OSDU catalog metadata with RDDMS object-graph data
      // using shared UUIDs across systems.
      xref_grid_props: `# CROSS-SYSTEM: Find grids indexed in OSDU catalog,
# then discover their attached properties from RDDMS.
#
# Why only GraphQL can do this:
#   OSDU Search knows the grid exists (WPC record) but has NO property data.
#   RDDMS has the properties (porosity, permeability) but isn't searchable by OSDU kind.
#   GraphQL bridges the gap: catalog hit → UUID → RDDMS graph → properties.
{
  federatedSearch(
    text: "*"
    kind: "osdu:wks:work-product-component--IjkGridRepresentation:*"
    dataspaces: $DS_LIST
    typeName: "resqml20.obj_IjkGridRepresentation"
    searchCatalog: true
    searchRddms: true
    includeRelations: true
    includeProperties: true
    includeStatistics: true
    limit: 5
  ) {
    totalCatalog totalLocalRddms totalMerged sources
    hits {
      uuid title typeName dataspace
      foundInCatalog foundInLocalRddms
      osduId osduKind
      # Relations from RDDMS graph (CRS, stratigraphy, features)
      relations { uuid name typeName direction }
      # Properties from RDDMS (porosity, perm, saturation)
      properties {
        title kind uom
        statistics { count minValue maxValue mean stdDev }
      }
    }
  }
}`,
      xref_horizon_reps: `# CROSS-SYSTEM: Horizons known in catalog → their RDDMS representations
#
# Requires harmonized catalog data: run gen_markers_strat_drogon.py then
# ingest manifest_litho_strat_drogon.json to create HorizonInterpretation WPCs.
#
# Why only GraphQL can do this:
#   Catalog knows HorizonInterpretation records exist (OSDU kind + metadata).
#   But which Grid2D surfaces or triangulated meshes REFERENCE that horizon?
#   Only RDDMS object graph (sources = reverse edges) knows this.
#
# relationFilter: ["Grid2d", "PointSet", "TriangulatedSet"] keeps only
# surface representations.  Remove it to also see WellboreMarkerFrame (9 per
# horizon) and Activity.  Activity is always stripped by default.
#
# Expected results (4 strat + 2 technical):
#   TopVolantis  → 4 Grid2D, 6 PointSet   [strat]
#   BaseVolantis → 4 Grid2D, 6 PointSet   [strat]
#   TopTherys    → 1 Grid2D, 2 PointSet   [strat]
#   TopVolon     → 1 Grid2D, 2 PointSet   [strat]
#   MSL          → 3 Grid2D               [technical]
#   BaseVelmodel → 2 Grid2D               [technical]
{
  federatedSearch(
    text: "*"
    kind: "osdu:wks:work-product-component--HorizonInterpretation:*"
    dataspaces: $DS_LIST
    typeName: "resqml20.obj_HorizonInterpretation"
    searchCatalog: true
    searchRddms: true
    includeRelations: true
    relationFilter: ["Grid2d", "PointSet", "TriangulatedSet"]
    limit: 10
  ) {
    totalCatalog totalLocalRddms totalMerged sources
    hits {
      uuid title dataspace
      foundInCatalog foundInLocalRddms
      osduId osduKind
      # Which representations point TO this horizon? (Grid2D, TriangulatedSet, etc.)
      relations {
        uuid name typeName direction
      }
    }
  }
}`,
      xref_orphan_rddms: `# CROSS-SYSTEM: Find RDDMS objects NOT indexed in OSDU catalog
#
# Why only GraphQL can do this:
#   Catalog Search only returns what's been ingested to OSDU.
#   RDDMS may contain objects that were loaded via ETP/EPC import
#   but never registered as OSDU WPC records.
#   This query finds them: foundInLocalRddms=true AND foundInCatalog=false.
#   Useful for: data governance, re-ingestion planning, gap analysis.
#
# text: "$DS_NAME" scopes catalog to this project.
# Change to "*" to compare against the entire OSDU instance (slow, >1M hits).
{
  federatedSearch(
    text: "$DS_NAME"
    kind: "osdu:wks:work-product-component--*:*"
    dataspaces: $DS_LIST
    searchCatalog: true
    searchRddms: true
    searchRemoteRddms: false
    limit: 100
  ) {
    totalCatalog totalLocalRddms totalMerged sources
    queryDescription
    hits {
      uuid title typeName dataspace
      foundInCatalog foundInLocalRddms
      osduId
    }
  }
}
# ↑ After running: filter results where foundInCatalog=false
#   (those are RDDMS-only orphans not visible to catalog search)`,
      xref_catalog_only: `# CROSS-SYSTEM: Catalog records that DON'T exist in RDDMS
#
# Why only GraphQL can do this:
#   If catalog ingestion created WPC records from a manifest
#   but the actual RESQML data was never loaded into RDDMS,
#   those records are "metadata ghosts" - searchable but not queryable.
#   This finds them: foundInCatalog=true AND foundInLocalRddms=false.
#   Useful for: verifying ingestion completeness, finding broken links.
#
# text: "$DS_NAME" scopes catalog to this project.
# Change to "*" to scan the entire OSDU instance (slow, >1M hits).
{
  federatedSearch(
    text: "$DS_NAME"
    kind: "osdu:wks:work-product-component--*:*"
    dataspaces: $DS_LIST
    searchCatalog: true
    searchRddms: true
    searchRemoteRddms: false
    limit: 100
  ) {
    totalCatalog totalLocalRddms totalMerged sources
    queryDescription
    hits {
      uuid title typeName dataspace
      foundInCatalog foundInLocalRddms
      osduId osduKind
    }
  }
}
# ↑ After running: filter results where foundInLocalRddms=false
#   (those are catalog-only records with no RDDMS backing)`,
      xref_well_chain: `# CROSS-SYSTEM: Trace a well from catalog to full RDDMS graph
#
# Why only GraphQL can do this:
#   OSDU catalog stores flat WPC records - you can search for wells.
#   But the Feature → Interpretation → Trajectory → FrameRepresentation
#   chain lives in RDDMS only. Catalog has no knowledge of these edges.
#   GraphQL finds the well in catalog, then traverses the RDDMS graph
#   to reveal the full subsurface object hierarchy.
{
  federatedSearch(
    text: "*"
    kind: "osdu:wks:work-product-component--WellboreTrajectory:*"
    dataspaces: $DS_LIST
    typeName: "resqml20.obj_WellboreFeature"
    searchCatalog: true
    searchRddms: true
    includeRelations: true
    includeProperties: true
    limit: 5
  ) {
    totalCatalog totalLocalRddms totalMerged sources
    hits {
      uuid title typeName dataspace
      foundInCatalog foundInLocalRddms
      osduId osduKind
      # Graph edges: Interpretation → Trajectory → FrameRep → logs
      relations {
        uuid name typeName direction
      }
      # Any attached array properties (deviation surveys, logs)
      properties {
        title kind uom
        statistics { count minValue maxValue mean }
      }
    }
  }
}`,
      xref_grid_full: `# CROSS-SYSTEM: Full grid lineage - catalog metadata + RDDMS graph + array stats
#
# The ultimate cross-system query that no single API can answer:
#   1. OSDU catalog → finds the grid (WPC record with OSDU id, kind, version)
#   2. UUID match → confirms it exists in RDDMS (data integrity check)
#   3. Graph traversal → finds CRS, stratigraphy, interpretation links
#   4. Property discovery → finds porosity, permeability, saturation arrays
#   5. Array statistics → computes min/max/mean without downloading data
#
# This single query replaces: 1 catalog search + N RDDMS REST calls +
# N property lookups + N array stat computations.
{
  federatedSearch(
    text: "*"
    kind: "osdu:wks:work-product-component--IjkGridRepresentation:*"
    dataspaces: $DS_LIST
    typeName: "resqml20.obj_IjkGridRepresentation"
    searchCatalog: true
    searchRddms: true
    searchRemoteRddms: true
    includeRelations: true
    includeProperties: true
    includeStatistics: true
    propertyFilter: { kind: "porosity", arrayFilter: { threshold: 0.1, operator: GT } }
    limit: 3
  ) {
    totalCatalog totalLocalRddms totalRemoteRddms totalMerged
    sources queryDescription
    hits {
      uuid title typeName dataspace
      foundInCatalog foundInLocalRddms foundInRemoteRddms
      osduId osduKind
      relations { uuid name typeName direction }
      properties {
        uuid title kind uom
        statistics { count minValue maxValue mean stdDev }
        matchingCells { count total fraction }
      }
    }
  }
}`
    };

    function gqlSelectedDataspaces() {
      return Array.from(dsSel.selectedOptions).map(o => o.value);
    }

    function gqlCurrentDs() {
      // Returns first selected for single-dataspace presets
      const sel = gqlSelectedDataspaces();
      return sel.length > 0 ? sel[0] : 'maap/drogon';
    }

    function gqlDataspacesArg() {
      // Returns the GraphQL argument string for dataspaces
      const sel = gqlSelectedDataspaces();
      if (sel.length <= 1) {
        return `dataspace: "${sel[0] || gqlCurrentDs()}"`;
      }
      const items = sel.map(d => `"${d}"`).join(', ');
      return `dataspaces: [${items}]`;
    }

    function gqlDataspacesList() {
      // Returns the JSON list string for dataspaces (federated search)
      const sel = gqlSelectedDataspaces();
      const ds = sel.length > 0 ? sel : [gqlCurrentDs()];
      return `[${ds.map(d => `"${d}"`).join(', ')}]`;
    }

    function gqlLoadPreset() {
      const key = gqlPreset.value;
      const tpl = GQL_PRESETS[key] || '';
      // For deep search presets, use dataspaces (multi) arg; for others, use single dataspace
      const isDeep = key.startsWith('deep_');
      // $DS_NAME = project name extracted from the dataspace path
      // e.g. "maap/drogon" → "Drogon", "user/johan-sverdrup" → "Johan-sverdrup"
      const dsName = (gqlCurrentDs().split('/').pop() || 'Drogon').replace(/^\w/, c => c.toUpperCase());
      let query = tpl.replace(/\$DS_ARG/g, gqlDataspacesArg());
      query = query.replace(/\$DS_LIST/g, gqlDataspacesList());
      query = query.replace(/\$DS_NAME/g, dsName);
      query = query.replace(/\$DS/g, gqlCurrentDs());
      gqlEditor.value = query;
    }

    gqlPreset.addEventListener('change', gqlLoadPreset);
    // Re-inject dataspaces into preset when selection changes
    dsSel.addEventListener('change', gqlLoadPreset);
    // Initialize with first preset
    gqlLoadPreset();

    // Auto-check backend status and update badge
    (async function checkGqlBackend() {
      const badge = document.getElementById('gql-backend-badge');
      try {
        const resp = await fetch('/api/graphql/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: '{ status }' }),
        });
        const data = await resp.json();
        const st = (data.data && data.data.status) || '';
        if (st.startsWith('PostgreSQL direct')) {
          badge.textContent = 'PostgreSQL';
          badge.style.background = '#dff6dd';
          badge.style.color = '#107c10';
          // Pre-fill dataspaces from local PG – merge with existing remote items
          try {
            const dsResp = await fetch('/api/graphql/query', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ query: '{ dataspaces { path } }' }),
            });
            const dsData = await dsResp.json();
            const pgDs = (dsData.data && dsData.data.dataspaces) || [];
            if (pgDs.length) {
              // Tag PG dataspaces as local; keep existing remote items
              const localPaths = new Set(pgDs.map(d => d.path));
              const localItems = pgDs.map(d => ({ path: d.path, uri: d.uri || '', source: 'local' }));
              // Keep remote items that aren't duplicates of local
              const remoteItems = _allDsItems.filter(x => !localPaths.has(x.path) && x.source !== 'local');
              // Re-tag remote items that lack a source
              remoteItems.forEach(x => { if (!x.source) x.source = 'remote'; });
              _allDsItems = [...localItems, ...remoteItems];
              _applyDsFilter();
              // Select all local PG dataspaces by default
              Array.from(dsSel.options).forEach(o => {
                o.selected = localPaths.has(o.value);
              });
              gqlLoadPreset();
              // Trigger loadTypes with first dataspace
              loadTypes();
            }
          } catch (_) { /* ignore – dataspaces already populated from REST */ }
        } else if (st.includes('REST')) {
          badge.textContent = 'REST API';
          badge.style.background = '#deecf9';
          badge.style.color = '#004578';
        } else {
          badge.textContent = 'connected';
          badge.style.background = '#dff6dd';
          badge.style.color = '#107c10';
        }
      } catch (e) {
        badge.textContent = 'offline';
        badge.style.background = '#fde7e9';
        badge.style.color = '#a80000';
      }
    })();

    // Update $DS placeholder when dataspace changes
    dsSel.addEventListener('change', () => {
      const current = gqlEditor.value;
      if (current.includes('dataspace:')) {
        // smart-replace the dataspace argument
        gqlEditor.value = current.replace(
          /dataspace:\s*"[^"]*"/g,
          `dataspace: "${gqlCurrentDs()}"`
        );
      }
    });

    async function runGraphQLQuery() {
      const query = gqlEditor.value.trim();
      if (!query) { gqlStatus.textContent = 'Empty query'; return; }

      let variables = {};
      try {
        const vt = gqlVars.value.trim();
        if (vt && vt !== '{}') variables = JSON.parse(vt);
      } catch (e) {
        gqlStatus.textContent = 'Invalid variables JSON';
        return;
      }

      gqlStatus.textContent = 'Running…';
      gqlOutput.textContent = '';

      try {
        const resp = await fetch('/api/graphql/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query, variables }),
        });
        const data = await resp.json();
        gqlOutput.textContent = JSON.stringify(data, null, 2);
        autoSizeOutput();
        if (data.errors && data.errors.length) {
          gqlStatus.textContent = `Done (${data.errors.length} error(s))`;
        } else {
          const count = data.data ? Object.keys(data.data).length : 0;
          gqlStatus.textContent = `Done – ${count} field(s) returned`;
        }
        // Try to render graph visualisation
        renderMermaidFromResponse(data);

        // Check for 3D-renderable objects and show button in result area
        const renderableObjs = extractRenderableObjects(data);
        const existing3dBtn = document.getElementById('gql3d-advanced-trigger-wrap');
        if (existing3dBtn) existing3dBtn.remove();
        if (renderableObjs.length > 0) {
          const wrap = document.createElement('div');
          wrap.id = 'gql3d-advanced-trigger-wrap';
          wrap.style.cssText = 'margin:8px 0;display:flex;align-items:center;gap:10px;';
          wrap.innerHTML = `<button class="btn-show3d-results" id="gql3d-adv-trigger">
            <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            Show 3D Results (${renderableObjs.length})
          </button>
          <span style="font-size:12px;color:#605e5c;">${renderableObjs.length} renderable object${renderableObjs.length > 1 ? 's' : ''}</span>`;
          $('gql-result').parentNode.insertBefore(wrap, $('gql-result'));
          wrap.querySelector('#gql3d-adv-trigger').addEventListener('click', () => openGql3DPopup(renderableObjs));
        }
      } catch (e) {
        gqlStatus.textContent = 'Request failed';
        gqlOutput.textContent = e.message;
        autoSizeOutput();
      }
    }

    // Auto-resize editor textarea to fit content (min 4, max 24 rows)
    function autoSizeEditor() {
      const lines = gqlEditor.value.split('\n').length;
      gqlEditor.rows = Math.max(4, Math.min(lines + 1, 24));
    }
    gqlEditor.addEventListener('input', autoSizeEditor);
    // Also size on preset load
    const _origPreset = gqlPreset.onchange;
    gqlPreset.addEventListener('change', () => setTimeout(autoSizeEditor, 0));
    autoSizeEditor();

    // Shrink/grow output container based on content
    function autoSizeOutput() {
      const el = document.getElementById('gql-result');
      const pre = document.getElementById('gql-output');
      // reset to auto to measure
      el.style.maxHeight = 'none';
      const h = pre.scrollHeight + 20;
      // cap at 70vh
      const cap = window.innerHeight * 0.7;
      el.style.maxHeight = (h > cap ? cap : h) + 'px';
    }

    gqlRun.addEventListener('click', runGraphQLQuery);
    // Ctrl+Enter to run
    gqlEditor.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        runGraphQLQuery();
      }
    });

    // ── Saved GraphQL queries ─────────────────────────────────────────────────
    (function() {
      const savedSel = $('gql-saved-select');
      const saveBtn = $('gql-save-query');
      const delBtn = $('gql-delete-query');
      if (!savedSel) return;

      // Load saved queries on page load
      fetch('/api/queries?source=graphql')
        .then(r => r.json())
        .then(function(list) {
          (list || []).forEach(function(sq) {
            const opt = document.createElement('option');
            opt.value = sq.id;
            opt.dataset.query = sq.query;
            opt.textContent = sq.name;
            savedSel.appendChild(opt);
          });
        })
        .catch(function() {});

      // Apply saved query on select
      savedSel.addEventListener('change', function() {
        const opt = savedSel.options[savedSel.selectedIndex];
        if (!opt || !opt.value) { delBtn.style.display = 'none'; return; }
        const raw = opt.dataset.query || '';
        // query may contain vars separated by \n---VARS---\n
        const sep = '\n---VARS---\n';
        const idx = raw.indexOf(sep);
        if (idx >= 0) {
          gqlEditor.value = raw.substring(0, idx);
          gqlVars.value = raw.substring(idx + sep.length);
        } else {
          gqlEditor.value = raw;
        }
        delBtn.style.display = 'inline-block';
      });

      // Delete
      if (delBtn) {
        delBtn.addEventListener('click', function() {
          const qid = savedSel.value;
          if (!qid) return;
          if (!confirm('Delete this saved query?')) return;
          fetch('/api/queries/' + qid, { method: 'DELETE' })
            .then(r => r.json())
            .then(function() {
              for (let i = savedSel.options.length - 1; i >= 0; i--) {
                if (savedSel.options[i].value === qid) savedSel.remove(i);
              }
              savedSel.value = '';
              delBtn.style.display = 'none';
            });
        });
      }

      // Save
      if (saveBtn) {
        saveBtn.addEventListener('click', function() {
          const queryText = (gqlEditor.value || '').trim();
          if (!queryText) return;
          const varsText = (gqlVars.value || '{ }').trim();
          // Build a default name from the first comment or first line
          const firstLine = queryText.split('\n').find(l => l.trim()) || 'query';
          const defaultName = firstLine.replace(/^[#{}\s]+/, '').substring(0, 50).trim() || 'query';
          const name = prompt('Name for this query:', defaultName);
          if (!name) return;
          // Pack query + vars together
          const packed = varsText && varsText !== '{ }' && varsText !== '{}'
            ? queryText + '\n---VARS---\n' + varsText
            : queryText;
          fetch('/api/queries', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, kind: '__graphql__', query: packed })
          })
            .then(r => r.json())
            .then(function(data) {
              if (data.id) {
                const opt = document.createElement('option');
                opt.value = data.id;
                opt.dataset.query = data.query;
                opt.textContent = data.name;
                if (savedSel.options.length > 1) {
                  savedSel.insertBefore(opt, savedSel.options[1]);
                } else {
                  savedSel.appendChild(opt);
                }
                savedSel.value = data.id;
                delBtn.style.display = 'inline-block';
              }
            });
        });
      }
    })();

    // ── Graph visualisation (Mermaid) ─────────────────────────────────────────
    const gqlTabJson = $('gql-tab-json');
    const gqlTabGraph = $('gql-tab-graph');
    const gqlGraphDiv = $('gql-graph');
    const gqlResultDiv = $('gql-result');
    const gqlMermaid = $('gql-mermaid');
    const gqlGraphHint = $('gql-graph-hint');
    let _lastMermaidCode = '';
    let _mermaidRenderCount = 0;

    gqlTabJson.addEventListener('click', () => {
      gqlResultDiv.style.display = '';
      gqlGraphDiv.style.display = 'none';
      gqlTabJson.style.background = 'transparent'; gqlTabJson.style.color = 'var(--eq-red, #FF1243)'; gqlTabJson.style.fontWeight = '600'; gqlTabJson.style.borderBottom = '2px solid var(--eq-red, #FF1243)';
      gqlTabGraph.style.background = 'transparent'; gqlTabGraph.style.color = '#605e5c'; gqlTabGraph.style.fontWeight = '500'; gqlTabGraph.style.borderBottom = '2px solid transparent';
      gqlGraphHint.style.display = 'none';
    });
    gqlTabGraph.addEventListener('click', () => {
      if (!_lastMermaidCode) { gqlGraphHint.textContent = 'No graph data in last response'; gqlGraphHint.style.display = ''; return; }
      gqlResultDiv.style.display = 'none';
      gqlGraphDiv.style.display = '';
      gqlTabGraph.style.background = 'transparent'; gqlTabGraph.style.color = 'var(--eq-red, #FF1243)'; gqlTabGraph.style.fontWeight = '600'; gqlTabGraph.style.borderBottom = '2px solid var(--eq-red, #FF1243)';
      gqlTabJson.style.background = 'transparent'; gqlTabJson.style.color = '#605e5c'; gqlTabJson.style.fontWeight = '500'; gqlTabJson.style.borderBottom = '2px solid transparent';
      gqlGraphHint.style.display = '';
    });

    function _sanitize(s) { return (s || '').replace(/["<>]/g, '').replace(/[\[\](){}#&;]/g, ' ').substring(0, 60); }
    function _shortType(t) { return (t || '').replace(/^resqml\d+\.obj_/, '').replace(/application.*\./g, ''); }
    function _nodeId(uuid) { return 'n' + (uuid || 'x').replace(/[^a-zA-Z0-9]/g, '').substring(0, 12); }

    function buildMermaidFromRelations(data) {
      // object_relations response
      const rels = data.data && data.data.objectRelations;
      if (!rels || !rels.length) return '';
      const lines = ['graph LR'];
      const centerId = 'center';
      lines.push(`  ${centerId}["Query Object"]`);
      rels.forEach((r, i) => {
        const nid = _nodeId(r.uuid) + i;
        const label = _sanitize(r.name) || _shortType(r.typeName || r.type_name);
        const stype = _shortType(r.typeName || r.type_name);
        lines.push(`  ${nid}["${label}<br/><small>${stype}</small>"]`);
        if (r.direction === 'target') {
          lines.push(`  ${centerId} -->|target| ${nid}`);
        } else {
          lines.push(`  ${nid} -->|source| ${centerId}`);
        }
      });
      return lines.join('\n');
    }

    function buildMermaidFromDeepSearch(data) {
      // deep_search response
      const ds = data.data && data.data.deepSearch;
      if (!ds || !ds.objects || !ds.objects.length) return '';
      const lines = ['graph TD'];
      ds.objects.forEach((obj, oi) => {
        const oid = _nodeId(obj.uuid) + oi;
        const oLabel = _sanitize(obj.title) || obj.uuid.substring(0, 8);
        const oType = _shortType(obj.typeName || obj.type_name);
        lines.push(`  ${oid}["${oLabel}<br/><small>${oType}</small>"]`);
        if (obj.properties && obj.properties.length) {
          obj.properties.forEach((p, pi) => {
            const pid = oid + 'p' + pi;
            const pLabel = _sanitize(p.title) || p.uuid.substring(0, 8);
            const kind = p.kind || '';
            const stats = p.statistics ? `min=${p.statistics.minValue?.toFixed(2) ?? '?'} max=${p.statistics.maxValue?.toFixed(2) ?? '?'}` : '';
            lines.push(`  ${pid}(["${pLabel}<br/><small>${kind} ${stats}</small>"])`);
            lines.push(`  ${pid} -.->|property| ${oid}`);
          });
        }
      });
      return lines.join('\n');
    }

    function buildMermaidFromResqmlObjects(data) {
      // resqml_objects or dataspaces list
      const objs = data.data && (data.data.resqmlObjects || data.data.resourceTypes);
      if (!objs || !objs.length || objs.length > 30) return '';
      if (data.data.resourceTypes) {
        // Type summary as a simple graph
        const lines = ['graph LR'];
        lines.push('  DS["Dataspace"]');
        objs.forEach((t, i) => {
          const nid = 'type' + i;
          lines.push(`  ${nid}["${_shortType(t.name)}<br/><small>${t.count} objects</small>"]`);
          lines.push(`  DS --- ${nid}`);
        });
        return lines.join('\n');
      }
      return '';
    }

    async function renderMermaidFromResponse(data) {
      if (!data || !data.data) { _lastMermaidCode = ''; return; }
      let code = buildMermaidFromRelations(data)
               || buildMermaidFromDeepSearch(data)
               || buildMermaidFromResqmlObjects(data);
      _lastMermaidCode = code;
      if (!code) return;
      // Render into the hidden div (pre-render so switching is instant)
      try {
        _mermaidRenderCount++;
        const id = 'gql-mmd-' + _mermaidRenderCount;
        const { svg } = await mermaid.render(id, code);
        gqlMermaid.innerHTML = svg;
      } catch (e) {
        gqlMermaid.innerHTML = `<pre style="color:#a80000;font-size:12px;">Diagram error: ${e.message}\n\n${code}</pre>`;
      }
    }

    // Delegate navigation for span[data-href]
    document.addEventListener('click', (ev) => {
      const el = ev.target.closest && ev.target.closest('[data-href]');
      if (el) {
        const url = el.getAttribute('data-href');
        if (url) window.location.assign(url);
      }
    });

    // --- Init with optional ?ds=... pre-selection
    (async function init() {
      const params = new URLSearchParams(window.location.search);
      const dsParam = params.get('ds');

      const hasPrefill = Array.isArray(window.PREFILL_DS) && window.PREFILL_DS.length > 0;
      if (hasPrefill) {
        populateDataspaces(window.PREFILL_DS);
        if (dsParam) {
          [...dsSel.options].forEach(opt => { if (opt.value === dsParam) dsSel.value = dsParam; });
        }
        setMsg('');
        await loadTypes();
        await loadObjects();

        loadDataspaces().then(() => {
          if (dsParam) {
            [...dsSel.options].forEach(opt => { if (opt.value === dsParam) dsSel.value = dsParam; });
            loadTypes().then(loadObjects);
          }
        });
      } else {
        const ok = await loadDataspaces();
        if (ok && dsParam) {
          [...dsSel.options].forEach(opt => { if (opt.value === dsParam) dsSel.value = dsParam; });
        }
        await loadTypes();
        await loadObjects();
      }
    })();
