(function() {
  // ── Decision level toggle ──
  window.toggleCustomLevel = function() {
    var sel = document.getElementById('bd-level');
    var show = sel.value === '__custom__';
    document.getElementById('bd-level-custom').style.display = show ? '' : 'none';
    document.getElementById('bd-level-custom-label').style.display = show ? '' : 'none';
    if (show) document.getElementById('bd-level-custom').focus();
  };

  // ── Custom records management ──
  var customRecords = [];

  window.addCustomRecord = function() {
    var labelInp = document.getElementById('custom-rec-label');
    var idInp = document.getElementById('custom-rec-id');
    var lbl = labelInp.value.trim();
    var rid = idInp.value.trim();
    if (!lbl || !rid) { alert('Both a label and a record ID are required.'); return; }
    customRecords.push({label: lbl, id: rid});
    labelInp.value = ''; idInp.value = '';
    renderCustomRecords();
  };

  function removeCustomRecord(idx) {
    customRecords.splice(idx, 1);
    renderCustomRecords();
  }
  window.removeCustomRecord = removeCustomRecord;

  function renderCustomRecords() {
    var el = document.getElementById('custom-rec-list');
    if (!customRecords.length) { el.innerHTML = '<span class="muted" style="font-size:13px;">No custom records added yet.</span>'; return; }
    el.innerHTML = customRecords.map(function(rec, i) {
      return '<div class="risk-item"><strong style="min-width:120px;font-size:12px;color:var(--eq-charcoal);">' + escHtml(rec.label) + '</strong>' +
             '<span class="risk-id">' + escHtml(rec.id) + '</span>' +
             '<button class="remove-btn" onclick="removeCustomRecord(' + i + ')" title="Remove">&times;</button></div>';
    }).join('');
  }
  renderCustomRecords();

  // ── Risk management ──
  var riskIds = [];

  window.addRisk = function() {
    var inp = document.getElementById('risk-input');
    var val = inp.value.trim();
    if (!val) return;
    if (riskIds.indexOf(val) < 0) riskIds.push(val);
    inp.value = '';
    renderRisks();
  };

  function removeRisk(idx) {
    riskIds.splice(idx, 1);
    renderRisks();
  }
  window.removeRisk = removeRisk;

  function renderRisks() {
    var el = document.getElementById('risk-list');
    if (!riskIds.length) { el.innerHTML = '<span class="muted" style="font-size:13px;">No risks linked yet.</span>'; return; }
    el.innerHTML = riskIds.map(function(id, i) {
      return '<div class="risk-item"><span class="risk-id">' + escHtml(id) + '</span>' +
             '<button class="remove-btn" onclick="removeRisk(' + i + ')" title="Remove">&times;</button></div>';
    }).join('');
  }
  renderRisks();

  // ── Browse modal ──
  var browseTarget = null;
  var browseKind = '';

  window.openBrowse = function(targetId, kind) {
    browseTarget = targetId;
    browseKind = kind;
    document.getElementById('wpc-modal-title').textContent = 'Browse: ' + kind.split('--').pop().replace(':*','');
    document.getElementById('wpc-search-q').value = '*';
    document.getElementById('wpc-result-list').innerHTML = '';
    document.getElementById('wpc-modal-bg').classList.add('active');
    runBrowseSearch();
  };

  window.closeBrowse = function() {
    document.getElementById('wpc-modal-bg').classList.remove('active');
    browseTarget = null;
  };

  window.runBrowseSearch = function() {
    var q = document.getElementById('wpc-search-q').value || '*';
    var list = document.getElementById('wpc-result-list');
    list.innerHTML = '<span class="muted">Searching…</span>';
    fetch('/add-dg/wpc-search?kind=' + encodeURIComponent(browseKind) + '&q=' + encodeURIComponent(q) + '&limit=20')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (!data.length) { list.innerHTML = '<span class="muted">No results.</span>'; return; }
        list.innerHTML = data.map(function(rec) {
          return '<div class="wpc-result-item" onclick="selectBrowseResult(\'' + escAttr(rec.id) + '\')">' +
                 '<div class="wpc-name">' + escHtml(rec.name) + '</div>' +
                 '<div class="wpc-id">' + escHtml(rec.id) + '</div></div>';
        }).join('');
      })
      .catch(function(err) { list.innerHTML = '<span class="muted">Error: ' + escHtml(err.message) + '</span>'; });
  };

  window.selectBrowseResult = function(id) {
    if (browseTarget === 'risk-input') {
      document.getElementById('risk-input').value = id;
      addRisk();
    } else if (browseTarget === 'pc-ref-input') {
      document.getElementById('pc-ref-input').value = id;
      addPcRef();
    } else if (browseTarget) {
      document.getElementById(browseTarget).value = id;
    }
    closeBrowse();
  };

  // ── Build record payload ──
  function buildPayload() {
    var levelSel = document.getElementById('bd-level').value;
    var levelVal = levelSel === '__custom__' ? document.getElementById('bd-level-custom').value.trim() : levelSel;
    return {
      reservoir_id:          document.getElementById('reservoir-select').value,
      name:                  document.getElementById('bd-name').value,
      project_name:          document.getElementById('bd-project').value,
      description:           document.getElementById('bd-description').value,
      decision_level:        levelVal,
      approval_status:       document.getElementById('bd-status').value,
      decision_date:         document.getElementById('bd-date').value,
      decision_due_date:     document.getElementById('bd-due-date').value,
      decision_summary:      document.getElementById('bd-summary').value,
      rev_stats_id:          document.getElementById('link-rev-stats').value,
      rev_raw_id:            document.getElementById('link-rev-raw').value,
      production_profile_id: document.getElementById('link-production-profile').value,
      geolabelset_id:        document.getElementById('link-geolabelset').value,
      params_id:             document.getElementById('link-params').value,
      activity_id:           document.getElementById('link-activity').value,
      dataspace_id:          document.getElementById('link-dataspace').value,
      collection_id:         document.getElementById('link-collection').value,
      risk_ids:              riskIds.slice(),
      custom_records:        customRecords.slice(),
    };
  }

  // ── Preview ──
  window.previewRecord = function() {
    var payload = buildPayload();
    var wrap = document.getElementById('preview-wrap');
    var pre = document.getElementById('preview-json');
    pre.textContent = JSON.stringify(payload, null, 2);
    wrap.style.display = 'block';
  };

  // ── Submit ──
  window.submitRecord = function() {
    var payload = buildPayload();
    if (!payload.reservoir_id) { alert('Please select a Reservoir.'); return; }
    if (!payload.name) { alert('Please enter a BD name.'); return; }

    document.getElementById('submit-overlay').classList.add('active');
    document.getElementById('result-area').innerHTML = '';

    fetch('/add-dg/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    })
    .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
    .then(function(res) {
      document.getElementById('submit-overlay').classList.remove('active');
      var area = document.getElementById('result-area');
      if (res.data.ok) {
        area.innerHTML = '<div class="result-ok">' +
          '<strong>&#10003; BusinessDecision created successfully</strong><br>' +
          '<span class="bd-id">' + escHtml(res.data.bd_id) + '</span><br>' +
          '<span class="muted">Status: ' + res.status + ' &middot; ' +
          res.data.parameters_count + ' parameters &middot; ' +
          res.data.risk_count + ' risks</span></div>';
      } else {
        area.innerHTML = '<div class="result-err">' +
          '<strong>Ingest failed (HTTP ' + res.status + ')</strong><br>' +
          '<pre style="margin:.4rem 0 0;font-size:12px;white-space:pre-wrap;">' +
          escHtml(res.data.response || res.data.error || JSON.stringify(res.data)) + '</pre></div>';
      }
    })
    .catch(function(err) {
      document.getElementById('submit-overlay').classList.remove('active');
      document.getElementById('result-area').innerHTML =
        '<div class="result-err"><strong>Network error:</strong> ' + escHtml(err.message) + '</div>';
    });
  };

  // ── Helpers ──
  function escHtml(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
  function escAttr(s) { return (s || '').replace(/'/g, "\\'").replace(/"/g, '&quot;'); }

  // Click outside modal closes it
  document.getElementById('wpc-modal-bg').addEventListener('click', function(e) {
    if (e.target === this) closeBrowse();
  });

  // ══════════════════════════════════════════════════════════════════════
  // Mode tab switching
  // ══════════════════════════════════════════════════════════════════════
  window.switchMode = function(mode) {
    document.querySelectorAll('.mode-tab').forEach(function(t) {
      t.classList.toggle('active', t.getAttribute('data-mode') === mode);
    });
    document.querySelectorAll('.mode-panel').forEach(function(p) {
      p.style.display = p.id === 'mode-' + mode ? '' : 'none';
    });
  };

  // ══════════════════════════════════════════════════════════════════════
  // Collaboration Project form logic
  // ══════════════════════════════════════════════════════════════════════
  var cpCustomRecords = [];

  window.addCpCustomRecord = function() {
    var labelInp = document.getElementById('cp-custom-rec-label');
    var idInp = document.getElementById('cp-custom-rec-id');
    var lbl = labelInp.value.trim();
    var rid = idInp.value.trim();
    if (!lbl || !rid) { alert('Both a label and a record ID are required.'); return; }
    cpCustomRecords.push({label: lbl, id: rid});
    labelInp.value = ''; idInp.value = '';
    renderCpCustomRecords();
  };

  window.removeCpCustomRecord = function(idx) {
    cpCustomRecords.splice(idx, 1);
    renderCpCustomRecords();
  };

  function renderCpCustomRecords() {
    var el = document.getElementById('cp-custom-rec-list');
    if (!cpCustomRecords.length) { el.innerHTML = '<span class="muted" style="font-size:13px;">No custom records added yet.</span>'; return; }
    el.innerHTML = cpCustomRecords.map(function(rec, i) {
      return '<div class="risk-item"><strong style="min-width:120px;font-size:12px;color:var(--eq-charcoal);">' + escHtml(rec.label) + '</strong>' +
             '<span class="risk-id">' + escHtml(rec.id) + '</span>' +
             '<button class="remove-btn" onclick="removeCpCustomRecord(' + i + ')" title="Remove">&times;</button></div>';
    }).join('');
  }
  renderCpCustomRecords();

  function buildCpPayload() {
    return {
      name:                 document.getElementById('cp-name').value.trim(),
      description:          document.getElementById('cp-description').value.trim(),
      purpose:              document.getElementById('cp-purpose').value.trim(),
      lifecycle_status:     document.getElementById('cp-lifecycle').value,
      begin_date:           document.getElementById('cp-begin-date').value,
      end_date:             document.getElementById('cp-end-date').value,
      namespace:            document.getElementById('cp-namespace').value.trim(),
      parent_bd_id:         document.getElementById('cp-link-bd').value.trim(),
      dataspace_id:         document.getElementById('cp-link-dataspace').value.trim(),
      reservoir_id:         document.getElementById('cp-link-reservoir').value.trim(),
      collection_id:        document.getElementById('cp-link-collection').value.trim(),
      activity_id:          document.getElementById('cp-link-activity').value.trim(),
      contributor_owners:   document.getElementById('cp-contributor-owners').value.trim(),
      contributor_viewers:  document.getElementById('cp-contributor-viewers').value.trim(),
      custom_records:       cpCustomRecords.slice(),
    };
  }

  window.previewCpRecord = function() {
    var payload = buildCpPayload();
    var wrap = document.getElementById('cp-preview-wrap');
    var pre = document.getElementById('cp-preview-json');
    pre.textContent = JSON.stringify(payload, null, 2);
    wrap.style.display = 'block';
  };

  window.submitCpRecord = function() {
    var payload = buildCpPayload();
    if (!payload.name) { alert('Please enter a project name.'); return; }

    document.getElementById('submit-overlay').classList.add('active');
    document.getElementById('cp-result-area').innerHTML = '';

    fetch('/add-dg/create-cp', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    })
    .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
    .then(function(res) {
      document.getElementById('submit-overlay').classList.remove('active');
      var area = document.getElementById('cp-result-area');
      if (res.data.ok) {
        area.innerHTML = '<div class="result-ok">' +
          '<strong>&#10003; CollaborationProject created successfully</strong><br>' +
          '<span class="bd-id">' + escHtml(res.data.cp_id) + '</span><br>' +
          '<span class="muted">Status: ' + res.status + ' &middot; ' +
          res.data.parameters_count + ' parameters</span></div>';
      } else {
        area.innerHTML = '<div class="result-err">' +
          '<strong>Ingest failed (HTTP ' + res.status + ')</strong><br>' +
          '<pre style="margin:.4rem 0 0;font-size:12px;white-space:pre-wrap;">' +
          escHtml(res.data.response || res.data.error || JSON.stringify(res.data)) + '</pre></div>';
      }
    })
    .catch(function(err) {
      document.getElementById('submit-overlay').classList.remove('active');
      document.getElementById('cp-result-area').innerHTML =
        '<div class="result-err"><strong>Network error:</strong> ' + escHtml(err.message) + '</div>';
    });
  };
  // ══════════════════════════════════════════════════════════════════════
  // Persisted Collection form logic
  // ══════════════════════════════════════════════════════════════════════
  var pcRefs = [];

  window.addPcRef = function() {
    var inp = document.getElementById('pc-ref-input');
    var val = inp.value.trim();
    if (!val) return;
    if (pcRefs.indexOf(val) < 0) pcRefs.push(val);
    inp.value = '';
    renderPcRefs();
  };

  window.removePcRef = function(idx) {
    pcRefs.splice(idx, 1);
    renderPcRefs();
  };

  function renderPcRefs() {
    var el = document.getElementById('pc-ref-list');
    document.getElementById('pc-ref-count').textContent = pcRefs.length;
    if (!pcRefs.length) { el.innerHTML = '<span class="muted" style="font-size:13px;">No references added yet.</span>'; return; }
    el.innerHTML = pcRefs.map(function(ref, i) {
      return '<div class="risk-item"><span style="min-width:28px;font-size:11px;color:var(--eq-grey);">' + (i+1) + '.</span>' +
             '<span class="risk-id">' + escHtml(ref) + '</span>' +
             '<button class="remove-btn" onclick="removePcRef(' + i + ')" title="Remove">&times;</button></div>';
    }).join('');
  }
  renderPcRefs();

  function buildPcPayload() {
    return {
      name:            document.getElementById('pc-name').value.trim(),
      description:     document.getElementById('pc-description').value.trim(),
      tags:            document.getElementById('pc-tags').value.trim(),
      custom_id:       document.getElementById('pc-custom-id').value.trim(),
      data_references: pcRefs.slice(),
    };
  }

  window.previewPcRecord = function() {
    var payload = buildPcPayload();
    var wrap = document.getElementById('pc-preview-wrap');
    var pre = document.getElementById('pc-preview-json');
    pre.textContent = JSON.stringify(payload, null, 2);
    wrap.style.display = 'block';
  };

  window.submitPcRecord = function() {
    var payload = buildPcPayload();
    if (!payload.name) { alert('Please enter a collection name.'); return; }
    if (!payload.data_references.length) { alert('Please add at least one data reference.'); return; }

    document.getElementById('submit-overlay').classList.add('active');
    document.getElementById('pc-result-area').innerHTML = '';

    fetch('/add-dg/create-pc', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    })
    .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
    .then(function(res) {
      document.getElementById('submit-overlay').classList.remove('active');
      var area = document.getElementById('pc-result-area');
      if (res.data.ok) {
        area.innerHTML = '<div class="result-ok">' +
          '<strong>&#10003; PersistedCollection created successfully</strong><br>' +
          '<span class="bd-id">' + escHtml(res.data.pc_id) + '</span><br>' +
          '<span class="muted">Status: ' + res.status + ' &middot; ' +
          res.data.data_references_count + ' data references</span></div>';
      } else {
        area.innerHTML = '<div class="result-err">' +
          '<strong>Ingest failed (HTTP ' + res.status + ')</strong><br>' +
          '<pre style="margin:.4rem 0 0;font-size:12px;white-space:pre-wrap;">' +
          escHtml(res.data.response || res.data.error || JSON.stringify(res.data)) + '</pre></div>';
      }
    })
    .catch(function(err) {
      document.getElementById('submit-overlay').classList.remove('active');
      document.getElementById('pc-result-area').innerHTML =
        '<div class="result-err"><strong>Network error:</strong> ' + escHtml(err.message) + '</div>';
    });
  };

  // ══════════════════════════════════════════════════════════════════════
  // Activity & Template form logic
  // ══════════════════════════════════════════════════════════════════════

  // ── Sub-tab toggle ──
  window.switchActSub = function(sub) {
    document.querySelectorAll('.act-subtab').forEach(function(t) {
      t.classList.toggle('active', t.getAttribute('data-act') === sub);
    });
    document.querySelectorAll('.act-subpanel').forEach(function(p) {
      p.classList.toggle('active', p.id === 'act-sub-' + sub);
    });
  };

  // ── Help popup ──
  window.showActHelp = function() { document.getElementById('act-help-bg').classList.add('active'); };
  window.hideActHelp = function() { document.getElementById('act-help-bg').classList.remove('active'); };

  // ────────────────────────────────────────────────────────────────────
  // TEMPLATE sub-tab
  // ────────────────────────────────────────────────────────────────────

  var TPL_PRESETS = {
    reservoir_sim: {
      name: 'Reservoir Simulation',
      desc: 'Multi-realisation reservoir modelling with ERT/RMS',
      params: [
        {title:'InputParameters', desc:'Per-realisation input table',  isInput:true,  isOutput:false, kind:'DataObject', min:0, max:1},
        {title:'Process',         desc:'RMS workflow name',            isInput:true,  isOutput:false, kind:'string',     min:1, max:1},
        {title:'NumberOfRealizations', desc:'Realisations executed',   isInput:true,  isOutput:false, kind:'integer',    min:1, max:1},
        {title:'Workflow',        desc:'ERT workflow identifier',      isInput:true,  isOutput:false, kind:'string',     min:0, max:1},
        {title:'Method',          desc:'Simulation method',            isInput:true,  isOutput:false, kind:'string',     min:0, max:1},
        {title:'Variables',       desc:'Serialised variable set (JSON)', isInput:true, isOutput:false, kind:'string',   min:0, max:1},
        {title:'DesignMatrix',    desc:'Serialised design matrix (JSON)',isInput:true, isOutput:false, kind:'string',   min:0, max:1},
        {title:'OutputParameters',desc:'Per-realisation output table', isInput:false, isOutput:true,  kind:'DataObject', min:0, max:1},
        {title:'OutputVolumes',   desc:'Aggregated volume results',    isInput:false, isOutput:true,  kind:'DataObject', min:1, max:1},
        {title:'ReportTable',     desc:'Summary report table',         isInput:false, isOutput:true,  kind:'DataObject', min:1, max:1},
      ]
    },
    interpretation: {
      name: 'Interpretation Session',
      desc: 'Seismic or geological interpretation',
      params: [
        {title:'InputSurvey',     desc:'Seismic survey input',         isInput:true,  isOutput:false, kind:'DataObject', min:1, max:1},
        {title:'Interpreter',     desc:'Person who interpreted',       isInput:true,  isOutput:false, kind:'string',     min:1, max:1},
        {title:'Method',          desc:'Interpretation method/software', isInput:true, isOutput:false, kind:'string',    min:0, max:1},
        {title:'OutputHorizons',  desc:'Interpreted horizon surfaces',  isInput:false, isOutput:true, kind:'DataObject', min:0, max:1},
        {title:'OutputFaults',    desc:'Interpreted fault surfaces',    isInput:false, isOutput:true, kind:'DataObject', min:0, max:1},
      ]
    },
    qc: {
      name: 'QC / Validation',
      desc: 'Quality control check workflow',
      params: [
        {title:'InputData',       desc:'Data under QC',                isInput:true,  isOutput:false, kind:'DataObject', min:1, max:1},
        {title:'QCMethod',        desc:'Validation method used',       isInput:true,  isOutput:false, kind:'string',     min:1, max:1},
        {title:'Threshold',       desc:'Pass/fail threshold',          isInput:true,  isOutput:false, kind:'string',     min:0, max:1},
        {title:'QCResult',        desc:'Pass/Fail/Warning',            isInput:false, isOutput:true,  kind:'string',     min:1, max:1},
        {title:'Report',          desc:'QC report DataObject',         isInput:false, isOutput:true,  kind:'DataObject', min:0, max:1},
      ]
    },
    custom: {
      name: '', desc: 'Build parameter slots from scratch',
      params: []
    },
  };

  var tplParams = [];

  window.selectTplPreset = function(presetName) {
    var preset = TPL_PRESETS[presetName];
    if (!preset) return;
    // Highlight card
    document.querySelectorAll('.act-preset-card').forEach(function(c) {
      c.classList.toggle('selected', c.id === 'apc-' + presetName);
    });
    // Fill name/desc
    if (preset.name) document.getElementById('tpl-name').value = preset.name;
    if (preset.desc && presetName !== 'custom')
      document.getElementById('tpl-desc').value = preset.desc;
    // Copy preset params
    tplParams = preset.params.map(function(p) {
      return {title:p.title, desc:p.desc, isInput:p.isInput, isOutput:p.isOutput, kind:p.kind, min:p.min, max:p.max};
    });
    renderTplParams();
  };

  window.addTplParam = function(role) {
    tplParams.push({
      title: '', desc: '',
      isInput: role === 'input', isOutput: role === 'output',
      kind: 'string', min: 0, max: 1,
    });
    renderTplParams();
  };

  window.removeTplParam = function(i) { tplParams.splice(i, 1); renderTplParams(); };

  function renderTplParams() {
    var el = document.getElementById('tpl-param-list');
    if (!tplParams.length) {
      el.innerHTML = '<span class="muted" style="font-size:13px;">No parameter slots yet. Choose a preset above or add slots manually.</span>';
      return;
    }
    el.innerHTML = tplParams.map(function(p, i) {
      var roleTag = p.isInput ? '<span style="color:var(--eq-red);font-weight:700;min-width:28px;font-size:11px;">IN</span>' :
                                '<span style="color:var(--eq-slate);font-weight:700;min-width:28px;font-size:11px;">OUT</span>';
      return '<div class="param-row">' +
        roleTag +
        '<input class="pk" placeholder="Title" value="' + escAttr(p.title) + '" oninput="tplParams['+i+'].title=this.value" />' +
        '<input class="pv" placeholder="Description" value="' + escAttr(p.desc) + '" oninput="tplParams['+i+'].desc=this.value" />' +
        '<select style="width:100px" onchange="tplParams['+i+'].kind=this.value">' +
          '<option value="string"' + (p.kind==='string'?' selected':'') + '>string</option>' +
          '<option value="integer"' + (p.kind==='integer'?' selected':'') + '>integer</option>' +
          '<option value="DataObject"' + (p.kind==='DataObject'?' selected':'') + '>DataObject</option>' +
        '</select>' +
        '<select style="width:65px;font-size:11px;" onchange="tplParams['+i+'].min=parseInt(this.value)" title="MinOccurs">' +
          '<option value="0"' + (p.min===0?' selected':'') + '>opt</option>' +
          '<option value="1"' + (p.min===1?' selected':'') + '>req</option>' +
        '</select>' +
        '<button class="remove-btn" onclick="removeTplParam('+i+')" title="Remove">&times;</button>' +
        '</div>';
    }).join('');
  }
  renderTplParams();

  function buildTplPayload() {
    return {
      name:        document.getElementById('tpl-name').value.trim(),
      description: document.getElementById('tpl-desc').value.trim(),
      originator:  document.getElementById('tpl-originator').value.trim(),
      parameter_templates: tplParams.map(function(p) {
        return {
          Title:                p.title,
          Description:          p.desc,
          IsInput:              p.isInput,
          IsOutput:             p.isOutput,
          MinOccurs:            p.min,
          MaxOccurs:            p.max,
          DefaultParameterKind: p.kind,
        };
      }),
    };
  }

  window.previewTplRecord = function() {
    var payload = buildTplPayload();
    var pre = document.getElementById('tpl-preview-json');
    pre.textContent = JSON.stringify(payload, null, 2);
    document.getElementById('tpl-preview-wrap').style.display = 'block';
  };

  window.submitTplRecord = function() {
    var payload = buildTplPayload();
    if (!payload.name) { alert('Template name is required.'); return; }

    document.getElementById('submit-overlay').classList.add('active');
    document.getElementById('tpl-result-area').innerHTML = '';

    fetch('/add-dg/create-activity-template', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    })
    .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
    .then(function(res) {
      document.getElementById('submit-overlay').classList.remove('active');
      var area = document.getElementById('tpl-result-area');
      if (res.data.ok) {
        area.innerHTML = '<div class="result-ok">' +
          '<strong>&#10003; ActivityTemplate created</strong><br>' +
          '<span class="bd-id">' + escHtml(res.data.record_id) + '</span><br>' +
          '<span class="muted">' + res.data.param_count + ' parameter slots &middot; Status: ' + res.status + '</span><br>' +
          '<button class="btn" style="margin-top:6px;font-size:12px;" onclick="copyTplId(\'' + escAttr(res.data.record_id) + '\')">Copy ID &amp; switch to Activity tab</button></div>';
      } else {
        area.innerHTML = '<div class="result-err"><strong>Ingest failed (HTTP ' + res.status + ')</strong><br>' +
          '<pre style="margin:.4rem 0 0;font-size:12px;white-space:pre-wrap;">' +
          escHtml(res.data.response || res.data.error || JSON.stringify(res.data)) + '</pre></div>';
      }
    })
    .catch(function(err) {
      document.getElementById('submit-overlay').classList.remove('active');
      document.getElementById('tpl-result-area').innerHTML =
        '<div class="result-err"><strong>Network error:</strong> ' + escHtml(err.message) + '</div>';
    });
  };

  window.copyTplId = function(id) {
    document.getElementById('act-template-id').value = id;
    // Pre-populate template validation slots from the just-created template
    loadedTemplateSlots = tplParams.map(function(p) {
      return {
        title: p.title,
        isInput: p.isInput,
        isOutput: p.isOutput,
        kind: p.kind,
        minOccurs: p.min,
      };
    });
    // Pre-populate activity params from template slots
    actParams = tplParams.map(function(p) {
      var role = p.isInput ? 'input' : 'output';
      var kind = p.kind.toLowerCase() === 'dataobject' ? 'DataObject' : p.kind;
      return {title: p.title, desc: p.desc, role: role, kind: kind, value: '', required: (p.min || 0) >= 1};
    });
    renderActParams();
    switchActSub('run');
  };

  // ────────────────────────────────────────────────────────────────────
  // ACTIVITY sub-tab
  // ────────────────────────────────────────────────────────────────────

  var actParams = [];
  var loadedTemplateSlots = null;  // template slots for validation

  window.loadTemplateSlots = function() {
    var tplId = document.getElementById('act-template-id').value.trim();
    if (!tplId) { alert('Enter an ActivityTemplate ID first.'); return; }

    // Fetch the template record via Storage API
    fetch('/add-dg/fetch-record?id=' + encodeURIComponent(tplId))
    .then(function(r) { return r.json(); })
    .then(function(res) {
      if (!res.ok) { alert('Could not fetch template: ' + (res.error || 'unknown error')); return; }
      var data = res.data || {};
      var slots = data.ParameterTemplates || data.parameterTemplates || [];
      if (!slots.length) { alert('Template has no parameter slots.'); return; }
      // Store template slots for validation
      loadedTemplateSlots = slots.map(function(s) {
        return {
          title: s.Title || '',
          isInput: !!s.IsInput,
          isOutput: !!s.IsOutput,
          kind: (s.DefaultParameterKind || 'string'),
          minOccurs: s.MinOccurs || 0,
        };
      });
      actParams = slots.map(function(s) {
        var role = s.IsInput ? 'input' : 'output';
        var kind = (s.DefaultParameterKind || 'string').toLowerCase();
        if (kind === 'dataobject') kind = 'DataObject';
        return {title: s.Title||'', desc: s.Description||'', role: role, kind: kind, value: '', required: (s.MinOccurs||0) >= 1};
      });
      renderActParams();
    })
    .catch(function(err) { alert('Error fetching template: ' + err.message); });
  };

  window.addActParam = function(role, kind) {
    actParams.push({title:'', desc:'', role:role, kind:kind||'string', value:''});
    renderActParams();
  };

  window.removeActParam = function(i) { actParams.splice(i, 1); renderActParams(); };

  function renderActParams() {
    var el = document.getElementById('act-param-list');
    if (!actParams.length) {
      el.innerHTML = '<span class="muted" style="font-size:13px;">No parameters yet. Load from a template or add manually.</span>';
      return;
    }
    el.innerHTML = actParams.map(function(p, i) {
      var roleTag = p.role === 'input'
        ? '<span style="color:var(--eq-red);font-weight:700;min-width:28px;font-size:11px;">IN</span>'
        : '<span style="color:var(--eq-slate);font-weight:700;min-width:28px;font-size:11px;">OUT</span>';
      var kindBadge = '<span style="font-size:10px;color:var(--eq-grey);min-width:60px;">['+p.kind+']</span>';
      var reqBadge = p.required ? '<span style="font-size:9px;color:var(--eq-red);font-weight:700;">REQ</span>' : '';
      var placeholder = p.kind === 'DataObject' ? 'OSDU record ID' :
                        p.kind === 'integer' ? 'Integer value' : 'String value';
      var borderStyle = (p.required && !p.value) ? 'border-color:var(--eq-red);' : '';
      return '<div class="param-row">' +
        roleTag + kindBadge + reqBadge +
        '<input class="pk" placeholder="Title" value="' + escAttr(p.title) + '" oninput="actParams['+i+'].title=this.value" />' +
        '<input class="pv" placeholder="' + placeholder + '" value="' + escAttr(p.value) + '" oninput="actParams['+i+'].value=this.value" style="' + borderStyle + '" />' +
        '<button class="remove-btn" onclick="removeActParam('+i+')" title="Remove">&times;</button>' +
        '</div>';
    }).join('');
  }
  renderActParams();

  // Set default datetime to now
  (function() {
    var dt = document.getElementById('act-datetime');
    if (dt) { var now = new Date(); dt.value = now.toISOString().slice(0,16); }
  })();

  function buildActPayload() {
    var idPrefix = '';  // auto
    return {
      name:            document.getElementById('act-name').value.trim(),
      description:     document.getElementById('act-desc').value.trim(),
      originator:      document.getElementById('act-originator').value.trim(),
      template_id:     document.getElementById('act-template-id').value.trim(),
      workflow_status: document.getElementById('act-status').value,
      creation_datetime: document.getElementById('act-datetime').value,
      parent_object_id: document.getElementById('act-parent').value.trim(),
      parameters: actParams.map(function(p) {
        return {title: p.title, role: p.role, kind: p.kind, value: p.value, desc: p.desc};
      }),
    };
  }

  window.previewActRecord = function() {
    var payload = buildActPayload();
    var pre = document.getElementById('act-preview-json');
    pre.textContent = JSON.stringify(payload, null, 2);
    document.getElementById('act-preview-wrap').style.display = 'block';
  };

  // Validate activity params against loaded template
  function validateActAgainstTemplate() {
    if (!loadedTemplateSlots) return null; // no template loaded, skip validation
    var issues = [];
    // Check required template slots have matching params with values
    loadedTemplateSlots.forEach(function(slot) {
      if (slot.minOccurs >= 1) {
        var match = actParams.filter(function(p) { return p.title === slot.title; });
        if (!match.length) {
          issues.push('Missing required slot: "' + slot.title + '"');
        } else if (!match[0].value && match[0].value !== 0) {
          issues.push('Required slot "' + slot.title + '" has no value');
        }
      }
    });
    // Check all params with titles have matching template slots (warn on extras)
    var slotTitles = loadedTemplateSlots.map(function(s) { return s.title; });
    actParams.forEach(function(p) {
      if (p.title && slotTitles.indexOf(p.title) < 0) {
        issues.push('Parameter "' + p.title + '" not in template (will be added as extra)');
      }
    });
    // Check kind matches
    loadedTemplateSlots.forEach(function(slot) {
      var match = actParams.filter(function(p) { return p.title === slot.title; });
      if (match.length) {
        var expected = slot.kind.toLowerCase() === 'dataobject' ? 'DataObject' : slot.kind.toLowerCase();
        if (match[0].kind !== expected) {
          issues.push('"' + slot.title + '" kind mismatch: template expects ' + expected + ', got ' + match[0].kind);
        }
      }
    });
    return issues.length ? issues : null;
  }

  window.submitActRecord = function() {
    var payload = buildActPayload();
    if (!payload.name) { alert('Activity name is required.'); return; }

    // Validate against template if one was loaded
    var issues = validateActAgainstTemplate();
    if (issues) {
      var msg = 'Template validation:\n\n' + issues.join('\n');
      var hasErrors = issues.some(function(i) { return i.indexOf('Missing required') === 0 || i.indexOf('Required slot') === 0; });
      if (hasErrors) {
        alert(msg + '\n\nPlease fix required fields before submitting.');
        return;
      }
      // Warnings only (extras, kind mismatches) - let user decide
      if (!confirm(msg + '\n\nProceed anyway?')) return;
    }

    document.getElementById('submit-overlay').classList.add('active');
    document.getElementById('act-result-area').innerHTML = '';

    fetch('/add-dg/create-activity', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    })
    .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
    .then(function(res) {
      document.getElementById('submit-overlay').classList.remove('active');
      var area = document.getElementById('act-result-area');
      if (res.data.ok) {
        area.innerHTML = '<div class="result-ok">' +
          '<strong>&#10003; Activity created</strong><br>' +
          '<span class="bd-id">' + escHtml(res.data.record_id) + '</span><br>' +
          '<span class="muted">' + res.data.param_count + ' parameters &middot; Status: ' + res.status + '</span></div>';
      } else {
        area.innerHTML = '<div class="result-err"><strong>Ingest failed (HTTP ' + res.status + ')</strong><br>' +
          '<pre style="margin:.4rem 0 0;font-size:12px;white-space:pre-wrap;">' +
          escHtml(res.data.response || res.data.error || JSON.stringify(res.data)) + '</pre></div>';
      }
    })
    .catch(function(err) {
      document.getElementById('submit-overlay').classList.remove('active');
      document.getElementById('act-result-area').innerHTML =
        '<div class="result-err"><strong>Network error:</strong> ' + escHtml(err.message) + '</div>';
    });
  };

  // ══════════════════════════════════════════════════════════════════════
  // Generic Record form logic
  // ══════════════════════════════════════════════════════════════════════

  // ── Type presets: kind + scaffold fields for each SME type ──
  var GEN_PRESETS = {
    risk: {
      kind: 'osdu:wks:master-data--Risk:1.2.0',
      desc: '<b>Risk</b> &mdash; subsurface or project risk with probability, severity, and mitigation strategy. Linked to BusinessDecisions via <code>RiskIDs[]</code>.',
      fields: [
        {key: 'Name',             value: '', type: 'string'},
        {key: 'Description',      value: '', type: 'string'},
        {key: 'RiskCategoryID',   value: '', type: 'string'},
        {key: 'RiskDisciplineID', value: '', type: 'string'},
        {key: 'InherentRiskProbabilityID', value: '', type: 'string'},
        {key: 'InherentRiskSeverityID',    value: '', type: 'string'},
        {key: 'ResidualRiskProbabilityID', value: '', type: 'string'},
        {key: 'ResidualRiskSeverityID',    value: '', type: 'string'},
        {key: 'MitigationPlan',   value: '', type: 'string'},
        {key: 'RiskOwner',        value: '', type: 'string'},
      ]
    },
    document: {
      kind: 'osdu:wks:work-product-component--Document:1.2.0',
      desc: '<b>Document</b> &mdash; metadata for a governance document (SRA, CRA, PDO, PTR, technical report). The document itself is stored externally; this record is the OSDU catalog entry.',
      fields: [
        {key: 'Name',            value: '', type: 'string'},
        {key: 'Description',     value: '', type: 'string'},
        {key: 'DocumentTypeID',  value: '', type: 'string'},
        {key: 'DocumentDate',    value: '', type: 'string'},
        {key: 'Authors',         value: '', type: 'array'},
        {key: 'Tags',            value: '', type: 'array'},
      ]
    },
    field: {
      kind: 'osdu:wks:master-data--Field:1.1.0',
      desc: '<b>Field</b> &mdash; an oil/gas field entity. Contains geographic and geological context. Parent for reservoirs and wells.',
      fields: [
        {key: 'FieldName',       value: '', type: 'string'},
        {key: 'Description',     value: '', type: 'string'},
        {key: 'OperatingEnvironmentID', value: '', type: 'string'},
        {key: 'DiscoveryDate',   value: '', type: 'string'},
        {key: 'CurrentFieldDevelopmentPhaseTypeID', value: '', type: 'string'},
      ]
    },
    organisation: {
      kind: 'osdu:wks:master-data--Organisation:1.1.0',
      desc: '<b>Organisation</b> &mdash; a company, team, or organizational unit. Referenced by other records for operator, partner, and contributor roles.',
      fields: [
        {key: 'OrganisationName',    value: '', type: 'string'},
        {key: 'Description',         value: '', type: 'string'},
        {key: 'OrganisationTypeID',  value: '', type: 'string'},
      ]
    },
    reservoir: {
      kind: 'osdu:wks:master-data--Reservoir:2.0.0',
      desc: '<b>Reservoir</b> &mdash; a reservoir entity containing geological context. Parent for ReservoirSegments and linked to volumes, risks, and decisions.',
      fields: [
        {key: 'Name',            value: '', type: 'string'},
        {key: 'Description',     value: '', type: 'string'},
        {key: 'FieldID',         value: '', type: 'string'},
        {key: 'FluidTypeID',     value: '', type: 'string'},
      ]
    },
    reservoirsegment: {
      kind: 'osdu:wks:master-data--ReservoirSegment:2.0.0',
      desc: '<b>Reservoir Segment</b> &mdash; a fault-bounded compartment within a reservoir. Carries segment-level properties and volume allocations.',
      fields: [
        {key: 'Name',            value: '', type: 'string'},
        {key: 'Description',     value: '', type: 'string'},
        {key: 'ReservoirID',     value: '', type: 'string'},
        {key: 'SegmentIndex',    value: '', type: 'number'},
      ]
    },
    well: {
      kind: 'osdu:wks:master-data--Well:1.1.0',
      desc: '<b>Well</b> &mdash; a well header record. Parent for wellbores. Contains surface location, operator, spud date, and regulatory status.',
      fields: [
        {key: 'FacilityName',    value: '', type: 'string'},
        {key: 'Description',     value: '', type: 'string'},
        {key: 'FacilityOperator',value: '', type: 'string'},
        {key: 'FieldID',         value: '', type: 'string'},
        {key: 'SpudDate',        value: '', type: 'string'},
        {key: 'WellTypeID',      value: '', type: 'string'},
        {key: 'CurrentStatusID', value: '', type: 'string'},
      ]
    },
    wellbore: {
      kind: 'osdu:wks:master-data--Wellbore:1.2.0',
      desc: '<b>Wellbore</b> &mdash; a wellbore within a well. Carries trajectory reference, target depth, and drilling status.',
      fields: [
        {key: 'FacilityName',    value: '', type: 'string'},
        {key: 'Description',     value: '', type: 'string'},
        {key: 'WellID',          value: '', type: 'string'},
        {key: 'TargetFormation', value: '', type: 'string'},
        {key: 'TotalMeasuredDepth', value: '', type: 'number'},
        {key: 'StatusID',        value: '', type: 'string'},
      ]
    },
    horizoninterp: {
      kind: 'osdu:wks:work-product-component--HorizonInterpretation:1.2.0',
      desc: '<b>Horizon Interpretation</b> &mdash; the geological meaning of a mapped horizon surface. SMEs assign conformability, sequence-stratigraphic role, and chronostratigraphic age.',
      fields: [
        {key: 'Name',                  value: '', type: 'string'},
        {key: 'Description',           value: '', type: 'string'},
        {key: 'StratigraphicUnitInterpretationAboveID', value: '', type: 'string'},
        {key: 'StratigraphicUnitInterpretationBelowID', value: '', type: 'string'},
        {key: 'HorizonTypeID',         value: '', type: 'string'},
        {key: 'SequenceStratigraphicSurfaceTypeID', value: '', type: 'string'},
      ]
    },
    devconcept: {
      kind: 'osdu:wks:work-product-component--DevelopmentConcept:3.0.0',
      desc: '<b>Development Concept</b> &mdash; describes how a field will be developed: facility type, well plan, drainage strategy, production technology. Links to Field, Reservoir, and decision gates.',
      fields: [
        {key: 'Name',                 value: '', type: 'string'},
        {key: 'Description',          value: '', type: 'string'},
        {key: 'FieldID',              value: '', type: 'string'},
        {key: 'ProjectName',          value: '', type: 'string'},
        {key: 'FacilityConcept',      value: '', type: 'json'},
        {key: 'WellPlan',             value: '', type: 'json'},
        {key: 'DrainageStrategy',     value: '', type: 'json'},
      ]
    },
    refdata: {
      kind: 'osdu:wks:reference-data--',
      desc: '<b>Reference Data</b> &mdash; a classification / taxonomy entry (DecisionLevel, RiskCategory, ParameterType, UnitOfMeasure, etc.). These are organization-specific seed records. Edit the <i>Kind</i> field to set the specific type.',
      fields: [
        {key: 'Name',            value: '', type: 'string'},
        {key: 'Description',     value: '', type: 'string'},
        {key: 'Code',            value: '', type: 'string'},
      ]
    },
    custom: {
      kind: '',
      desc: '<b>Custom Kind</b> &mdash; enter any OSDU kind manually and build the data block from scratch. For types not listed above or custom/local schemas.',
      fields: [
        {key: 'Name',            value: '', type: 'string'},
        {key: 'Description',     value: '', type: 'string'},
      ]
    },
  };

  var genFields = [];
  var selectedGenType = '';

  window.selectGenType = function(typeName) {
    selectedGenType = typeName;
    var preset = GEN_PRESETS[typeName];
    if (!preset) return;

    // Highlight selected card
    document.querySelectorAll('.gen-type-card').forEach(function(c) {
      c.classList.toggle('selected', c.id === 'gtc-' + typeName);
    });

    // Set kind
    document.getElementById('gen-kind').value = preset.kind;
    document.getElementById('gen-kind-row').style.display = '';

    // Show description
    var descEl = document.getElementById('gen-type-desc');
    descEl.innerHTML = preset.desc;
    descEl.style.display = '';

    // Pre-populate fields (replace existing)
    genFields = preset.fields.map(function(f) { return {key: f.key, value: f.value, type: f.type}; });
    renderGenFields();

    // Focus kind for refdata/custom so user can complete it
    if (typeName === 'refdata' || typeName === 'custom') {
      document.getElementById('gen-kind').focus();
    }
  };

  window.addGenField = function() {
    var keyInp = document.getElementById('gen-field-key');
    var valInp = document.getElementById('gen-field-value');
    var typeInp = document.getElementById('gen-field-type');
    var k = keyInp.value.trim();
    var v = valInp.value;
    var t = typeInp.value;
    if (!k) { alert('Field key is required.'); return; }
    genFields.push({key: k, value: v, type: t});
    keyInp.value = ''; valInp.value = ''; typeInp.value = 'auto';
    renderGenFields();
  };

  window.removeGenField = function(idx) {
    genFields.splice(idx, 1);
    renderGenFields();
  };

  function renderGenFields() {
    var el = document.getElementById('gen-field-list');
    if (!genFields.length) { el.innerHTML = '<span class="muted" style="font-size:13px;">Select a record type above to pre-populate fields.</span>'; return; }
    el.innerHTML = genFields.map(function(f, i) {
      var valDisplay = f.value.length > 60 ? f.value.substring(0, 57) + '…' : (f.value || '<em class="muted">empty</em>');
      var valHtml = f.value ? escHtml(valDisplay) : valDisplay;
      return '<div class="risk-item" style="gap:4px;">' +
             '<strong style="min-width:160px;font-size:12px;color:var(--eq-charcoal);">' + escHtml(f.key) + '</strong>' +
             '<span style="font-size:10px;color:var(--eq-grey);min-width:40px;">[' + f.type + ']</span>' +
             '<input type="text" value="' + escAttr(f.value) + '" ' +
             'oninput="genFields[' + i + '].value=this.value" ' +
             'style="flex:1;font-size:12px;padding:2px 6px;border:1px solid var(--eq-border);border-radius:3px;" />' +
             '<button class="remove-btn" onclick="removeGenField(' + i + ')" title="Remove">&times;</button></div>';
    }).join('');
  }
  renderGenFields();

  function buildGenPayload() {
    return {
      kind:      document.getElementById('gen-kind').value.trim(),
      record_id: document.getElementById('gen-record-id').value.trim(),
      fields:    genFields.slice(),
    };
  }

  window.previewGenRecord = function() {
    var payload = buildGenPayload();
    var wrap = document.getElementById('gen-preview-wrap');
    var pre = document.getElementById('gen-preview-json');
    pre.textContent = JSON.stringify(payload, null, 2);
    wrap.style.display = 'block';
  };

  window.submitGenRecord = function() {
    var payload = buildGenPayload();
    if (!payload.kind) { alert('Please enter a kind.'); return; }
    if (!payload.fields.length) { alert('Please add at least one data field.'); return; }

    document.getElementById('submit-overlay').classList.add('active');
    document.getElementById('gen-result-area').innerHTML = '';

    fetch('/add-dg/create-generic', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    })
    .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
    .then(function(res) {
      document.getElementById('submit-overlay').classList.remove('active');
      var area = document.getElementById('gen-result-area');
      if (res.data.ok) {
        area.innerHTML = '<div class="result-ok">' +
          '<strong>&#10003; Record created successfully</strong><br>' +
          '<span class="bd-id">' + escHtml(res.data.record_id) + '</span><br>' +
          '<span class="muted">Kind: ' + escHtml(res.data.kind) + ' &middot; Status: ' + res.status +
          ' &middot; ' + res.data.field_count + ' fields</span></div>';
      } else {
        area.innerHTML = '<div class="result-err">' +
          '<strong>Ingest failed (HTTP ' + res.status + ')</strong><br>' +
          '<pre style="margin:.4rem 0 0;font-size:12px;white-space:pre-wrap;">' +
          escHtml(res.data.response || res.data.error || JSON.stringify(res.data)) + '</pre></div>';
      }
    })
    .catch(function(err) {
      document.getElementById('submit-overlay').classList.remove('active');
      document.getElementById('gen-result-area').innerHTML =
        '<div class="result-err"><strong>Network error:</strong> ' + escHtml(err.message) + '</div>';
    });
  };

})();
</script>
