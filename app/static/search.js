/* search.js — extracted from search.html */

/* ── Inline results: BD map, DDMS map, volume histograms ── */
    /* ── Shared HTML escape helper ── */
    function escHtml(s) {
      if (s == null) return '';
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    /* ── BD map selector (switch between maps in the dataspace) ── */
    window.switchBdMap = function(sel, recIdx) {
      var opt = sel.options[sel.selectedIndex];
      var ds = opt.dataset.ds;
      var uuid = opt.dataset.uuid;
      var title = opt.dataset.title;
      var dsname = opt.dataset.dsname;

      /* Update dataspace badge */
      var badge = document.getElementById('bd-map-dsname-' + recIdx);
      if (badge) badge.textContent = dsname;

      /* Show loading spinner */
      var imgDiv = document.getElementById('bd-map-img-' + recIdx);
      if (!imgDiv) return;
      imgDiv.innerHTML = '<div style="text-align:center;padding:2rem;color:#718096;"><span class="spinner" style="display:inline-block;width:18px;height:18px;border:2px solid #cbd5e0;border-top-color:#4299e1;border-radius:50%;animation:spin .7s linear infinite;"></span> Loading map&hellip;</div>';

      var src = '/keys/object/map.png?ds=' + encodeURIComponent(ds) + '&uuid=' + encodeURIComponent(uuid) + '&w=12&h=8&dpi=100';
      var ctrl = new AbortController();
      var timer = setTimeout(function() { ctrl.abort(); }, 90000);

      fetch(src, { signal: ctrl.signal })
        .then(function(resp) {
          clearTimeout(timer);
          if (!resp.ok) {
            return resp.text().then(function(body) {
              try { body = JSON.parse(body).detail || body; } catch(_){}
              throw new Error('Server ' + resp.status + ': ' + body);
            });
          }
          return resp.blob();
        })
        .then(function(blob) {
          var url = URL.createObjectURL(blob);
          imgDiv.innerHTML = '';
          var img = new Image();
          img.src = url;
          img.alt = 'Map: ' + title;
          img.style.cssText = 'max-width:100%;border-radius:6px;border:1px solid #e2e8f0;';
          imgDiv.appendChild(img);
        })
        .catch(function(err) {
          clearTimeout(timer);
          var msg = err.name === 'AbortError' ? 'Timed out after 90s' : (err.message || 'Unknown error');
          var safe = msg.replace(/</g, '&lt;').replace(/>/g, '&gt;');
          imgDiv.innerHTML = '<div style="color:#e53e3e;font-size:.85rem;padding:.5rem;">Failed to load map: ' + safe + '</div>';
        });

      /* Update links */
      var linksDiv = document.getElementById('bd-map-links-' + recIdx);
      if (linksDiv) {
        linksDiv.innerHTML = '<code>/keys/object/map.png?ds=' + ds + '&amp;uuid=' + uuid + '</code>' +
          ' <a href="/keys/object/map.json?ds=' + encodeURIComponent(ds) + '&uuid=' + encodeURIComponent(uuid) + '" target="_blank" style="margin-left:.5rem;font-size:.72rem;">JSON ↗</a>' +
          ' <a href="/keys?ds=' + encodeURIComponent(ds) + '" style="margin-left:.5rem;font-size:.72rem;">Browse dataspace →</a>';
      }
    };

    /* ── DDMS map lazy loader ── */
    window.loadDdmsMap = function(btn) {
      const section = btn.closest('.ddms-map-section');
      if (!section) return;
      const ds = section.dataset.ds;
      const uuid = section.dataset.uuid;
      const status = section.querySelector('.ddms-map-status');
      const placeholder = section.querySelector('.ddms-map-placeholder');
      status.textContent = 'Fetching surface from RDDMS (may take a few seconds)…';
      btn.disabled = true;

      const src = '/keys/object/map.png?ds=' + encodeURIComponent(ds) + '&uuid=' + encodeURIComponent(uuid) + '&w=12&h=8&dpi=100';
      const ctrl = new AbortController();
      const timer = setTimeout(function() { ctrl.abort(); }, 90000);

      fetch(src, { signal: ctrl.signal })
        .then(function(resp) {
          clearTimeout(timer);
          if (!resp.ok) {
            return resp.text().then(function(body) {
              /* Try to extract JSON detail */
              try { body = JSON.parse(body).detail || body; } catch(_){}
              throw new Error('Server ' + resp.status + ': ' + body);
            });
          }
          return resp.blob();
        })
        .then(function(blob) {
          const url = URL.createObjectURL(blob);
          const img = new Image();
          img.src = url;
          img.alt = 'Map';
          img.style.cssText = 'max-width:100%;border-radius:6px;border:1px solid #e2e8f0;';
          placeholder.innerHTML = '';
          placeholder.appendChild(img);
          status.textContent = '';
        })
        .catch(function(err) {
          clearTimeout(timer);
          if (err.name === 'AbortError') {
            status.textContent = 'Timed out after 90s - try from the Resources page with lower DPI.';
          } else {
            status.textContent = 'Map failed: ' + err.message;
          }
          btn.disabled = false;
        });
    };

    /* ── Volume histogram popup ── */
    (function(){
      let activeModal = null;
      let activeChart = null;

      window.openJsonModal = function(btn) {
        const section = btn.closest('.section-card');
        if (!section) return;
        const dataEl = section.querySelector('.rec-json-data');
        if (!dataEl) return;
        let pretty;
        try {
          pretty = JSON.stringify(JSON.parse(dataEl.textContent), null, 2);
        } catch (e) {
          pretty = dataEl.textContent;
        }
        if (activeModal) { activeModal.remove(); activeModal = null; }
        const overlay = document.createElement('div');
        overlay.className = 'vol-modal-overlay';
        overlay.innerHTML = `
          <div class="vol-modal" style="max-width:56rem;">
            <button class="vol-modal-close" title="Close">&times;</button>
            <h4>Full Record JSON</h4>
            <div class="json-modal-toolbar">
              <button onclick="(function(b){var t=b.closest('.vol-modal').querySelector('pre').textContent;navigator.clipboard.writeText(t).then(function(){b.textContent='Copied!';setTimeout(function(){b.textContent='Copy';},1500);});})(this)">Copy</button>
            </div>
            <pre class="json-modal-pre"></pre>
          </div>`;
        overlay.querySelector('pre').textContent = pretty;
        overlay.querySelector('.vol-modal-close').onclick = function() { overlay.remove(); activeModal = null; };
        overlay.addEventListener('click', function(e) { if (e.target === overlay) { overlay.remove(); activeModal = null; } });
        document.body.appendChild(overlay);
        activeModal = overlay;
      };

      window.openVolHistogram = function(btn) {
        const section = btn.closest('.section-card');
        if (!section) return;

        // ── Read data from embedded JSON (full data, not truncated DOM) ──
        const dataEl = section.querySelector('.vol-full-data');
        let headers = [], keyNameSet = new Set(), allRows = [];
        if (dataEl) {
          try {
            const d = JSON.parse(dataEl.textContent);
            headers = d.headers || [];
            (d.keyNames || []).forEach(k => keyNameSet.add(k));
            allRows = d.rows || [];
          } catch(e) { /* fall through to DOM */ }
        }
        // Fallback: parse DOM table
        if (!headers.length) {
          const tbl = section.querySelector('table.vol-data-table');
          if (!tbl) return;
          headers = Array.from(tbl.querySelectorAll('tr:first-child th')).map(th => th.textContent.trim());
          const domRows = Array.from(tbl.querySelectorAll('tr')).slice(1);
          domRows.forEach(r => {
            if (r.classList.contains('vol-ellipsis-row')) return;
            allRows.push(Array.from(r.cells).map(c => {
              const t = c.textContent.trim(); const n = parseFloat(t); return isNaN(n) ? t : n;
            }));
          });
          // Heuristic: columns without a dot are keys
          headers.forEach(h => { if (!h.includes('.')) keyNameSet.add(h); });
        }
        if (!headers.length || !allRows.length) return;

        // Classify key vs value columns
        const keyCols = [], valCols = [];
        headers.forEach((h, i) => {
          if (keyNameSet.has(h)) keyCols.push({name: h, idx: i});
          else valCols.push({name: h, idx: i});
        });
        if (!valCols.length) { alert('No numeric volume columns found.'); return; }

        // Build segment labels + column data
        const segments = [];
        const colData = {};
        valCols.forEach(c => { colData[c.name] = []; });
        allRows.forEach((row, ri) => {
          const segParts = keyCols.map(k => row[k.idx] != null ? String(row[k.idx]) : '').filter(Boolean);
          segments.push(segParts.join(' / ') || ('Row ' + (ri + 1)));
          valCols.forEach(c => {
            colData[c.name].push(typeof row[c.idx] === 'number' ? row[c.idx] : (parseFloat(row[c.idx]) || 0));
          });
        });

        // Group columns by fluid (Oil, Gas, etc.)
        const groups = {};
        valCols.forEach(c => {
          const parts = c.name.split('.');
          const fluid = parts.length > 1 ? parts[0] : 'Value';
          const stat = parts.length > 1 ? parts.slice(1).join('.') : c.name;
          if (!groups[fluid]) groups[fluid] = [];
          groups[fluid].push({stat, col: c.name});
        });

        // Build modal
        if (activeModal) { activeModal.remove(); activeModal = null; }
        if (activeChart) { activeChart.destroy(); activeChart = null; }

        const overlay = document.createElement('div');
        overlay.className = 'vol-modal-overlay';
        overlay.addEventListener('click', e => { if (e.target === overlay) closeVolModal(); });

        const modal = document.createElement('div');
        modal.className = 'vol-modal';

        // Fluid selector
        const fluidNames = Object.keys(groups);
        // Default to 'Oil' if present, else first
        const defaultFluid = fluidNames.includes('Oil') ? 'Oil' : fluidNames[0];
        let controlsHTML = '<div class="vol-chart-controls">';
        controlsHTML += '<label>Fluid: <select id="volFluidSel">';
        fluidNames.forEach(f => {
          controlsHTML += '<option value="' + f + '"' + (f===defaultFluid?' selected':'') + '>' + f + '</option>';
        });
        controlsHTML += '</select></label>';
        controlsHTML += '<label style="margin-left:auto;"><input type="checkbox" id="volLogScale"> Log scale</label>';
        controlsHTML += '</div>';

        modal.innerHTML = '<button class="vol-modal-close" onclick="closeVolModal()" title="Close">&times;</button>'
          + '<h4>Volume Histogram - per Segment</h4>'
          + controlsHTML
          + '<div class="vol-chart-wrap"><canvas id="volHistCanvas"></canvas></div>';

        overlay.appendChild(modal);
        document.body.appendChild(overlay);
        activeModal = overlay;

        // Esc key to close
        const escHandler = e => { if (e.key === 'Escape') closeVolModal(); };
        document.addEventListener('keydown', escHandler);
        overlay._escHandler = escHandler;

        // Color: one hue per fluid, dark→light by statistic
        // Base HSL hues per fluid property
        const fluidHSL = {
          'Oil':              [28, 82],   // warm orange
          'Gas':              [153, 55],  // green
          'Total':            [211, 65],  // blue
          'AssociatedLiquid': [263, 55],  // purple
          'AssociatedGas':    [0, 55],    // red
          'BulkOil':          [35, 60],   // tan-orange
          'BulkGas':          [145, 45],  // sage green
          'PoreOil':          [30, 50],   // muted orange
          'PoreGas':          [155, 40],  // muted green
          'HydrocarbonPoreOil': [20, 55], // rust
          'HydrocarbonPoreGas': [160, 50],// teal
          'Bulk':             [230, 40],  // slate blue
          'Pore':             [270, 45],  // violet
        };
        const defaultHSL = [0, 0];       // grey

        // Stat → lightness level (dark = small L → light = large L)
        const statLevel = {
          'P10': 35, 'P50': 50, 'P90': 65,
          'ArithmeticMean': 42, 'Minimum': 72, 'Maximum': 78, 'StandardDeviation': 82
        };
        const defaultLevel = 55;

        function fluidColor(fluid, stat) {
          const [h, s] = fluidHSL[fluid] || defaultHSL;
          const l = statLevel[stat] || defaultLevel;
          return 'hsl(' + h + ',' + s + '%,' + l + '%)';
        }

        function buildChart(fluid){
          if (activeChart) activeChart.destroy();
          const cols = groups[fluid] || [];
          const datasets = cols.map(c => ({
            label: c.stat || c.col,
            data: colData[c.col],
            backgroundColor: fluidColor(fluid, c.stat),
            borderColor: fluidColor(fluid, 'P10'),
            borderWidth: 1,
            borderRadius: 3,
          }));
          const logScale = document.getElementById('volLogScale')?.checked;
          activeChart = new Chart(document.getElementById('volHistCanvas').getContext('2d'), {
            type: 'bar',
            data: { labels: segments, datasets },
            options: {
              responsive: true, maintainAspectRatio: false,
              interaction: { mode: 'index', intersect: false },
              plugins: {
                legend: { position: 'top', labels: { boxWidth: 14, font: { size: 11 } } },
                tooltip: { callbacks: { label: ctx => ctx.dataset.label + ': ' + (ctx.parsed.y != null ? ctx.parsed.y.toLocaleString(undefined, {maximumFractionDigits: 2}) : '-') } }
              },
              scales: {
                x: {
                  grid: { display: false },
                  ticks: { maxRotation: 45, minRotation: 0, font: { size: 10 },
                    callback: function(val) {
                      const lbl = this.getLabelForValue(val);
                      return lbl.length > 18 ? lbl.slice(0,16) + '…' : lbl;
                    }
                  }
                },
                y: {
                  type: logScale ? 'logarithmic' : 'linear',
                  beginAtZero: !logScale,
                  title: { display: true, text: fluid + ' volume' },
                  ticks: { callback: v => v >= 1e6 ? (v/1e6).toFixed(1) + 'M' : v >= 1e3 ? (v/1e3).toFixed(1) + 'k' : v }
                }
              }
            }
          });
        }

        buildChart(defaultFluid);

        document.getElementById('volFluidSel')?.addEventListener('change', e => buildChart(e.target.value));
        document.getElementById('volLogScale')?.addEventListener('change', () => {
          const sel = document.getElementById('volFluidSel');
          buildChart(sel ? sel.value : fluidNames[0]);
        });
      };

      window.closeVolModal = function(){
        if (activeChart) { activeChart.destroy(); activeChart = null; }
        if (activeModal) {
          if (activeModal._escHandler) document.removeEventListener('keydown', activeModal._escHandler);
          activeModal.remove();
          activeModal = null;
        }
      };

      /* ── Full volume table popup ── */
      window.openVolTable = function(btn) {
        const section = btn.closest('.section-card');
        if (!section) return;
        const tbl = section.querySelector('table.vol-data-table');
        if (!tbl) return;

        // Parse full table (including the ellipsis row we'll skip)
        const ths = Array.from(tbl.querySelectorAll('tr:first-child th'));
        const headers = ths.map(th => th.textContent.trim());
        if (!headers.length) return;

        // We need the full data - read from the Jinja-embedded data attributes
        // Actually, the preview table only has 3 rows. We'll rebuild from the hidden full data.
        // Strategy: find ALL vol-data-table rows (skip ellipsis), but full data is in the DOM
        //   We'll use a data attribute approach - embed full JSON in a hidden element.
        //   Simpler: the full data is available in the hidden sibling.
        // Best approach: clone the preview table and populate from data attributes.

        // Look for the full-data script tag next to the table
        const dataEl = section.querySelector('.vol-full-data');
        if (!dataEl) return;
        let fullData;
        try { fullData = JSON.parse(dataEl.textContent); } catch(e) { return; }

        if (activeModal) { activeModal.remove(); activeModal = null; }

        const overlay = document.createElement('div');
        overlay.className = 'vol-modal-overlay';
        overlay.addEventListener('click', e => { if (e.target === overlay) closeVolModal(); });

        const modal = document.createElement('div');
        modal.className = 'vol-modal';

        let h = '<button class="vol-modal-close" onclick="closeVolModal()" title="Close">&times;</button>';
        h += '<h4>Volume Table - ' + fullData.rows.length + ' rows</h4>';
        h += '<div style="margin-bottom:.5rem;display:flex;gap:.5rem;align-items:center;"><input type="text" id="volTblFilter" placeholder="Filter rows…" style="flex:1;max-width:20rem;font-size:.85rem;padding:.25rem .5rem;border:1px solid #cbd5e0;border-radius:4px;"><button type="button" class="btn-vol-expand" onclick="copyVolTableCSV()" title="Copy as CSV">📋 Copy CSV</button></div>';
        h += '<div class="table-scroll" style="max-height:60vh;overflow:auto;"><table class="vol-data-table" id="volFullTable">';
        h += '<tr>' + fullData.headers.map(hd => '<th>' + hd + '</th>').join('') + '</tr>';
        const keySet = new Set(fullData.keyNames || []);
        fullData.rows.forEach(row => {
          // Detect total rows: any key column has value 'TOTAL'
          let isTotal = false, isGrand = true;
          fullData.headers.forEach((hd, ci) => {
            if (keySet.has(hd) && String(row[ci]) === 'TOTAL') isTotal = true;
            if (keySet.has(hd) && String(row[ci]) !== 'TOTAL') isGrand = false;
          });
          const cls = (isTotal && isGrand) ? ' class="vol-grand-total"' : isTotal ? ' class="vol-total-row"' : '';
          h += '<tr' + cls + '>' + row.map(v => '<td>' + (v != null ? v : '-') + '</td>').join('') + '</tr>';
        });
        h += '</table></div>';

        modal.innerHTML = h;
        overlay.appendChild(modal);
        document.body.appendChild(overlay);
        activeModal = overlay;

        const escHandler = e => { if (e.key === 'Escape') closeVolModal(); };
        document.addEventListener('keydown', escHandler);
        overlay._escHandler = escHandler;

        // Filter
        document.getElementById('volTblFilter')?.addEventListener('input', function() {
          const q = this.value.toLowerCase();
          const rows = document.querySelectorAll('#volFullTable tr');
          rows.forEach((r, i) => {
            if (i === 0) return; // header
            r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none';
          });
        });
      };

      window.copyVolTableCSV = function() {
        const tbl = document.getElementById('volFullTable');
        if (!tbl) return;
        const rows = Array.from(tbl.querySelectorAll('tr'));
        const csv = rows.map(r => Array.from(r.querySelectorAll('th,td')).map(c => c.textContent.trim()).join('\t')).join('\n');
        navigator.clipboard.writeText(csv).then(() => {
          const btn = document.querySelector('.vol-modal .btn-vol-expand');
          if (btn) { const orig = btn.textContent; btn.textContent = 'Copied!'; setTimeout(() => btn.textContent = orig, 1500); }
        });
      };
    })();

/* ── Schema & Refdata detail viewer ── */
(function() {
  // ─── Schema detail on row click ───
  const schemaPanel = document.getElementById('schema-detail-panel');
  if (schemaPanel) {
    document.querySelectorAll('tr[data-schema-kind]').forEach(row => {
      row.addEventListener('click', function(e) {
        if (e.target.closest('a')) return;
        const kind = row.dataset.schemaKind;
        if (!kind) return;
        // Highlight active row
        row.closest('tbody').querySelectorAll('tr').forEach(r => r.classList.remove('active-row'));
        row.classList.add('active-row');
        // Show loading
        schemaPanel.style.display = '';
        schemaPanel.innerHTML = '<span class="loading">Loading schema definition for <strong>' + kind + '</strong>…</span>';
        schemaPanel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
        // Fetch
        fetch('/search/api/schema/' + encodeURIComponent(kind))
          .then(r => r.json())
          .then(data => {
            if (data.error) {
              schemaPanel.textContent = 'Error: ' + data.error;
              return;
            }
            renderSchemaDetail(kind, data, schemaPanel);
          })
          .catch(err => {
            schemaPanel.textContent = 'Fetch error: ' + err.message;
          });
      });
    });
  }

  function renderSchemaDetail(kind, schema, panel) {
    // Extract properties from the schema definition
    const props = schema.properties || {};
    const dataProps = (props.data && props.data.properties) ? props.data.properties : {};
    const required = (props.data && props.data.required) || [];

    let html = '<div class="tab-btns">';
    html += '<button class="active" data-tab="properties">Properties</button>';
    html += '<button data-tab="raw">Raw JSON</button>';
    html += '</div>';

    // Properties tab
    html += '<div class="tab-content" data-tab="properties">';
    html += '<h5>Schema: ' + escHtml(kind) + '</h5>';
    const propKeys = Object.keys(dataProps);
    if (propKeys.length > 0) {
      html += '<table class="schema-props-table"><thead><tr><th>Property</th><th>Type</th><th>Description</th><th>Req</th></tr></thead><tbody>';
      propKeys.sort().forEach(function(key) {
        const p = dataProps[key];
        let ptype = p.type || (p['$ref'] ? 'ref' : (p.items ? 'array' : ''));
        if (p.type === 'array' && p.items) {
          const itemType = p.items.type || p.items['$ref'] || 'object';
          ptype = 'array&lt;' + itemType.split('/').pop() + '&gt;';
        }
        if (p['$ref']) ptype = p['$ref'].split('/').pop();
        const desc = escHtml((p.description || p.title || '').substring(0, 120));
        const isReq = required.includes(key) ? '✓' : '';
        html += '<tr><td><strong>' + escHtml(key) + '</strong></td><td>' + escHtml(ptype) + '</td><td>' + desc + '</td><td>' + isReq + '</td></tr>';
      });
      html += '</tbody></table>';
    } else {
      html += '<p style="color:#605e5c;">No data properties found in this schema. See raw JSON for the full definition.</p>';
    }
    html += '</div>';

    // Raw JSON tab
    html += '<div class="tab-content" data-tab="raw" style="display:none;">';
    html += '<pre>' + JSON.stringify(schema, null, 2).replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</pre>';
    html += '</div>';

    panel.innerHTML = html;

    // Tab switching within detail panel
    panel.querySelectorAll('.tab-btns button').forEach(function(btn) {
      btn.addEventListener('click', function() {
        panel.querySelectorAll('.tab-btns button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        panel.querySelectorAll('.tab-content').forEach(c => {
          c.style.display = c.dataset.tab === btn.dataset.tab ? '' : 'none';
        });
      });
    });
  }

  // ─── Reference Data detail on row click ───
  const refdataPanel = document.getElementById('refdata-detail-panel');
  if (refdataPanel) {
    document.querySelectorAll('tr[data-record-id]').forEach(row => {
      row.addEventListener('click', function(e) {
        if (e.target.closest('a')) return;
        const recId = row.dataset.recordId;
        if (!recId) return;
        // Highlight active row
        row.closest('tbody').querySelectorAll('tr').forEach(r => r.classList.remove('active-row'));
        row.classList.add('active-row');
        // Show loading
        refdataPanel.style.display = '';
        refdataPanel.innerHTML = '<span class="loading">Loading record…</span>';
        refdataPanel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
        // Fetch
        fetch('/search/api/record/' + encodeURIComponent(recId))
          .then(r => r.json())
          .then(data => {
            if (data.error) {
              refdataPanel.textContent = 'Error: ' + data.error;
              return;
            }
            renderRecordDetail(data, refdataPanel);
          })
          .catch(err => {
            refdataPanel.textContent = 'Fetch error: ' + err.message;
          });
      });
    });
  }

  function renderRecordDetail(rec, panel) {
    const d = rec.data || {};
    const meta = rec.meta || (rec.acl ? {acl: rec.acl, legal: rec.legal} : {});

    let html = '<div class="tab-btns">';
    html += '<button class="active" data-tab="overview">Overview</button>';
    html += '<button data-tab="data">Data Fields</button>';
    html += '<button data-tab="raw">Raw JSON</button>';
    html += '</div>';

    // Overview tab
    html += '<div class="tab-content" data-tab="overview">';
    html += '<h5>' + escHtml(d.Name || rec.id || 'Record') + '</h5>';
    html += '<div class="detail-kv">';
    html += '<div class="k">ID</div><div class="v">' + escHtml(rec.id || '-') + '</div>';
    html += '<div class="k">Kind</div><div class="v">' + escHtml(rec.kind || '-') + '</div>';
    html += '<div class="k">Version</div><div class="v">' + escHtml(rec.version || '-') + '</div>';
    if (d.Name) html += '<div class="k">Name</div><div class="v">' + escHtml(d.Name) + '</div>';
    if (d.Code) html += '<div class="k">Code</div><div class="v">' + escHtml(d.Code) + '</div>';
    if (d.Description) html += '<div class="k">Description</div><div class="v">' + escHtml(d.Description) + '</div>';
    if (d.Source) html += '<div class="k">Source</div><div class="v">' + escHtml(d.Source) + '</div>';;
    html += '</div>';
    html += '<p style="margin-top:.5rem;"><a href="/search/view/' + encodeURIComponent(rec.id) + '">Open full page view →</a></p>';
    html += '</div>';

    // Data fields tab
    html += '<div class="tab-content" data-tab="data" style="display:none;">';
    html += '<table class="schema-props-table"><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>';
    Object.keys(d).sort().forEach(function(key) {
      let val = d[key];
      if (val === null || val === undefined) val = '-';
      else if (typeof val === 'object') val = '<code>' + JSON.stringify(val, null, 1).replace(/</g, '&lt;').substring(0, 300) + '</code>';
      else val = escHtml(val);
      html += '<tr><td><strong>' + escHtml(key) + '</strong></td><td>' + val + '</td></tr>';
    });
    html += '</tbody></table></div>';

    // Raw JSON tab
    html += '<div class="tab-content" data-tab="raw" style="display:none;">';
    html += '<pre>' + JSON.stringify(rec, null, 2).replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</pre>';
    html += '</div>';

    panel.innerHTML = html;

    // Tab switching
    panel.querySelectorAll('.tab-btns button').forEach(function(btn) {
      btn.addEventListener('click', function() {
        panel.querySelectorAll('.tab-btns button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        panel.querySelectorAll('.tab-content').forEach(c => {
          c.style.display = c.dataset.tab === btn.dataset.tab ? '' : 'none';
        });
      });
    });
  }
})();

/* ── Results table sorting ── */
<script>
/* ── Sortable table headers (all .results-table) ── */
(function() {
  function sortTable(th) {
    var table = th.closest('table');
    if (!table) return;
    var thead = table.querySelector('thead');
    var tbody = table.querySelector('tbody');
    if (!thead || !tbody) return;
    var ths = Array.from(thead.querySelectorAll('th'));
    var colIdx = ths.indexOf(th);
    if (colIdx < 0) return;

    // Determine direction
    var asc = !th.classList.contains('sort-asc');
    ths.forEach(function(h) { h.classList.remove('sort-asc', 'sort-desc'); });
    th.classList.add(asc ? 'sort-asc' : 'sort-desc');

    // Sort rows
    var rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort(function(a, b) {
      var cellA = a.children[colIdx];
      var cellB = b.children[colIdx];
      var tA = (cellA ? cellA.textContent : '').trim().toLowerCase();
      var tB = (cellB ? cellB.textContent : '').trim().toLowerCase();
      // Try numeric comparison first
      var nA = parseFloat(tA), nB = parseFloat(tB);
      if (!isNaN(nA) && !isNaN(nB)) {
        return asc ? nA - nB : nB - nA;
      }
      if (tA < tB) return asc ? -1 : 1;
      if (tA > tB) return asc ? 1 : -1;
      return 0;
    });
    rows.forEach(function(row) { tbody.appendChild(row); });
  }

  document.querySelectorAll('.results-table').forEach(function(table) {
    table.querySelectorAll('thead th').forEach(function(th) {
      th.addEventListener('click', function(e) {
        // Don't sort if clicking a link inside th
        if (e.target.tagName === 'A') return;
        sortTable(th);
      });
    });
  });
})();
