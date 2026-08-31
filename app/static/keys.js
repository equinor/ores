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

// Global helper: click a "Graph" button on a browse/relation card → switch to
// Object Relations mode, fill UUID, and run the query.
window.__ezShowGraph = function(uuid, typeName) {
  $('ez-action').value = 'relations';
  $('ez-action').dispatchEvent(new Event('change'));
  if ($('ez-uuid')) $('ez-uuid').value = uuid;
  if ($('ez-type') && typeName) $('ez-type').value = typeName;
  $('ez-run').click();
};

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
  const dsArg = dsList.length > 0 ? `dataspaces: ${JSON.stringify(dsList)}` : `dataspace: "default"`;
  const singleDs = dsList.length > 0 ? dsList[0] : 'default';

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
    includeRelations: ${relations}
    includeStatistics: ${stats}
    includeSampleValues: ${sample}
    limit: ${limit}
  ) {
    backend totalScanned totalMatched queryDescription warnings
    objects {
      uuid title typeName
      ${relations ? 'relations { uuid name typeName direction contentType }' : ''}
      properties {
        title kind uom
        ${stats ? 'statistics { count minValue maxValue mean stdDev }' : ''}
        ${(op && threshold) ? 'matchingCells { count total fraction }' : ''}
        ${sample ? 'arrays { path totalElements statistics { count minValue maxValue mean stdDev } sampleValues }' : ''}
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
    const uuid = ($('ez-uuid') ? $('ez-uuid').value.trim() : '') || 'PASTE-UUID-HERE';
    return `{
  objectRelations(
    dataspace: "${singleDs}"
    typeName: "${typeName}"
    uuid: "${uuid}"
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
    totalCatalog totalLocalRddms totalRemoteRddms totalMerged sources warnings
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
    sources queryDescription warnings
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
    if (ds.warnings && ds.warnings.length) {
      html += `<div style="margin-bottom:8px;padding:8px 12px;background:#fff3cd;border:1px solid #ffc107;border-radius:4px;font-size:12px;">
            <strong>Warnings:</strong>
            <ul style="margin:.3em 0 0 1.2em;padding:0;">${ds.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul>
          </div>`;
    }
    html += '<div id="ez-ds-cards"></div>';
    if ((ds.objects || []).length > 50) {
      html += '<div id="ez-ds-pager" style="display:flex;align-items:center;gap:12px;margin:8px 0;font-size:13px;"></div>';
    }
  }

  // Federated results
  if (d.federatedSearch) {
    const fs = d.federatedSearch;
    html += `<div style="margin-bottom:8px;padding:8px 12px;background:#e3f2fd;border-radius:4px;border-left:4px solid #1976d2;font-size:13px;">
          <strong>${fs.totalMerged}</strong> merged results
          &nbsp;|&nbsp; Catalog: ${fs.totalCatalog || 0} &nbsp; Local: ${fs.totalLocalRddms || 0} &nbsp; Remote: ${fs.totalRemoteRddms || 0}
          &nbsp;|&nbsp; Sources: ${(fs.sources || []).map(s => `<span class="tag">${esc(s)}</span>`).join(' ')}
        </div>`;
    if (fs.warnings && fs.warnings.length) {
      html += `<div style="margin-bottom:8px;padding:8px 12px;background:#fff3cd;border:1px solid #ffc107;border-radius:4px;font-size:12px;">
            <strong>Warnings:</strong>
            <ul style="margin:.3em 0 0 1.2em;padding:0;">${fs.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul>
          </div>`;
    }
    html += '<div id="ez-fed-cards"></div>';
    if ((fs.hits || []).length > 50) {
      html += '<div id="ez-fed-pager" style="display:flex;align-items:center;gap:12px;margin:8px 0;font-size:13px;"></div>';
    }
  }

  // Browse results (paginated)
  if (d.resqmlObjects) {
    html += `<div style="margin-bottom:8px;padding:8px 12px;background:#f3e5f5;border-radius:4px;border-left:4px solid #9c27b0;font-size:13px;">
          <strong>${d.resqmlObjects.length}</strong> objects found
        </div>`;
    html += '<div id="ez-browse-cards"></div>';
    if (d.resqmlObjects.length > 50) {
      html += '<div id="ez-browse-pager" style="display:flex;align-items:center;gap:12px;margin:8px 0;font-size:13px;"></div>';
    }
  }

  // Relation results
  if (d.objectRelations) {
    const rels = d.objectRelations;
    const targets = rels.filter(r => r.direction === 'target');
    const sources = rels.filter(r => r.direction === 'source');
    html += `<div style="margin-bottom:8px;padding:8px 12px;background:#fff3e0;border-radius:4px;border-left:4px solid #ff9800;font-size:13px;">
          <strong>${rels.length}</strong> relations (${targets.length} targets, ${sources.length} sources)
        </div>`;
    // Inline Mermaid graph for relation results
    html += '<div id="ez-rel-mermaid" style="margin-bottom:12px;padding:10px;background:#fff;border:1px solid #e1dfdd;border-radius:6px;overflow-x:auto;"></div>';
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
            <span class="btn" style="font-size:10px;padding:2px 8px;margin-left:auto;cursor:pointer;" onclick="window.__ezShowGraph('${esc(rel.uuid)}','${esc(rel.typeName)}')" title="Traverse this object">🔗 Graph</span>
          </div>`;
    });
  }

  container.innerHTML = html || '<p class="muted">Query returned no renderable results. Check JSON tab for raw output.</p>';

  // Render inline Mermaid for relation results in Easy Mode
  if (d.objectRelations && d.objectRelations.length) {
    const relMermaidEl = document.getElementById('ez-rel-mermaid');
    if (relMermaidEl) {
      try {
        const code = buildMermaidFromRelations(data);
        if (code) {
          _mermaidRenderCount++;
          const id = 'ez-rel-mmd-' + _mermaidRenderCount;
          mermaid.render(id, code).then(({ svg }) => {
            relMermaidEl.innerHTML = svg;
          }).catch(e => {
            relMermaidEl.innerHTML = `<span style="color:#a80000;font-size:12px;">Diagram error: ${e.message}</span>`;
          });
        }
      } catch (e) { console.warn('Inline mermaid error:', e); }
    }
  }

  // Paginate browse cards
  if (d.resqmlObjects && d.resqmlObjects.length > 0) {
    var BROWSE_PAGE = 50;
    var browseContainer = document.getElementById('ez-browse-cards');
    var browsePager = document.getElementById('ez-browse-pager');
    var browsePage = 0;
    var objs = d.resqmlObjects;
    function renderBrowsePage() {
      var start = browsePage * BROWSE_PAGE;
      var end = Math.min(start + BROWSE_PAGE, objs.length);
      var h = '';
      for (var i = start; i < end; i++) {
        var obj = objs[i];
        var tShort = (obj.typeName || '').replace(/^(resqml|eml)\d+\.obj_/, '');
        var cat = (_refData.resqmlTypes.find(function (t) { return t.name === obj.typeName; }) || {}).category || '';
        var colors = TYPE_COLORS[cat] || DEFAULT_COLOR;
        h += '<div style="margin-bottom:6px;padding:8px 12px;background:' + colors.bg + ';border:1px solid ' + colors.border + ';border-radius:4px;display:flex;align-items:center;gap:10px;">' +
          '<span style="font-size:11px;font-family:monospace;color:#605e5c;user-select:all;flex-shrink:0;">' + esc(obj.uuid) + '</span>' +
          '<strong style="color:' + colors.fg + ';">' + esc(obj.title) + '</strong>' +
          '<span class="tag" style="background:' + colors.bg + ';color:' + colors.fg + ';border:1px solid ' + colors.border + ';">' + tShort + '</span>' +
          '<span class="btn" style="font-size:10px;padding:2px 8px;margin-left:auto;cursor:pointer;" onclick="window.__ezShowGraph(\'' + esc(obj.uuid) + '\',\'' + esc(obj.typeName) + '\')" title="Show relationship graph">🔗 Graph</span>' +
          '</div>';
      }
      if (browseContainer) browseContainer.innerHTML = h;
      if (browsePager) {
        var pages = Math.ceil(objs.length / BROWSE_PAGE);
        browsePager.innerHTML = '<button onclick="window.__ezBrowsePrev()"' + (browsePage <= 0 ? ' disabled' : '') + ' style="padding:2px 10px;cursor:pointer;">&#8249; Prev</button>' +
          '<span>Showing ' + (start + 1) + '–' + end + ' of ' + objs.length + '</span>' +
          '<button onclick="window.__ezBrowseNext()"' + (browsePage >= pages - 1 ? ' disabled' : '') + ' style="padding:2px 10px;cursor:pointer;">Next &#8250;</button>';
      }
    }
    window.__ezBrowsePrev = function () { if (browsePage > 0) { browsePage--; renderBrowsePage(); } };
    window.__ezBrowseNext = function () { var pages = Math.ceil(objs.length / BROWSE_PAGE); if (browsePage < pages - 1) { browsePage++; renderBrowsePage(); } };
    renderBrowsePage();
  }

  // Paginate deep search cards
  if (d.deepSearch && (d.deepSearch.objects || []).length > 0) {
    var DS_PAGE = 50;
    var dsContainer = document.getElementById('ez-ds-cards');
    var dsPager = document.getElementById('ez-ds-pager');
    var dsPage = 0;
    var dsObjs = d.deepSearch.objects;
    function renderDsPage() {
      var start = dsPage * DS_PAGE;
      var end = Math.min(start + DS_PAGE, dsObjs.length);
      var h = '';
      for (var i = start; i < end; i++) {
        h += renderObjectCard(dsObjs[i]);
      }
      if (dsContainer) dsContainer.innerHTML = h;
      if (dsPager) {
        var pages = Math.ceil(dsObjs.length / DS_PAGE);
        dsPager.innerHTML = '<button onclick="window.__ezDsPrev()"' + (dsPage <= 0 ? ' disabled' : '') + ' style="padding:2px 10px;cursor:pointer;">&#8249; Prev</button>' +
          '<span>Showing ' + (start + 1) + '\u2013' + end + ' of ' + dsObjs.length + '</span>' +
          '<button onclick="window.__ezDsNext()"' + (dsPage >= pages - 1 ? ' disabled' : '') + ' style="padding:2px 10px;cursor:pointer;">Next &#8250;</button>';
      }
    }
    window.__ezDsPrev = function () { if (dsPage > 0) { dsPage--; renderDsPage(); } };
    window.__ezDsNext = function () { var pages = Math.ceil(dsObjs.length / DS_PAGE); if (dsPage < pages - 1) { dsPage++; renderDsPage(); } };
    renderDsPage();
  }

  // Paginate federated search cards
  if (d.federatedSearch && (d.federatedSearch.hits || []).length > 0) {
    var FED_PAGE = 50;
    var fedContainer = document.getElementById('ez-fed-cards');
    var fedPager = document.getElementById('ez-fed-pager');
    var fedPage = 0;
    var fedHits = d.federatedSearch.hits;
    function renderFedPage() {
      var start = fedPage * FED_PAGE;
      var end = Math.min(start + FED_PAGE, fedHits.length);
      var h = '';
      for (var i = start; i < end; i++) {
        h += renderFederatedCard(fedHits[i]);
      }
      if (fedContainer) fedContainer.innerHTML = h;
      if (fedPager) {
        var pages = Math.ceil(fedHits.length / FED_PAGE);
        fedPager.innerHTML = '<button onclick="window.__ezFedPrev()"' + (fedPage <= 0 ? ' disabled' : '') + ' style="padding:2px 10px;cursor:pointer;">&#8249; Prev</button>' +
          '<span>Showing ' + (start + 1) + '\u2013' + end + ' of ' + fedHits.length + '</span>' +
          '<button onclick="window.__ezFedNext()"' + (fedPage >= pages - 1 ? ' disabled' : '') + ' style="padding:2px 10px;cursor:pointer;">Next &#8250;</button>';
      }
    }
    window.__ezFedPrev = function () { if (fedPage > 0) { fedPage--; renderFedPage(); } };
    window.__ezFedNext = function () { var pages = Math.ceil(fedHits.length / FED_PAGE); if (fedPage < pages - 1) { fedPage++; renderFedPage(); } };
    renderFedPage();
  }

  // Check for 3D-renderable objects and show "Show 3D Results" button
  const renderableObjs = extractRenderableObjects(data);
  if (renderableObjs.length > 0) {
    insertShow3DButton(container, renderableObjs);
  }
}

// ── Compound query renderer (multi-alias deepSearch results) ───────────
// Field dev presets return multiple named aliases (e.g. lowSw, goodPerm).
// Each alias is a deepSearch result - render them as separate sections.
function renderCompoundResults(data, explanation) {
  const container = $('ez-results');
  if (!data || !data.data) {
    container.innerHTML = '<p class="muted">No results</p>';
    return;
  }
  const d = data.data;
  const aliases = Object.keys(d);
  let html = '';

  // Explanation banner
  if (explanation) {
    html += `<div style="margin-bottom:10px;padding:10px 14px;background:#e8eaf6;border:1px solid #9fa8da;border-radius:4px;font-size:12px;line-height:1.5;white-space:pre-line;font-family:'Fira Code',Consolas,monospace;color:#283593;">
      ${esc(explanation)}</div>`;
  }

  // Collect all renderable objects across aliases for 3D
  let allRenderableObjs = [];

  aliases.forEach(alias => {
    const ds = d[alias];
    if (!ds || typeof ds !== 'object') return;
    // It's a deepSearch result if it has objects or totalMatched
    if (!ds.objects && ds.totalMatched === undefined) return;

    const label = alias.replace(/([A-Z])/g, ' $1').replace(/^./, s => s.toUpperCase());
    const matchInfo = ds.totalMatched !== undefined
      ? `<strong>${ds.totalMatched}</strong> matched / <strong>${ds.totalScanned || '?'}</strong> scanned`
      : '';
    const backendTag = ds.backend ? `<span class="tag">${esc(ds.backend)}</span>` : '';

    html += `<div style="margin:12px 0 6px 0;padding:8px 12px;background:#e8f5e9;border-radius:4px;border-left:4px solid #4caf50;font-size:13px;">
          <strong style="color:#1b5e20;">${esc(label)}</strong>
          &nbsp;|&nbsp; ${matchInfo} ${backendTag}
        </div>`;

    if (ds.objects && ds.objects.length > 0) {
      ds.objects.forEach(obj => {
        html += renderObjectCard(obj);
      });
      // Collect for 3D
      const objs = ds.objects.filter(o => o.uuid);
      allRenderableObjs = allRenderableObjs.concat(objs);
    } else {
      html += '<div style="padding:6px 12px;color:#605e5c;font-size:12px;">No matching objects</div>';
    }
  });

  container.innerHTML = html || '<p class="muted">Query returned no renderable results.</p>';

  // 3D button for all collected objects
  if (allRenderableObjs.length > 0) {
    const renderableForViz = extractRenderableObjects(data);
    if (renderableForViz.length > 0) {
      insertShow3DButton(container, renderableForViz);
    }
  }
}

// ── Field dev preset runner (stays in Easy Mode) ─────────────────────────
async function runFieldDevPreset(presetKey) {
  const tpl = GQL_PRESETS[presetKey];
  if (!tpl) return;

  // Ensure a dataspace is selected — if not, try to restore last used or show error
  if (!dsSel.value && dsSel.options.length > 0) {
    // Auto-select first available dataspace
    dsSel.selectedIndex = 0;
  }
  if (!dsSel.value || dsSel.value === 'default') {
    $('ez-status').textContent = 'Select a dataspace first';
    $('ez-status').style.color = '#a80000';
    return;
  }

  // Extract explanation from comment lines
  const lines = tpl.split('\n');
  const explanation = lines
    .filter(l => l.trim().startsWith('#'))
    .map(l => l.trim().replace(/^#\s?/, ''))
    .join('\n');

  // Resolve template variables
  let query = tpl.replace(/\$DS_ARG/g, gqlDataspacesArg());
  query = query.replace(/\$DS_LIST/g, gqlDataspacesList());
  const dsName = (gqlCurrentDs().split('/').pop() || 'Drogon').replace(/^\w/, c => c.toUpperCase());
  query = query.replace(/\$DS_NAME/g, dsName);
  query = query.replace(/\$DS/g, gqlCurrentDs());

  $('ez-status').textContent = 'Running field dev query…';
  $('ez-status').style.color = '#605e5c';
  $('ez-results').innerHTML = '<div style="padding:12px;color:#605e5c;">Loading…</div>';

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
      const totalObjs = Object.values(data.data || {}).reduce((n, v) =>
        n + ((v && v.objects) ? v.objects.length : 0), 0);
      $('ez-status').textContent = `Done – ${totalObjs} object(s) across ${Object.keys(data.data || {}).length} sub-queries`;
      renderCompoundResults(data, explanation);
    }
    // Also populate the GraphQL tab for inspection
    $('gql-output').textContent = JSON.stringify(data, null, 2);
    $('gql-editor').value = query;
    gqlPreset.value = presetKey;
  } catch (e) {
    $('ez-status').textContent = 'Request failed: ' + e.message;
    $('ez-status').style.color = '#a80000';
    $('ez-results').innerHTML = `<pre style="color:#a80000;font-size:12px;padding:8px;background:#fde7e9;border-radius:4px;">${esc(e.message)}</pre>`;
  }
}

function renderObjectCard(obj) {
  const tShort = (obj.typeName || '').replace(/^resqml\d+\.obj_/, '');
  const cat = (_refData.resqmlTypes.find(t => t.name === obj.typeName) || {}).category || 'Grid';
  const colors = TYPE_COLORS[cat] || DEFAULT_COLOR;

  let html = `<div style="margin-bottom:10px;border:1px solid ${colors.border};border-radius:6px;overflow:hidden;">
        <div style="padding:8px 12px;background:${colors.bg};display:flex;align-items:center;gap:10px;flex-wrap:wrap;border-bottom:1px solid ${colors.border};">
          <strong style="color:${colors.fg};font-size:14px;">${esc(obj.title)}</strong>
          <span class="tag" style="background:${colors.bg};color:${colors.fg};border:1px solid ${colors.border};">${tShort}</span>
          <span style="font-size:10px;font-family:monospace;color:#9e9e9e;" title="${esc(obj.uuid)}">${esc(obj.uuid.substring(0,8))}…</span>
        </div>`;

  // Relations (rendered as compact pills)
  if (obj.relations && obj.relations.length) {
    html += '<div style="padding:6px 12px;display:flex;flex-wrap:wrap;gap:4px;border-bottom:1px solid #f0f0f0;">';
    obj.relations.forEach(r => {
      const rType = (r.typeName || '').replace(/^resqml\d+\.obj_/, '');
      const arrow = r.direction === 'target' ? '→' : '←';
      const rCat = (_refData.resqmlTypes.find(t => t.name === r.typeName) || {}).category || '';
      const rc = TYPE_COLORS[rCat] || DEFAULT_COLOR;
      html += `<span style="font-size:11px;padding:2px 6px;background:${rc.bg};color:${rc.fg};border:1px solid ${rc.border};border-radius:3px;" title="${esc(r.typeName)}">${arrow} ${esc(r.name || r.uuid?.substring(0,8) || '?')} <span style='color:#9e9e9e;font-size:10px;'>${rType}</span></span>`;
    });
    html += '</div>';
  }

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

/**
 * Validate query builder inputs before running.
 * Returns an array of error/warning strings. Empty = valid.
 */
function validateEasyQuery() {
  const action = $('ez-action').value;
  const errors = [];

  // Dataspace required for non-status queries
  const dsList = Array.from(dsSel.selectedOptions).map(o => o.value);
  if (dsList.length === 0 && action !== 'status') {
    errors.push('No dataspace selected. Select at least one dataspace from the list.');
  }

  // Limit bounds
  const limit = parseInt($('ez-limit').value);
  if (isNaN(limit) || limit < 1) {
    errors.push('Limit must be a positive integer (1–2000).');
  } else if (limit > 200) {
    errors.push('Limit exceeds maximum (2000). It will be capped server-side.');
  }

  // Threshold validation for deep_search / cross_system
  if (action === 'deep_search' || action === 'cross_system') {
    const op = $('ez-op').value;
    const thresholdStr = $('ez-threshold').value.trim();
    const thresholdHighStr = $('ez-threshold-high').value.trim();

    if (op && !thresholdStr) {
      errors.push('Operator selected but no threshold value specified.');
    }
    if (thresholdStr && !op) {
      errors.push('Threshold value specified but no operator selected.');
    }
    if (thresholdStr && isNaN(parseFloat(thresholdStr))) {
      errors.push('Threshold must be a number (e.g. 0.1, 100, 0.05).');
    }
    if (op === 'BETWEEN') {
      if (!thresholdHighStr) {
        errors.push('BETWEEN operator requires both threshold (low) and threshold high (high) values.');
      } else if (isNaN(parseFloat(thresholdHighStr))) {
        errors.push('Threshold high must be a number.');
      } else if (parseFloat(thresholdHighStr) < parseFloat(thresholdStr)) {
        errors.push('Threshold high must be >= threshold (low value).');
      }
    }

    // Warn: array filter without property kind
    if (op && thresholdStr && !$('ez-prop').value.trim()) {
      errors.push('Warning: array filter without a property kind will scan ALL properties on each object - this may be slow. Consider specifying a property (e.g. porosity, perm).');
    }
  }

  return errors;
}

$('ez-run').addEventListener('click', async () => {
  const action = $('ez-action').value;
  // Check for missing UUID in relations mode
  if (action === 'relations') {
    const uuid = $('ez-uuid') ? $('ez-uuid').value.trim() : '';
    if (!uuid || uuid === 'PASTE-UUID-HERE') {
      $('ez-status').textContent = 'Please enter a UUID. Run "Browse Objects" first to find one.';
      $('ez-results').innerHTML = `<div style="padding:12px;background:#fff3cd;border:1px solid #ffc107;border-radius:4px;font-size:13px;">
        <strong>UUID required</strong> - Switch to <em>Browse Objects</em> to list objects of this type, then copy a UUID and paste it into the UUID field above.
      </div>`;
      return;
    }
  }

  // Frontend validation
  const validationErrors = validateEasyQuery();
  const hardErrors = validationErrors.filter(e => !e.startsWith('Warning:'));
  if (hardErrors.length > 0) {
    $('ez-status').textContent = 'Validation failed';
    $('ez-results').innerHTML = `<div style="padding:12px;background:#fff3cd;border:1px solid #ffc107;border-radius:4px;font-size:13px;">
      <strong>Please fix the following:</strong>
      <ul style="margin:.5em 0 0 1.2em;padding:0;">${validationErrors.map(e => `<li>${esc(e)}</li>`).join('')}</ul>
    </div>`;
    return;
  }
  // Show soft warnings but proceed
  if (validationErrors.length > 0) {
    $('ez-status').textContent = 'Running (with warnings)…';
  }

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
  // Property row: only for deep_search, federated, cross_system (query types that filter on properties)
  const showProp = (action === 'deep_search' || action === 'federated' || action === 'cross_system');
  $('ez-prop-row').style.display = showProp ? 'flex' : 'none';
  // Filter row (array thresholds): only for deep_search, cross_system
  $('ez-filter-row').style.display = (action === 'deep_search' || action === 'cross_system') ? 'flex' : 'none';
  // UUID row: only for relations
  $('ez-uuid-label').style.display = (action === 'relations') ? '' : 'none';
  $('ez-uuid-row').style.display = (action === 'relations') ? 'flex' : 'none';
  // Options: show/hide checkboxes based on query type relevance
  const showStats = (action === 'deep_search' || action === 'federated');
  const showRelations = (action === 'deep_search' || action === 'federated');
  const showSample = (action === 'deep_search');
  $('ez-stats-label').style.display = showStats ? '' : 'none';
  $('ez-relations-label').style.display = showRelations ? '' : 'none';
  $('ez-sample-label').style.display = showSample ? '' : 'none';
  // Clear property/filter values when hiding to avoid stale state in generated queries
  if (!showProp) {
    $('ez-prop').value = '';
    $('ez-prop-resolved').textContent = '';
    if ($('ez-prop-pick')) $('ez-prop-pick').selectedIndex = 0;
  }
  if (action !== 'deep_search' && action !== 'cross_system') {
    $('ez-op').selectedIndex = 0;
    $('ez-threshold').value = '';
    $('ez-threshold-high').value = '';
  }
});

// Easy-mode quick example: wellbore markers grouped by horizon/feature,
// renderable in 3D via the "Show 3D Results" button.
const ezExMarkers = $('ez-ex-markers');
if (ezExMarkers) {
  ezExMarkers.addEventListener('click', () => runFieldDevPreset('markers_by_horizon'));
}

// Easy-mode field dev examples - run the full compound preset, stay in Easy Mode
const _ezFieldDevExamples = [
  { id: 'ez-ex-bypassed', preset: 'field_bypassed_oil' },
  { id: 'ez-ex-highperm', preset: 'field_water_breakthrough' },
  { id: 'ez-ex-ntg', preset: 'field_completion_ntg' },
  { id: 'ez-ex-poro', preset: 'field_segment_ranking' },
  { id: 'ez-ex-injection', preset: 'field_injection_support' },
  { id: 'ez-ex-grid-inv', preset: 'field_grid_inventory' },
];
_ezFieldDevExamples.forEach(ex => {
  const btn = $(ex.id);
  if (btn) {
    btn.addEventListener('click', () => runFieldDevPreset(ex.preset));
  }
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
  return `<table class="meta-table"><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody>${pairs.map(p => `<tr><td>${esc(p.name)}</td><td><code>${esc(String(p.value))}</code></td></tr>`).join('')
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
  'deviationsurveyrepresentation', 'ijkgridrepresentation',
  'continuousproperty', 'discreteproperty', 'categoricalproperty'];
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
  if (t < 0.25) { const s = t / 0.25; r = 0.28 * (1 - s) + 0.13 * s; g = 0.0 * (1 - s) + 0.57 * s; b = 0.33 * (1 - s) + 0.55 * s; }
  else if (t < 0.5) { const s = (t - 0.25) / 0.25; r = 0.13 * (1 - s) + 0.15 * s; g = 0.57 * (1 - s) + 0.73 * s; b = 0.55 * (1 - s) + 0.34 * s; }
  else if (t < 0.75) { const s = (t - 0.5) / 0.25; r = 0.15 * (1 - s) + 0.63 * s; g = 0.73 * (1 - s) + 0.85 * s; b = 0.34 * (1 - s) + 0.17 * s; }
  else { const s = (t - 0.75) / 0.25; r = 0.63 * (1 - s) + 0.99 * s; g = 0.85 * (1 - s) + 0.91 * s; b = 0.17 * (1 - s) + 0.14 * s; }
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
      _gql3dRotX = Math.max(-Math.PI / 2 + 0.01, Math.min(Math.PI / 2 - 0.01, _gql3dRotX));
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
      lastPinch = Math.sqrt(dx * dx + dy * dy);
    }
  });
  el.addEventListener('touchmove', e => {
    e.preventDefault();
    if (e.touches.length === 1 && drag) {
      const dx = e.touches[0].clientX - px, dy = e.touches[0].clientY - py;
      _gql3dRotY += dx * 0.008; _gql3dRotX += dy * 0.008;
      _gql3dRotX = Math.max(-Math.PI / 2 + 0.01, Math.min(Math.PI / 2 - 0.01, _gql3dRotX));
      px = e.touches[0].clientX; py = e.touches[0].clientY;
      _gql3dUpdateCam();
    } else if (e.touches.length === 2) {
      const dx = e.touches[1].clientX - e.touches[0].clientX, dy = e.touches[1].clientY - e.touches[0].clientY;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (lastPinch > 0) { _gql3dZoomDist *= lastPinch / dist; _gql3dZoomDist = Math.max(0.3, Math.min(50, _gql3dZoomDist)); _gql3dUpdateCam(); }
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
    const x = positions[i], y = positions[i + 1], z = positions[i + 2];
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
  const propVals = geo.propertyValues || null;
  const propMin = geo.propertyMin || 0, propMax = geo.propertyMax || 1;
  const cmInfo = geo.colorMap || null;
  const pLog = cmInfo && cmInfo.useLog, pRev = cmInfo && cmInfo.useReverse;
  const pCmap = cmInfo && cmInfo.colorMapName;
  const normPos = new Float32Array(positions.length);
  const colors = new Float32Array(positions.length);
  for (let i = 0; i < nVerts; i++) {
    normPos[i * 3] = (positions[i * 3] - cx) / extLateral * 2;
    normPos[i * 3 + 1] = (cz - positions[i * 3 + 2]) / extLateral * 2 * zExag;  // depth increases downward
    normPos[i * 3 + 2] = (positions[i * 3 + 1] - cy) / extLateral * 2;
    if (propVals && propVals.length > i) {
      const [cr, cg, cb] = _colorFromProperty(propVals[i], propMin, propMax, pLog, pRev, pCmap);
      colors[i * 3] = cr; colors[i * 3 + 1] = cg; colors[i * 3 + 2] = cb;
    } else if (kind === 'surface' || kind === 'points') {
      const z = positions[i * 3 + 2];
      const [cr, cg, cb] = _gql3dColorZ(isFinite(z) ? z : cz, zmin, zmax);
      colors[i * 3] = cr; colors[i * 3 + 1] = cg; colors[i * 3 + 2] = cb;
    } else {
      colors[i * 3] = baseColor.r; colors[i * 3 + 1] = baseColor.g; colors[i * 3 + 2] = baseColor.b;
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
  } else if (kind === 'points') {
    mesh = new THREE.Points(geom3, new THREE.PointsMaterial({
      vertexColors: true, size: 0.015, sizeAttenuation: true,
    }));
  } else if (kind === 'markers') {
    // Oriented geological-layer disks (bedding planes), tilted by dip.
    const normals = geo.normals || [];
    const diskR = 0.06;
    const baseN = new THREE.Vector3(0, 0, 1);
    mesh = new THREE.Group();
    for (let i = 0; i < nVerts; i++) {
      let nv;
      if (normals.length >= (i + 1) * 3) {
        nv = new THREE.Vector3(
          normals[i * 3], normals[i * 3 + 2] * zExag, normals[i * 3 + 1]);
      } else {
        nv = new THREE.Vector3(0, 1, 0);
      }
      if (nv.lengthSq() < 1e-9) nv.set(0, 1, 0);
      nv.normalize();
      const disk = new THREE.Mesh(
        new THREE.CircleGeometry(diskR, 40),
        new THREE.MeshPhongMaterial({
          color: baseColor, side: THREE.DoubleSide,
          shininess: 18, transparent: true, opacity: 0.82,
        }));
      disk.quaternion.setFromUnitVectors(baseN, nv);
      disk.position.set(normPos[i * 3], normPos[i * 3 + 1], normPos[i * 3 + 2]);
      mesh.add(disk);
    }
  } else if (kind === 'trajectory') {
    mesh = new THREE.Line(geom3, new THREE.LineBasicMaterial({ vertexColors: true, linewidth: 2 }));
    const sg = new THREE.SphereGeometry(0.012, 6, 6);
    const s1 = new THREE.Mesh(sg, new THREE.MeshBasicMaterial({ color: hexColor }));
    s1.position.set(normPos[0], normPos[1], normPos[2]);
    scene.add(s1);
    if (nVerts > 1) {
      const s2 = new THREE.Mesh(sg, new THREE.MeshBasicMaterial({ color: 0xff4444 }));
      s2.position.set(normPos[(nVerts - 1) * 3], normPos[(nVerts - 1) * 3 + 1], normPos[(nVerts - 1) * 3 + 2]);
      scene.add(s2);
    }
  } else if (kind === 'polylines') {
    const counts = geo.counts || [];
    mesh = new THREE.Group();
    if (counts.length > 0) {
      let offset = 0;
      for (const cnt of counts) {
        const lp = new Float32Array(cnt * 3), lc = new Float32Array(cnt * 3);
        for (let j = 0; j < cnt && (offset + j) < nVerts; j++) {
          const idx = offset + j;
          lp[j * 3] = normPos[idx * 3]; lp[j * 3 + 1] = normPos[idx * 3 + 1]; lp[j * 3 + 2] = normPos[idx * 3 + 2];
          lc[j * 3] = colors[idx * 3]; lc[j * 3 + 1] = colors[idx * 3 + 1]; lc[j * 3 + 2] = colors[idx * 3 + 2];
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
      if (!b.isEmpty()) {
        obj.updateWorldMatrix(true, false);
        b.applyMatrix4(obj.matrixWorld);  // account for per-marker offsets
        box.union(b);
      }
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
    gridObj.scale.set(gs / 4, 1, gs / 4);
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
  const kindLabels = { surface: 'Surface', points: 'Points', trajectory: 'Well', markers: 'Markers', polylines: 'Polylines' };
  legend.innerHTML = entries.map(o =>
    `<div class="gql3d-legend-item"><span class="gql3d-legend-dot" style="background:${o.color}"></span>${esc(o.title)} <span style="opacity:0.6;font-size:10px;">(${kindLabels[o.kind] || o.kind})</span></div>`
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
  const seen = new Set();
  function _add(o) {
    if (o.uuid && is3dType(o.typeName) && !seen.has(o.uuid)) {
      objs.push({ uuid: o.uuid, title: o.title, typeName: o.typeName });
      seen.add(o.uuid);
    }
  }

  // Single-alias deepSearch
  if (d.deepSearch && d.deepSearch.objects) {
    d.deepSearch.objects.forEach(_add);
  }
  if (d.federatedSearch && d.federatedSearch.hits) {
    d.federatedSearch.hits.forEach(_add);
  }
  if (d.resqmlObjects) {
    d.resqmlObjects.forEach(_add);
  }
  // Compound queries: scan all aliases for deepSearch-like results
  Object.keys(d).forEach(key => {
    if (key === 'deepSearch' || key === 'federatedSearch' || key === 'resqmlObjects') return;
    const v = d[key];
    if (v && v.objects && Array.isArray(v.objects)) {
      v.objects.forEach(_add);
    }
  });
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
  if (!dsList.length) dsList.push('default');  // fallback

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
          .catch(() => { });
        return true;
      }
    } catch (_) { }
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

    // Group types by category
    const byCategory = {};
    (js.items || []).forEach(x => {
      if (!x || !x.name) return;
      const cat = x.category || 'Other';
      if (!byCategory[cat]) byCategory[cat] = [];
      byCategory[cat].push(x);
    });

    // Add types grouped by category using optgroups
    const sortedCategories = Object.keys(byCategory).sort();
    sortedCategories.forEach(cat => {
      const og = document.createElement('optgroup');
      og.label = cat;
      byCategory[cat].forEach(x => {
        const o = document.createElement('option');
        o.value = x.name;
        o.textContent = x.count ? `${x.name} (${x.count})` : x.name;
        og.appendChild(o);
      });
      typSel.appendChild(og);
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
  if (!dsSel.value) return;
  // Get all selected types (multi-select support)
  const selectedTypes = Array.from(typSel.selectedOptions).map(o => o.value);
  if (selectedTypes.length === 0) return;
  setMsg('Loading objects…');
  showLoading('Loading objects…');
  try {
    // Join multiple types with comma for backend
    const typParam = selectedTypes.join(',');
    const url = `/keys/objects.json?ds=${encodeURIComponent(dsSel.value)}&typ=${encodeURIComponent(typParam)}`;
    const r = await fetch(url, { credentials: 'same-origin' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const js = await r.json();
    objSel.innerHTML = '';
    (js.items || []).forEach(x => {
      const o = document.createElement('option');
      o.value = x.uuid;
      o.textContent = `${x.label || x.title || x.uuid} - ${x.uuid}`;
      o.setAttribute('data-uri', x.uri || '');
      objSel.appendChild(o);
    });
    clearDetails();
    const typeCount = selectedTypes.length > 1 ? ` (${selectedTypes.length} types)` : '';
    setMsg(js.items && js.items.length ? '' : `No objects found${typeCount}.`);
  } catch (e) {
    setMsg('Failed to load objects.');
    console.error(e);
  } finally {
    hideLoading();
  }
}

// ── Array Popup ──────────────────────────────────────────────────────
async function showArrayPopup(ds, uuid, path) {
  const overlay = $('array-popup-overlay');
  const titleEl = $('array-popup-title');
  const statsEl = $('array-popup-stats');
  const valuesEl = $('array-popup-values');
  titleEl.textContent = path;
  statsEl.innerHTML = '<p class="muted">Loading…</p>';
  valuesEl.textContent = '';
  overlay.classList.add('open');

  try {
    const qp = `ds=${encodeURIComponent(ds)}&uuid=${encodeURIComponent(uuid)}&path=${encodeURIComponent(path)}`;
    const res = await fetch(`/keys/object/array.json?${qp}`, { credentials: 'same-origin' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();

    // Render statistics
    if (data.statistics) {
      const s = data.statistics;
      const cards = [
        { label: 'Count', value: s.count },
        { label: 'Min', value: s.minValue?.toFixed(4) },
        { label: 'Max', value: s.maxValue?.toFixed(4) },
        { label: 'Mean', value: s.mean?.toFixed(4) },
        { label: 'Median', value: s.median?.toFixed(4) },
        { label: 'Std Dev', value: s.stdDev?.toFixed(4) },
      ];
      if (s.nanCount > 0) cards.push({ label: 'NaN', value: s.nanCount });
      statsEl.innerHTML = cards.map(c =>
        `<div class="stat-card"><div class="stat-label">${c.label}</div><div class="stat-value">${c.value}</div></div>`
      ).join('');
    } else {
      statsEl.innerHTML = '<p class="muted">No statistics (empty array).</p>';
    }

    // Render values
    const truncNote = data.truncated ? `\n\n… (showing first 200 of ${data.totalElements} values)` : '';
    valuesEl.textContent = JSON.stringify(data.values, null, 2) + truncNote;
  } catch (e) {
    statsEl.innerHTML = `<p style="color:red;">Error: ${esc(e.message)}</p>`;
    valuesEl.textContent = '';
  }
}

// Array popup close handlers
$('array-popup-close').addEventListener('click', () => {
  $('array-popup-overlay').classList.remove('open');
});
$('array-popup-overlay').addEventListener('click', (e) => {
  if (e.target === $('array-popup-overlay')) $('array-popup-overlay').classList.remove('open');
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && $('array-popup-overlay').classList.contains('open')) {
    $('array-popup-overlay').classList.remove('open');
  }
});

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
    const ct = p.contentType || '';
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
      extrametaEl.innerHTML = `<table class="meta-table"><thead><tr><th>Name</th><th>Value</th></tr></thead><tbody>${em.map(e => `<tr><td>${esc(e.name)}</td><td><code>${esc(e.value)}</code></td></tr>`).join('')
        }</tbody></table>`;
    }

    // --- Aliases ---
    const al = md.aliases || [];
    if (al.length) {
      aliasesSection.style.display = '';
      aliasesEl.innerHTML = `<table class="meta-table"><thead><tr><th>Authority</th><th>Identifier</th></tr></thead><tbody>${al.map(a => `<tr><td>${esc(a.authority)}</td><td><code>${esc(a.identifier)}</code></td></tr>`).join('')
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
      ? `<ul>${arr.map(a => {
        const p = a.path || a.pathInResource || (a.uid && a.uid.pathInResource) || '';
        return `<li data-array-path="${esc(p)}"><code>${esc(p)}</code></li>`;
      }).join('')
      }</ul>`
      : '<p class="muted">No arrays.</p>';
    // Attach click handlers for array popup
    arraysEl.querySelectorAll('li[data-array-path]').forEach(li => {
      li.addEventListener('click', () => showArrayPopup(ds, uuid, li.dataset.arrayPath));
    });

    // --- Grid2d section (auto-detect table vs depth map) ---
    if (isGrid2dType(typ)) {
      grid2dSection.style.display = '';
      const mode = (arr.length > 0) ? classifyGrid2d(js.content || {}) : 'map';
      grid2dBadge.textContent = mode === 'table' ? 'Data Table'
        : mode === 'map' ? 'Depth Map'
          : 'Grid2dRepresentation';
      grid2dStatus.textContent = '';
      btnTable.style.display = (mode === 'table' || mode === 'both') ? '' : 'none';
      btnMap.style.display = (mode === 'map' || mode === 'both') ? '' : 'none';
      btn3d.style.display = (mode === 'map' || mode === 'both') ? '' : 'none';
      const hint = mode === 'table' ? 'Detected as a data table (resqpy DataFrame).'
        : mode === 'map' ? 'Detected as a spatial depth surface.'
          : 'Could not auto-detect - try either view.';
      grid2dView.innerHTML = `<p class="muted">${hint}</p>`;
    }
    // --- Other 3D-capable types ---
    else if (is3dType(typ)) {
      grid2dSection.style.display = '';
      const shortType = typ.replace(/.*obj_/, '').replace(/^resqml\d+\./, '').replace(/Representation$/, '');
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
      const d = meta.dims || [0, 0];
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
      + ['viridis_r', 'terrain', 'coolwarm', 'RdYlBu_r', 'plasma_r', 'cividis_r', 'Spectral_r']
        .map(c => `<option${c === 'viridis_r' ? ' selected' : ''}>${c}</option>`).join('')
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
    $('map-cmap').onchange = function () { cmap = this.value; img.src = pngUrl(); grid2dStatus.textContent = 'Refreshing…'; };
    $('map-dpi').onchange = function () { dpi = parseInt(this.value); img.src = pngUrl(); grid2dStatus.textContent = 'Refreshing…'; };

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
      lookupInfo = `<details style="margin-top:8px;"><summary><b>String Lookups</b> (${lookupKeys.length})</summary><ul>${lookupKeys.map(k => {
        const lu = lookups[k];
        const entries = Object.entries(lu || {});
        const preview = entries.slice(0, 8).map(([i, v]) => `${i}→${v}`).join(', ');
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
    r = 0.28 * (1 - s) + 0.13 * s;
    g = 0.0 * (1 - s) + 0.57 * s;
    b = 0.33 * (1 - s) + 0.55 * s;
  } else if (t < 0.5) {
    const s = (t - 0.25) / 0.25;
    r = 0.13 * (1 - s) + 0.15 * s;
    g = 0.57 * (1 - s) + 0.73 * s;
    b = 0.55 * (1 - s) + 0.34 * s;
  } else if (t < 0.75) {
    const s = (t - 0.5) / 0.25;
    r = 0.15 * (1 - s) + 0.63 * s;
    g = 0.73 * (1 - s) + 0.85 * s;
    b = 0.34 * (1 - s) + 0.17 * s;
  } else {
    const s = (t - 0.75) / 0.25;
    r = 0.63 * (1 - s) + 0.99 * s;
    g = 0.85 * (1 - s) + 0.91 * s;
    b = 0.17 * (1 - s) + 0.14 * s;
  }
  return [r, g, b];
}

function _colorFromProperty(val, vmin, vmax, useLog, useReverse, cmapName) {
  // Color by property value with named colormap support (from GraphicalInformationSet)
  if (val == null || !isFinite(val)) return [0.3, 0.3, 0.3]; // grey for null/NaN
  let t;
  if (useLog && vmin > 0 && vmax > vmin && val > 0) {
    t = (Math.log(val) - Math.log(vmin)) / (Math.log(vmax) - Math.log(vmin));
  } else {
    t = vmax > vmin ? (val - vmin) / (vmax - vmin) : 0.5;
  }
  t = Math.max(0, Math.min(1, t));
  if (useReverse) t = 1 - t;
  const name = (cmapName || '').toLowerCase();
  if (name === 'viridis') return _cmapViridis(t);
  if (name === 'hot') return _cmapHot(t);
  return _cmapPlasma(t); // default
}

function _cmapPlasma(t) {
  // plasma: dark purple → magenta → orange → yellow
  let r, g, b;
  if (t < 0.25) {
    const s = t / 0.25;
    r = 0.05 * (1 - s) + 0.55 * s;
    g = 0.03 * (1 - s) + 0.0 * s;
    b = 0.53 * (1 - s) + 0.65 * s;
  } else if (t < 0.5) {
    const s = (t - 0.25) / 0.25;
    r = 0.55 * (1 - s) + 0.87 * s;
    g = 0.0 * (1 - s) + 0.22 * s;
    b = 0.65 * (1 - s) + 0.51 * s;
  } else if (t < 0.75) {
    const s = (t - 0.5) / 0.25;
    r = 0.87 * (1 - s) + 0.99 * s;
    g = 0.22 * (1 - s) + 0.56 * s;
    b = 0.51 * (1 - s) + 0.13 * s;
  } else {
    const s = (t - 0.75) / 0.25;
    r = 0.99 * (1 - s) + 0.94 * s;
    g = 0.56 * (1 - s) + 0.97 * s;
    b = 0.13 * (1 - s) + 0.13 * s;
  }
  return [r, g, b];
}

function _cmapViridis(t) {
  // viridis: purple → blue → teal → green → yellow
  let r, g, b;
  if (t < 0.25) {
    const s = t / 0.25;
    r = 0.28 * (1 - s) + 0.13 * s;
    g = 0.0 * (1 - s) + 0.57 * s;
    b = 0.33 * (1 - s) + 0.55 * s;
  } else if (t < 0.5) {
    const s = (t - 0.25) / 0.25;
    r = 0.13 * (1 - s) + 0.15 * s;
    g = 0.57 * (1 - s) + 0.73 * s;
    b = 0.55 * (1 - s) + 0.34 * s;
  } else if (t < 0.75) {
    const s = (t - 0.5) / 0.25;
    r = 0.15 * (1 - s) + 0.63 * s;
    g = 0.73 * (1 - s) + 0.85 * s;
    b = 0.34 * (1 - s) + 0.17 * s;
  } else {
    const s = (t - 0.75) / 0.25;
    r = 0.63 * (1 - s) + 0.99 * s;
    g = 0.85 * (1 - s) + 0.91 * s;
    b = 0.17 * (1 - s) + 0.14 * s;
  }
  return [r, g, b];
}

function _cmapHot(t) {
  // hot: black → red → orange → yellow → white
  let r, g, b;
  if (t < 0.33) {
    const s = t / 0.33;
    r = s; g = 0; b = 0;
  } else if (t < 0.67) {
    const s = (t - 0.33) / 0.34;
    r = 1.0; g = s; b = 0;
  } else {
    const s = (t - 0.67) / 0.33;
    r = 1.0; g = 1.0; b = s;
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
          <div id="viewer3d-controls" style="position:absolute;bottom:10px;left:10px;z-index:5;display:none;font-size:12px;color:#cfe3ff;background:rgba(20,20,46,0.72);padding:5px 9px;border-radius:4px;"></div>
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
      const x = positions[i * 3], y = positions[i * 3 + 1], z = positions[i * 3 + 2];
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
    // Normalization scale. For near-vertical features (wells, marker frames)
    // the lateral extent collapses to ~0, which would blow up the depth-axis
    // mapping and push the object off-screen. Fall back to the full 3D
    // extent in that case so the geometry stays framed by the camera.
    const normScale = (extLateral < extent * 0.2) ? extent : extLateral;
    // Z exaggeration: amplify depth relief so it's clearly visible in 3D
    // For subsurface surfaces the Z range is often <5% of lateral → exaggerate
    let zExag = 1;
    if (extZ > 0 && kind === 'surface') {
      const ratio = extZ / extLateral;
      // Auto-exaggerate so depth relief is clearly visible in 3D
      // No hard cap – the HUD shows the exaggeration factor
      if (ratio < 0.4) zExag = Math.max(3, 0.4 / ratio);
    }

    // Property coloring: use property values if available
    const propVals = geo.propertyValues || null;
    const propMin = geo.propertyMin || 0, propMax = geo.propertyMax || 1;
    const propName = geo.propertyName || '';
    const colorMapInfo = geo.colorMap || null;
    const useLog = colorMapInfo && colorMapInfo.useLog;
    const useReverse = colorMapInfo && colorMapInfo.useReverse;
    const cmapName = colorMapInfo && colorMapInfo.colorMapName;

    // Normalize positions to center and apply z-exaggeration
    const normPos = new Float32Array(positions.length);
    const colors = new Float32Array(positions.length);
    for (let i = 0; i < nVerts; i++) {
      normPos[i * 3] = (positions[i * 3] - cx) / normScale * 2;
      normPos[i * 3 + 1] = (cz - positions[i * 3 + 2]) / normScale * 2 * zExag;  // Z → Y (up); depth increases downward
      normPos[i * 3 + 2] = (positions[i * 3 + 1] - cy) / normScale * 2;          // Y → Z (depth)
      if (propVals && propVals.length > i) {
        // Color by property value
        const v = propVals[i];
        const [cr, cg, cb] = _colorFromProperty(v, propMin, propMax, useLog, useReverse, cmapName);
        colors[i * 3] = cr; colors[i * 3 + 1] = cg; colors[i * 3 + 2] = cb;
      } else {
        const z = positions[i * 3 + 2];
        const [cr, cg, cb] = colorFromZ(isFinite(z) ? z : cz, zmin, zmax);
        colors[i * 3] = cr; colors[i * 3 + 1] = cg; colors[i * 3 + 2] = cb;
      }
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
    } else if (kind === 'points') {
      const mat = new THREE.PointsMaterial({
        vertexColors: true, size: 0.015,
        sizeAttenuation: true,
      });
      mesh = new THREE.Points(geom3, mat);
    } else if (kind === 'markers') {
      // Geological layer markers: draw an oriented disk (bedding plane) at
      // each marker position, tilted by the layer's dip / dip-azimuth.
      const md = geo.md || [];
      const normals = geo.normals || [];
      const diskR = 0.09;
      const baseN = new THREE.Vector3(0, 0, 1);  // CircleGeometry faces +Z
      const datumObjs = [];  // KB / MSL / above-datum markers (MD ≤ 0)
      mesh = new THREE.Group();
      for (let i = 0; i < nVerts; i++) {
        const isDatum = md.length > i && md[i] <= 0;
        // Normal in viewer frame (RESQML X→X, Z→Y, Y→Z). zExag stretches
        // the depth axis, so divide the up-component to keep the disk
        // perpendicular to the (exaggerated) bedding.
        let nv;
        if (normals.length >= (i + 1) * 3) {
          nv = new THREE.Vector3(
            normals[i * 3], normals[i * 3 + 2] * zExag, normals[i * 3 + 1]);
        } else {
          nv = new THREE.Vector3(0, 1, 0);
        }
        if (nv.lengthSq() < 1e-9) nv.set(0, 1, 0);
        nv.normalize();
        const col = new THREE.Color(colors[i * 3], colors[i * 3 + 1], colors[i * 3 + 2]);
        const diskGeo = new THREE.CircleGeometry(diskR, 48);
        const diskMat = new THREE.MeshPhongMaterial({
          color: col, side: THREE.DoubleSide,
          shininess: 18, transparent: true, opacity: 0.82,
        });
        const disk = new THREE.Mesh(diskGeo, diskMat);
        disk.quaternion.setFromUnitVectors(baseN, nv);
        disk.position.set(normPos[i * 3], normPos[i * 3 + 1], normPos[i * 3 + 2]);
        mesh.add(disk);
        // Bright rim so thin/edge-on disks stay visible.
        const ringGeo = new THREE.RingGeometry(diskR * 0.92, diskR, 48);
        const ringMat = new THREE.MeshBasicMaterial({
          color: 0xffffff, side: THREE.DoubleSide,
          transparent: true, opacity: 0.55,
        });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.quaternion.copy(disk.quaternion);
        ring.position.copy(disk.position);
        mesh.add(ring);
        if (isDatum) { datumObjs.push(disk, ring); }
      }

      // Label sprites
      if (geo.labels && geo.labels.length) {
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
          sprite.position.set(normPos[i * 3] + diskR + 0.02, normPos[i * 3 + 1] + 0.02, normPos[i * 3 + 2]);
          sprite.scale.set(0.15, 0.04, 1);
          scene.add(sprite);
          if (md.length > i && md[i] <= 0) datumObjs.push(sprite);
        }
      }

      // KB / datum-marker visibility toggle. Markers at or above the
      // wellhead datum (MD ≤ 0, e.g. KB / MSL) are hidden by default so the
      // geological markers are the focus.
      if (datumObjs.length) {
        const setDatumHidden = (hide) => datumObjs.forEach(o => { o.visible = !hide; });
        setDatumHidden(true);
        const ctrls = $('viewer3d-controls');
        if (ctrls) {
          ctrls.style.display = '';
          ctrls.innerHTML = `<label style="cursor:pointer;"><input type="checkbox" id="vz-hide-kb" checked> Hide KB / datum markers (MD &le; 0)</label>`;
          const cb = $('vz-hide-kb');
          if (cb) cb.addEventListener('change', () => setDatumHidden(cb.checked));
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
        endSphere.position.set(normPos[(nVerts - 1) * 3], normPos[(nVerts - 1) * 3 + 1], normPos[(nVerts - 1) * 3 + 2]);
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
            linePos[j * 3] = normPos[idx * 3]; linePos[j * 3 + 1] = normPos[idx * 3 + 1]; linePos[j * 3 + 2] = normPos[idx * 3 + 2];
            lineCol[j * 3] = colors[idx * 3]; lineCol[j * 3 + 1] = colors[idx * 3 + 1]; lineCol[j * 3 + 2] = colors[idx * 3 + 2];
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
        wireIdx.push(indices[t * 3], indices[t * 3 + 1], indices[t * 3 + 2]);
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
    const yMin = (cz - maxZ) / normScale * 2 * zExag;  // deepest → bottom
    const yMax = (cz - minZ) / normScale * 2 * zExag;  // shallowest → top
    const halfW = extX / normScale;
    const halfD = extY / normScale;

    // ── Ground grid ──
    const gridSize = Math.max(halfW, halfD) * 2.2;
    const gridHelper = new THREE.GridHelper(gridSize, 12, 0x5566aa, 0x3a3a6e);
    gridHelper.position.y = yMin - 0.08;
    scene.add(gridHelper);

    // ── Bounding box wireframe ──
    const bbW = extX / normScale * 2;
    const bbH = (yMax - yMin) || 0.1;
    const bbD = extY / normScale * 2;
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
        rotX = Math.max(-Math.PI / 2 + 0.01, Math.min(Math.PI / 2 - 0.01, rotX));
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
        lastPinchDist = Math.sqrt(dx * dx + dy * dy);
      }
    });
    renderer.domElement.addEventListener('touchmove', e => {
      e.preventDefault();
      if (e.touches.length === 1 && isDragging) {
        const dx = e.touches[0].clientX - prevX, dy = e.touches[0].clientY - prevY;
        rotY += dx * 0.008;
        rotX += dy * 0.008;
        rotX = Math.max(-Math.PI / 2 + 0.01, Math.min(Math.PI / 2 - 0.01, rotX));
        prevX = e.touches[0].clientX; prevY = e.touches[0].clientY;
        updateCamera();
      } else if (e.touches.length === 2) {
        const dx = e.touches[1].clientX - e.touches[0].clientX;
        const dy = e.touches[1].clientY - e.touches[0].clientY;
        const dist = Math.sqrt(dx * dx + dy * dy);
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
        case 'ArrowLeft': rotY -= rotStep; break;
        case 'ArrowRight': rotY += rotStep; break;
        case 'ArrowUp': rotX = Math.min(Math.PI / 2 - 0.01, rotX + rotStep); break;
        case 'ArrowDown': rotX = Math.max(-Math.PI / 2 + 0.01, rotX - rotStep); break;
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
    _viewer3d = { renderer, scene, camera, controls: { dispose() { } }, animId: 0 };
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
    const legendIsProp = !!(propVals && propVals.length);
    for (let y = 0; y < 200; y++) {
      const t = 1 - y / 199;
      let cr, cg, cb;
      if (legendIsProp) {
        const v = propMin + t * (propMax - propMin);
        [cr, cg, cb] = _colorFromProperty(v, propMin, propMax, useLog, useReverse, cmapName);
      } else {
        const z = zmin + t * (zmax - zmin);
        [cr, cg, cb] = colorFromZ(z, zmin, zmax);
      }
      lctx.fillStyle = `rgb(${cr * 255 | 0},${cg * 255 | 0},${cb * 255 | 0})`;
      lctx.fillRect(0, y, 24, 1);
    }
    const labels = $('viewer3d-legend-labels');
    if (legendIsProp) {
      labels.innerHTML = `<span>${propMax.toFixed(2)}</span><span>${propName}</span><span>${propMin.toFixed(2)}</span>`;
    } else {
      labels.innerHTML = `<span>${zmax.toFixed(1)}</span><span>${((zmin + zmax) / 2).toFixed(1)}</span><span>${zmin.toFixed(1)}</span>`;
    }

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
  // ─── Browse & Explore ─────────────────────────────────────────────
  status: `{
  status
}`,
  dataspaces: `{
  dataspaces {
    path
    uri
  }
}`,
  types: `# Count of each type in the selected dataspace
{
  resourceTypes(dataspace: "$DS") {
    name
    count
  }
}`,
  objects_grid: `# Browse objects by type (change typeName as needed)
{
  resqmlObjects(
    dataspace: "$DS"
    typeName: "resqml20.obj_PointSetRepresentation"
    limit: 20
  ) {
    uuid
    title
    typeName
  }
}`,

  // ─── Relationships ────────────────────────────────────────────────
  rel_grid_targets: `# Object relations for a specific object (paste UUID from browse)
# Step 1: Run "Browse objects" to find UUIDs
# Step 2: Paste a UUID below to explore its full graph
{
  objectRelations(
    dataspace: "$DS"
    typeName: "resqml20.obj_FaultInterpretation"
    uuid: "PASTE-UUID-HERE"
    direction: "both"
  ) {
    uuid
    name
    typeName
    direction
    contentType
  }
}`,

  // ─── Deep Search ───────────────────────────────────────────────────
  deep_poro: `# Grid cells with porosity > 0.20 (reservoir quality cutoff)
# IMPOSSIBLE in OSDU catalog: catalog has no cell-level property values.
# deepSearch traverses: IjkGrid → attached ContinuousProperty → HDF5 arrays
# Returns statistics + fraction of cells passing the threshold.
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_IjkGridRepresentation"
    includeRelations: true
    includeStatistics: true
    propertyFilter: {
      kind: "porosity"
      arrayFilter: { operator: GT, threshold: 0.20 }
    }
    limit: 5
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title
      relations { uuid name typeName direction }
      properties {
        title kind uom
        statistics { count minValue maxValue mean stdDev }
        matchingCells { count total fraction }
      }
    }
  }
}`,
  deep_all_props: `# All properties attached to IjkGrid (porosity, perm, Sw, NTG, facies…)
# Shows the full property inventory for each grid representation.
# Graph traversal: IjkGrid ← ContinuousProperty/DiscreteProperty sources
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_IjkGridRepresentation"
    includeRelations: true
    includeStatistics: true
    limit: 5
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title
      relations { uuid name typeName direction }
      properties {
        title kind uom
        statistics { count minValue maxValue mean stdDev }
      }
    }
  }
}`,

  // ─── Surfaces & Arrays ─────────────────────────────────────────────
  deep_grid2d_arrays: `# Grid2D surfaces - full statistics + sample values for preview
# Only possible through RDDMS (HDF5 access), never in catalog search.
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_Grid2dRepresentation"
    includeRelations: true
    includeStatistics: true
    includeSampleValues: true
    limit: 10
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title
      relations { uuid name typeName direction }
      properties {
        title kind uom
        statistics { count minValue maxValue mean stdDev }
        arrays { path totalElements statistics { count minValue maxValue mean stdDev } sampleValues }
      }
    }
  }
}`,

  // ─── Stratigraphy ──────────────────────────────────────────────────
  strat_column: `# Strat column → ranks → units hierarchy
{
  col: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_StratigraphicColumn"
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

  // ─── Federated (Catalog + RDDMS) ────────────────────────────────────────
  fed_enrich: `# Federated + relations (horizons)
{
  federatedSearch(
    text: "*"
    dataspaces: $DS_LIST
    typeName: "resqml20.obj_HorizonInterpretation"
    searchCatalog: true
    searchRddms: true
    includeRelations: true
    limit: 10
  ) {
    totalCatalog totalLocalRddms totalMerged sources
    hits {
      uuid title typeName dataspace
      foundInCatalog foundInLocalRddms
      relations { uuid name typeName direction }
    }
  }
}`,
  // ─── Cross-System (impossible with just OSDU catalog search) ────────────
  xref_orphan_rddms: `# RDDMS orphans (not in catalog) vs catalog ghosts (not in RDDMS)
# Impossible with single-system search - requires comparing both
{
  federatedSearch(
    text: "$DS_NAME"
    kind: "osdu:wks:work-product-component--*:*"
    dataspaces: $DS_LIST
    searchCatalog: true
    searchRddms: true
    limit: 50
  ) {
    totalCatalog totalLocalRddms totalMerged sources
    hits {
      uuid title typeName dataspace
      foundInCatalog foundInLocalRddms
      osduId
    }
  }
}`,
  xref_grid_poro_perm: `# FEDERATED: Grid zones with porosity > 0.15 AND permeability stats
# WHY THIS IS UNIQUE:
#   - OSDU catalog: knows grids exist, but has NO cell values
#   - RDDMS alone: has arrays, but no business metadata (who approved, project)
#   - Federated GraphQL: catalog metadata + RDDMS numerical arrays + graph
#
# This query finds IjkGrid representations, filters by porosity > 0.15,
# and returns BOTH catalog metadata (OSDU ID, kind) AND property statistics.
# The Drogon model has grids with PORO, PERMX, Sw, NTG, FACIES properties.
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
    propertyFilter: {
      kind: "porosity"
      arrayFilter: { operator: GT, threshold: 0.15 }
    }
    limit: 5
  ) {
    totalCatalog totalLocalRddms totalMerged sources
    hits {
      uuid title typeName dataspace
      foundInCatalog foundInLocalRddms
      osduId osduKind
      relations { uuid name typeName direction }
      properties {
        title kind uom
        statistics { count minValue maxValue mean stdDev }
        matchingCells { count total fraction }
      }
    }
  }
}`,
  xref_well_grid_props: `# FEDERATED: Wells + their grid-intersecting properties
# Finds WellboreTrajectory objects in RDDMS, shows which grid properties
# (PORO, PERMX) are attached to grids that the well penetrates.
# 
# Step 1: This query finds well trajectories with their RESQML graph
# Step 2: The relations show which IjkGrid the blocked well references
#
# OSDU catalog cannot answer: "which grid cells does this well pass through?"
# Only RDDMS topology graph knows the BlockedWellbore→IjkGrid link.
{
  wells: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_WellboreTrajectoryRepresentation"
    includeRelations: true
    limit: 10
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title
      relations { uuid name typeName direction }
    }
  }
  grids: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_IjkGridRepresentation"
    includeRelations: true
    includeStatistics: true
    propertyFilter: { kind: "porosity" }
    limit: 5
  ) {
    totalMatched
    objects {
      uuid title
      relations { uuid name typeName direction }
      properties {
        title kind uom
        statistics { count minValue maxValue mean stdDev }
      }
    }
  }
}`,

  // ─── FIRP Hierarchy (Feature→Interp→Rep→Property) ─────────────────────
  struct_features_to_reps: `# FIRP: BoundaryFeature → Interpretation → Representations
# Traverses the full RESQML hierarchy from geological concepts down
# to spatial data objects (Grid2D, PolylineSet, PointSet)
{
  features: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_GeneticBoundaryFeature"
    includeRelations: true
    limit: 10
  ) {
    totalMatched
    objects {
      uuid title typeName
      relations { uuid name typeName direction }
    }
  }
  faultFeatures: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_TectonicBoundaryFeature"
    includeRelations: true
    limit: 10
  ) {
    totalMatched
    objects {
      uuid title typeName
      relations { uuid name typeName direction }
    }
  }
}`,

  // ─── Numerical Properties (3D grid cell values) ───────────────────────
  markers_by_horizon: `# Wellbore markers grouped by the horizon/feature they pick
# Each marker frame ties a well to a stratigraphic surface - the
# relations show which GeneticBoundaryFeature (horizon) is picked.
# Results are renderable in 3D as bedding-disk markers along trajectories.
#
# HOW TO READ: Each object is a WellboreMarkerFrameRepresentation - one
# per well. Its relations list the horizons (GeneticBoundaryFeature) that
# the well penetrates. Compare relations across wells to see which
# horizons are picked consistently and which are missing (eroded/faulted out).
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_WellboreMarkerFrameRepresentation"
    includeRelations: true
    limit: 20
  ) {
    backend totalScanned totalMatched queryDescription
    objects {
      uuid title typeName
      relations { uuid name typeName direction contentType }
    }
  }
}`,

  // ─── WITSML (1 preset: browse + graph) ────────────────────────────────
  witsml_browse_wells: `# WITSML well hierarchy + relations
{
  wells: deepSearch(
    $DS_ARG
    typeName: "witsml21.Well"
    includeRelations: true
    limit: 15
  ) {
    backend totalScanned totalMatched
    objects {
      uuid title typeName
      relations { uuid name typeName direction }
    }
  }
  wellbores: deepSearch(
    $DS_ARG
    typeName: "witsml21.Wellbore"
    includeRelations: true
    limit: 15
  ) {
    totalMatched
    objects {
      uuid title typeName
      relations { uuid name typeName direction }
    }
  }
}`,

  // ─── Native RDDMS GraphQL (M27+) ─────────────────────────────────────
  // These queries use the native ETP-backed GraphQL endpoint on the RDDMS
  // etp-client (M27 release). They expose capabilities beyond REST:
  //   • True graph traversal with edges (not just relations)
  //   • Full object content (parsed XML→JSON)
  //   • Array metadata and dimensions
  //   • Batch graph search across multiple URIs in one call
  //
  // Requires: RDDMS etp-client with /graphql endpoint (M27+).
  // Falls back to REST automatically if native GQL is unavailable.

  native_graph_traverse: `# NATIVE GQL (M27+): Full graph traversal with edges
# Unlike objectRelations (flat list), this returns a true graph structure
# with directed edges - enabling visualization of RESQML topology.
# The depth parameter controls how many hops to traverse.
#
# Requires: local etp-client with /graphql endpoint (M27 release)
# Fallback: REST-based simplified graph (nodes + target edges only)
{
  nativeGraphSearch(
    dataspace: "$DS"
    typeName: "resqml20.obj_IjkGridRepresentation"
    depth: 2
    limit: 3
  ) {
    backend
    resources {
      uri name dataObjectType
      sourceCount targetCount
      lastChanged activeStatus
    }
    edges {
      sourceUri targetUri
    }
  }
}`,

  native_object_content: `# NATIVE GQL (M27+): Full object content as JSON
# Fetches the complete parsed RESQML/EML XML as a JSON tree via ETP Store.
# Use to inspect Citation, CRS references, geometry params, property kinds.
#
# Step 1: Get a UUID from "Browse objects" preset
# Step 2: Paste it below to see the full object body
#
# Requires: local etp-client with /graphql endpoint (M27 release)
# Fallback: REST $format=json (similar but not identical structure)
{
  nativeObjectContent(
    dataspace: "$DS"
    typeName: "resqml20.obj_IjkGridRepresentation"
    limit: 1
  ) {
    uri name dataObjectType
    content
  }
}`,

  native_array_metadata: `# NATIVE GQL (M27+): Array dimensions & types without downloading data
# Shows what arrays exist inside a resource (grid geometry, property values)
# with their shape, logical type, and last-write timestamp - without
# actually downloading the (potentially GB-sized) array payload.
#
# Requires: local etp-client with /graphql endpoint (M27 release)
# Fallback: REST array listing (paths only, no dimensions/types)
{
  nativeArrayMetadata(
    dataspace: "$DS"
    typeName: "resqml20.obj_IjkGridRepresentation"
    limit: 2
  ) {
    uri name
    arrays {
      pathInResource
      dimensions
      logicalArrayType
      storeLastWrite
    }
  }
}`,

  // ─── Field Development Queries ─────────────────────────────────────────
  // These presets combine spatial topology, properties, and production
  // to answer real subsurface questions for field development workflows.

  field_bypassed_oil: `# FIELD DEV: Bypassed oil screening - compound cell intersection
# Finds grid cells where BOTH conditions are true simultaneously:
#   Water Saturation < 0.4  (oil still in place - not swept)
#   Horizontal Permeability > 100 mD  (permeable enough to produce)
#
# The compoundFilter ANDs the criteria at cell level and returns
# the intersection count - the actual bypassed oil cell set.
# Individual property stats are also shown for context.
#
# HOW TO READ: Each object is an IjkGrid (the 3D geocellular model).
# compoundMatch shows how many cells pass ALL filters simultaneously -
# these are the bypassed-oil sweet spots. The fraction tells you what
# share of the reservoir is prospective. Each property under the grid
# shows its full statistics so you can gauge the overall distribution.
{
  deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_IjkGridRepresentation"
    includeStatistics: true
    compoundFilter: {
      filters: [
        { titleContains: "Water Saturation", arrayFilter: { operator: LT, threshold: 0.4 } }
        { titleContains: "Horizontal Permeability", arrayFilter: { operator: GT, threshold: 100.0 } }
      ]
    }
    limit: 5
  ) {
    backend totalScanned totalMatched
    compoundMatch { count total fraction }
    warnings
    objects {
      uuid title
      properties {
        title kind uom
        statistics { count minValue maxValue mean stdDev }
      }
    }
  }
}`,

  field_water_breakthrough: `# FIELD DEV: Water breakthrough diagnosis - per-well log overview
# Shows ALL log properties on each wellbore frame so you can see
# Horizontal Permeability, Water Saturation, Total Porosity, Shale Volume together.
#
# High-perm streaks (Horizontal Permeability > 500 mD) can act as water conduits.
# Wells where high-perm cells overlap with high Sw = water breakthrough.
# Relations identify which wellbore each log frame belongs to.
#
# Fault connections show inter-segment transmissibility -
# a high-perm well near a conductive fault is the likely breakthrough path.
#
# HOW TO READ: allWellLogs lists every well's log frame with all its
# properties - compare mean Sw across wells to spot which are watering out.
# highPermStreaks shows only frames where Horizontal Permeability > 500 mD; matchingCells
# tells you what fraction of each well's log is high-perm streak.
# faultConnections lists inter-segment links; their transmissibility
# properties tell you if water can cross from injector to producer segments.
{
  allWellLogs: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_WellboreFrameRepresentation"
    includeStatistics: true
    includeRelations: true
    limit: 14
  ) {
    backend totalScanned totalMatched
    objects {
      uuid title
      relations { name typeName direction }
      properties {
        title kind uom
        statistics { count minValue maxValue mean }
      }
    }
  }
  highPermStreaks: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_WellboreFrameRepresentation"
    includeStatistics: true
    includeRelations: true
    propertyFilter: {
      titleContains: "Horizontal Permeability"
      arrayFilter: { operator: GT, threshold: 500.0 }
    }
    limit: 14
  ) {
    totalMatched
    objects {
      uuid title
      relations { name typeName direction }
      properties {
        title
        matchingCells { count total fraction }
      }
    }
  }
  faultConnections: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_GridConnectionSetRepresentation"
    includeRelations: true
    includeStatistics: true
    limit: 5
  ) {
    totalMatched
    objects {
      uuid title
      relations { name typeName direction }
      properties { title kind statistics { mean minValue maxValue } }
    }
  }
}`,

  field_injection_support: `# FIELD DEV: Verify injection support across faults
# Checks if injection from A-5 (CentralHorst) reaches producers in other
# segments. Combines fault geometry with well trajectory topology.
#
# Expected result: A-1/A-2 (same segment) get pressure support.
# A-3 (EastLowland, across F2 baffle) does NOT - pressure declining.
#
# HOW TO READ: Each fault object's relations show the horizons it cuts.
# structuralOrg ties faults into named segments. wells lists trajectories
# whose relations reveal which grid/segment each well penetrates.
# Cross-reference: if two wells share relations to the same segment but
# a fault with "baffle" or "seal" character sits between, injection
# support is limited - that's your pressure-decline explanation.
{
  faults: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_FaultInterpretation"
    includeRelations: true
    limit: 10
  ) {
    backend totalScanned totalMatched
    objects {
      uuid title typeName
      relations { uuid name typeName direction }
    }
  }
  structuralOrg: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_StructuralOrganizationInterpretation"
    includeRelations: true
    limit: 5
  ) {
    totalMatched
    objects {
      uuid title
      relations { uuid name typeName direction }
    }
  }
  wells: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_WellboreTrajectoryRepresentation"
    titleContains: "Drilled"
    includeRelations: true
    limit: 12
  ) {
    totalMatched
    objects {
      uuid title
      relations { name typeName direction }
    }
  }
}`,

  field_completion_ntg: `# FIELD DEV: Completion optimization - best pay intervals per well
# Finds well log intervals with good porosity and permeability
# (the "pay zone") for completion/perforation design.
#
# Properties: Total Porosity, Horizontal Permeability, Shale Volume, Water Saturation
# Filter: Total Porosity > 0.15 and Horizontal Permeability > 100 identify net pay.
# Low Water Saturation (< 0.3) confirms the interval is above the OWC.
# Relations show which wellbore each log belongs to.
#
# HOW TO READ: Each sub-query returns the same well log frames filtered
# differently. matchingCells.fraction is the key metric - it tells you
# what share of each well's log passes the threshold. A well that scores
# high on all three (good porosity, good perm, low Sw) is the best
# completion candidate. Compare fractions across wells to rank them.
{
  payPorosity: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_WellboreFrameRepresentation"
    includeStatistics: true
    includeRelations: true
    propertyFilter: {
      titleContains: "Total Porosity"
      arrayFilter: { operator: GT, threshold: 0.15 }
    }
    limit: 14
  ) {
    backend totalScanned totalMatched
    objects {
      uuid title
      relations { name typeName direction }
      properties {
        title kind uom
        statistics { count minValue maxValue mean }
        matchingCells { count total fraction }
      }
    }
  }
  payPerm: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_WellboreFrameRepresentation"
    includeStatistics: true
    includeRelations: true
    propertyFilter: {
      titleContains: "Horizontal Permeability"
      arrayFilter: { operator: GT, threshold: 100.0 }
    }
    limit: 14
  ) {
    totalMatched
    objects {
      uuid title
      relations { name typeName direction }
      properties {
        title statistics { mean maxValue }
        matchingCells { count total fraction }
      }
    }
  }
  aboveOwc: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_WellboreFrameRepresentation"
    includeStatistics: true
    includeRelations: true
    propertyFilter: {
      titleContains: "Water Saturation"
      arrayFilter: { operator: LT, threshold: 0.3 }
    }
    limit: 14
  ) {
    totalMatched
    objects {
      uuid title
      relations { name typeName direction }
      properties {
        title statistics { mean }
        matchingCells { count total fraction }
      }
    }
  }
}`,

  field_segment_ranking: `# FIELD DEV: Segment overview for infill targeting
# Shows fault-bounded segments and what's in each one:
#   1. Faults - segment boundaries with names (F1–F6)
#   2. Structural organization - how faults group into segments
#   3. Grid connections - inter-segment links across faults
#   4. Wells - trajectory relations show which segment each well sits in
#
# Cross-reference fault names with well relations to see
# which segments are drained vs. undrained for infill candidates.
#
# HOW TO READ: faults lists each named fault (F1–F6) with its horizon
# relations. structuralOrg shows how faults and horizons are grouped into
# segments. gridConnections lists cross-fault cell links - their property
# statistics (transmissibility) tell you if segments communicate.
# wells shows each trajectory and its relations to grids/wellbores.
# A segment with no wells but connected to a producing segment via
# a conductive fault is your top infill target.
{
  faults: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_FaultInterpretation"
    includeRelations: true
    limit: 10
  ) {
    backend totalScanned totalMatched
    objects {
      uuid title typeName
      relations { uuid name typeName direction }
    }
  }
  structuralOrg: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_OrganizationFeature"
    includeRelations: true
    limit: 5
  ) {
    totalMatched
    objects {
      uuid title typeName
      relations { uuid name typeName direction }
    }
  }
  gridConnections: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_GridConnectionSetRepresentation"
    includeRelations: true
    includeStatistics: true
    limit: 5
  ) {
    totalMatched
    objects {
      uuid title typeName
      relations { uuid name typeName direction }
      properties {
        title kind uom
        statistics { count minValue maxValue mean }
      }
    }
  }
  wells: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_WellboreTrajectoryRepresentation"
    titleContains: "Drilled"
    includeRelations: true
    limit: 18
  ) {
    totalMatched
    objects {
      uuid title
      relations { name typeName direction }
    }
  }
}`
};

// ── REST-friendly presets (no arrayFilter / compoundFilter) ──────────
// These work on any backend including REST-only instances.
GQL_PRESETS.field_grid_inventory = `# FIELD DEV: Grid property inventory (REST-compatible)
# Lists ALL properties on the IjkGrid geocellular model with their
# kind, unit of measure, and statistics (when available).
#
# Works on both REST and PostgreSQL backends.
# On REST: shows property names, kinds, and UOMs (statistics null).
# On PG: also includes min/max/mean/stdDev for each property.
#
# HOW TO READ: Each property listed under the grid is a 3D cell array.
# The "kind" tells you what physical quantity it represents (porosity,
# permeability, saturation, etc.). Use this inventory to plan which
# properties to filter on in compound queries.
{
  grids: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_IjkGridRepresentation"
    includeStatistics: true
    includeRelations: true
    limit: 2
  ) {
    backend totalScanned totalMatched warnings
    objects {
      uuid title typeName
      relations { uuid name typeName direction }
      properties {
        title kind uom
        statistics { count minValue maxValue mean stdDev }
      }
    }
  }
  wellLogs: deepSearch(
    $DS_ARG
    typeName: "resqml20.obj_WellboreFrameRepresentation"
    includeStatistics: true
    includeRelations: true
    limit: 3
  ) {
    totalScanned totalMatched
    objects {
      uuid title
      relations { name typeName direction }
      properties { title kind uom }
    }
  }
}`;

function gqlSelectedDataspaces() {
  return Array.from(dsSel.selectedOptions).map(o => o.value);
}

let _lastUsedDs = '';

function gqlCurrentDs() {
  // Returns first selected for single-dataspace presets
  const sel = gqlSelectedDataspaces();
  if (sel.length > 0) {
    _lastUsedDs = sel[0];
    return sel[0];
  }
  // Fall back to last used dataspace (avoids "default" after deselection)
  return _lastUsedDs || 'default';
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

  // Show preset explanation tooltip (extracted from # comment lines)
  const tooltip = document.getElementById('gql-preset-tooltip');
  if (tooltip) {
    const lines = tpl.split('\n');
    const comments = lines
      .filter(l => l.trim().startsWith('#'))
      .map(l => l.trim().replace(/^#\s?/, ''));
    if (comments.length > 0) {
      tooltip.textContent = comments.join('\n');
      tooltip.style.display = 'block';
    } else {
      tooltip.style.display = 'none';
    }
  }
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
      gqlStatus.textContent = `Done(${data.errors.length} error(s))`;
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
      wrap.innerHTML = `< button class="btn-show3d-results" id = "gql3d-adv-trigger" >
  <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>
            Show 3D Results(${renderableObjs.length})
          </button >
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
(function () {
  const savedSel = $('gql-saved-select');
  const saveBtn = $('gql-save-query');
  const delBtn = $('gql-delete-query');
  if (!savedSel) return;

  // Load saved queries on page load
  fetch('/api/queries?source=graphql')
    .then(r => r.json())
    .then(function (list) {
      (list || []).forEach(function (sq) {
        const opt = document.createElement('option');
        opt.value = sq.id;
        opt.dataset.query = sq.query;
        opt.textContent = sq.name;
        savedSel.appendChild(opt);
      });
    })
    .catch(function () { });

  // Apply saved query on select
  savedSel.addEventListener('change', function () {
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
    delBtn.addEventListener('click', function () {
      const qid = savedSel.value;
      if (!qid) return;
      if (!confirm('Delete this saved query?')) return;
      fetch('/api/queries/' + qid, { method: 'DELETE' })
        .then(r => r.json())
        .then(function () {
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
    saveBtn.addEventListener('click', function () {
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
        .then(function (data) {
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

function _sanitize(s) { return (s || '').replace(/["<>`]/g, '').replace(/[\[\](){}#&;|]/g, ' ').replace(/\s+/g, ' ').trim().substring(0, 50); }
function _shortType(t) { return (t || '').replace(/^(resqml|witsml|eml)\d+\.obj_/i, '').replace(/^(resqml|witsml|eml)\d+\./i, '').replace(/application.*\./g, ''); }
function _nodeId(uuid) { return 'n' + (uuid || 'x').replace(/[^a-zA-Z0-9]/g, '').substring(0, 12); }

function buildMermaidFromRelations(data) {
  // object_relations response (top-level or aliased)
  const rels = _findField(data.data, 'objectRelations');
  if (!rels || !rels.length) return '';
  // Try to get the queried object's name and type from the UUID field
  const ezUuid = $('ez-uuid') ? $('ez-uuid').value.trim() : '';
  const ezType = $('ez-type') ? $('ez-type').value : '';
  const centerType = _sanitize(_shortType(ezType));
  // Look for a title from browse results cache (if available)
  let centerLabel = centerType || 'Query Object';
  if (ezUuid) centerLabel = _sanitize(ezUuid.substring(0, 8)) + ' : ' + centerLabel;
  const lines = ['graph LR'];
  const centerId = 'center';
  lines.push(`  ${centerId}["${centerLabel}"]:::cls_center`);
  // Group by direction for layout
  const targets = rels.filter(r => r.direction === 'target');
  const sources = rels.filter(r => r.direction === 'source');
  targets.forEach((r, i) => {
    const nid = _nodeId(r.uuid) + 't' + i;
    const label = _sanitize(r.name) || _sanitize(_shortType(r.typeName || r.type_name));
    const stype = _sanitize(_shortType(r.typeName || r.type_name));
    lines.push(`  ${nid}["${label} : ${stype}"]`);
    lines.push(`  ${centerId} -->|target| ${nid}`);
  });
  sources.forEach((r, i) => {
    const nid = _nodeId(r.uuid) + 's' + i;
    const label = _sanitize(r.name) || _sanitize(_shortType(r.typeName || r.type_name));
    const stype = _sanitize(_shortType(r.typeName || r.type_name));
    lines.push(`  ${nid}["${label} : ${stype}"]`);
    lines.push(`  ${nid} -->|source| ${centerId}`);
  });
  lines.push('  classDef cls_center fill:#fff3e0,stroke:#ff9800,stroke-width:2px,color:#e65100');
  return lines.join('\n');
}

function buildMermaidFromDeepSearch(data) {
  // deep_search response (top-level or any aliased field with .objects[].relations)
  const ds = _findDeepSearchResult(data.data);
  if (!ds) return '';
  if (ds.length > 200) {
    console.warn('Mermaid: skipping diagram for', ds.length, 'objects (max 200)');
    return '';
  }
  const lines = ['graph TD'];
  ds.forEach((obj, oi) => {
    const oid = _nodeId(obj.uuid) + oi;
    const oLabel = _sanitize(obj.title) || (obj.uuid || '').substring(0, 8);
    const oType = _sanitize(_shortType(obj.typeName || obj.type_name || ''));
    lines.push(`  ${oid}["${oLabel} : ${oType}"]`);
    if (obj.relations && obj.relations.length) {
      obj.relations.forEach((r, ri) => {
        const rid = oid + 'r' + ri;
        const rLabel = _sanitize(r.name) || (r.uuid || '').substring(0, 8);
        const rType = _sanitize(_shortType(r.typeName || r.type_name || ''));
        lines.push(`  ${rid}["${rLabel} : ${rType}"]`);
        if (r.direction === 'target') {
          lines.push(`  ${oid} -->|target| ${rid}`);
        } else {
          lines.push(`  ${rid} -->|source| ${oid}`);
        }
      });
    }
    if (obj.properties && obj.properties.length) {
      obj.properties.forEach((p, pi) => {
        const pid = oid + 'p' + pi;
        const pLabel = _sanitize(p.title || p.kind || 'prop');
        const kind = _sanitize(p.kind || '');
        const stats = p.statistics ? `min=${p.statistics.minValue?.toFixed(2) ?? '?'} max=${p.statistics.maxValue?.toFixed(2) ?? '?'}` : '';
        const detail = [kind, stats].filter(Boolean).join(' ');
        lines.push(`  ${pid}(["${pLabel} ${detail}"])`);
        lines.push(`  ${pid} -.->|property| ${oid}`);
      });
    }
  });
  return lines.join('\n');
}

function buildMermaidFromFederated(data) {
  // federatedSearch response (top-level or aliased)
  const fs = _findField(data.data, 'federatedSearch');
  if (!fs || !fs.hits || !fs.hits.length) return '';
  if (fs.hits.length > 200) {
    console.warn('Mermaid: skipping diagram for', fs.hits.length, 'hits (max 200)');
    return '';
  }
  const lines = ['graph TD'];
  fs.hits.forEach((hit, hi) => {
    const hid = _nodeId(hit.uuid) + hi;
    const hLabel = _sanitize(hit.title) || (hit.uuid || '').substring(0, 8);
    const hType = _sanitize(_shortType(hit.typeName || ''));
    let flags = '';
    if (hit.foundInCatalog) flags += ' C';
    if (hit.foundInLocalRddms) flags += ' R';
    lines.push(`  ${hid}["${hLabel} : ${hType}${flags}"]`);
    if (hit.relations && hit.relations.length) {
      hit.relations.forEach((r, ri) => {
        const rid = hid + 'r' + ri;
        const rLabel = _sanitize(r.name) || (r.uuid || '').substring(0, 8);
        const rType = _sanitize(_shortType(r.typeName || ''));
        lines.push(`  ${rid}["${rLabel} : ${rType}"]`);
        if (r.direction === 'target') {
          lines.push(`  ${hid} -->|target| ${rid}`);
        } else {
          lines.push(`  ${rid} -->|source| ${hid}`);
        }
      });
    }
  });
  return lines.join('\n');
}

function buildMermaidFromResqmlObjects(data) {
  const objs = data.data && (data.data.resqmlObjects || data.data.resourceTypes);
  if (!objs || !objs.length || objs.length > 30) return '';
  if (data.data.resourceTypes) {
    const lines = ['graph LR'];
    lines.push('  DS["Dataspace"]');
    objs.forEach((t, i) => {
      const nid = 'type' + i;
      lines.push(`  ${nid}["${_sanitize(_shortType(t.name))} : ${t.count} objects"]`);
      lines.push(`  DS --- ${nid}`);
    });
    return lines.join('\n');
  }
  return '';
}

// Helper: find a field in data by key name (handles aliased GraphQL fields)
function _findField(d, fieldName) {
  if (!d) return null;
  if (d[fieldName]) return d[fieldName];
  // Check all keys for aliased versions
  for (const key of Object.keys(d)) {
    const val = d[key];
    if (val && typeof val === 'object') {
      // federatedSearch has .hits, objectRelations is array
      if (fieldName === 'federatedSearch' && val.hits) return val;
      if (fieldName === 'objectRelations' && Array.isArray(val) && val.length > 0 && val[0].direction) return val;
    }
  }
  return null;
}

// Helper: find deepSearch-style results (any field with .objects[] containing relations or properties)
function _findDeepSearchResult(d) {
  if (!d) return null;
  // Direct deepSearch field
  if (d.deepSearch && d.deepSearch.objects && d.deepSearch.objects.length) return d.deepSearch.objects;
  // Search all fields for deepSearch-like structure
  let allObjects = [];
  for (const key of Object.keys(d)) {
    const val = d[key];
    if (val && val.objects && Array.isArray(val.objects) && val.objects.length > 0) {
      allObjects = allObjects.concat(val.objects);
    }
  }
  return allObjects.length > 0 ? allObjects : null;
}

async function renderMermaidFromResponse(data) {
  if (!data || !data.data) { _lastMermaidCode = ''; return; }
  let code = buildMermaidFromRelations(data)
    || buildMermaidFromDeepSearch(data)
    || buildMermaidFromFederated(data)
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
    console.warn('Mermaid render error:', e.message);
    gqlMermaid.innerHTML = `<pre style="color:#a80000;font-size:12px;">Diagram error: ${e.message.substring(0, 200)}</pre>`;
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
