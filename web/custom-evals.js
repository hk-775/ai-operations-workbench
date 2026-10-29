function createCustomEvals({api,action,notice,canEdit,getEpoch,download}) {
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const usd=value=>value===null||value===undefined?'Unknown':`$${value}`;
  const kinds={exact_text:'Exact text, including whitespace',contains_text:'Contains literal text',excludes_text:'Excludes literal text',json_object:'Is a valid JSON object',json_field_equals:'JSON field matches value and type'};
  let suites=[],runs=[],editing=null,selected=null,suitePage=0,runPage=0,casePage=0,sequence=0,resultSequence=0;
  function addCheck(parent,rule={kind:'exact_text',expected:'',pointer:'',ignore_case:false}) {
    if(parent.children.length>=10)throw new Error('Each case supports at most ten checks.');
    const row=document.createElement('div');row.className='custom-check workflow-rule';
    row.innerHTML=`<div class="billing-form-grid"><label class="field">Check type<select class="rule-kind">${Object.entries(kinds).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label><label class="field rule-pointer-field">JSON field pointer<input class="rule-pointer" maxlength="300" value="${esc(rule.pointer)}" placeholder="/action"><small>Use /action for a field, or /items/0 for an array entry.</small></label><label class="field rule-expected-field wide-field">Expected value or literal text<textarea class="rule-expected" maxlength="4000">${esc(rule.expected)}</textarea><small>For a JSON field, enter a JSON value such as "escalate", false, or 0. Exact text checks preserve whitespace.</small></label></div><label class="check rule-case-field"><input class="rule-ignore-case" type="checkbox">Ignore text case</label><button class="button small" type="button" data-remove-check>Remove check</button>`;
    row.querySelector('.rule-kind').value=rule.kind;
    row.querySelector('.rule-ignore-case').checked=rule.ignore_case;
    parent.append(row);checkFields(row);
  }
  function checkFields(row) {
    const kind=row.querySelector('.rule-kind').value;
    row.querySelector('.rule-pointer-field').hidden=kind!=='json_field_equals';
    row.querySelector('.rule-expected-field').hidden=kind==='json_object';
    row.querySelector('.rule-case-field').hidden=kind.startsWith('json_');
  }
  function addCase(value) {
    if($('custom-case-editor').children.length>=100)throw new Error('A suite supports at most 100 cases.');
    const data=value||{id:'case-'+crypto.randomUUID().slice(0,8),name:'',input:'',critical:false,checks:[{kind:'exact_text',expected:'',pointer:'',ignore_case:false}]};
    const row=document.createElement('details');row.className='custom-case-editor-row workflow-rule';row.open=!value||$('custom-case-editor').children.length===0;
    row.innerHTML=`<summary><strong class="custom-case-title">${esc(data.name||'New case')}</strong></summary><div class="billing-form-grid"><label class="field">Case name<input class="case-name" required maxlength="100" value="${esc(data.name)}"></label><label class="field">Stable case ID<input class="case-id" required maxlength="80" pattern="[A-Za-z0-9][A-Za-z0-9_\\-]*" value="${esc(data.id)}"></label><label class="field wide-field">Input or task context<textarea class="case-input" maxlength="4000">${esc(data.input)}</textarea></label></div><label class="check"><input class="case-critical" type="checkbox">Critical case: any failed check counts as a critical failure</label><div class="custom-checks"></div><div class="row-actions"><button class="button small" type="button" data-add-check>Add check</button><button class="button small" type="button" data-remove-case>Remove case</button></div>`;
    row.querySelector('.case-critical').checked=data.critical;
    $('custom-case-editor').append(row);data.checks.forEach(rule=>addCheck(row.querySelector('.custom-checks'),rule));
  }
  function formValue() {
    const form=$('custom-suite-form');
    return {reference:form.elements.reference.value,name:form.elements.name.value,description:form.elements.description.value,
      active:editing?.value.active??true,evidence:form.elements.fixture.checked?'fixture':'declared',
      cases:[...$('custom-case-editor').children].map(row=>({
        id:row.querySelector('.case-id').value,name:row.querySelector('.case-name').value,
        input:row.querySelector('.case-input').value,critical:row.querySelector('.case-critical').checked,
        checks:[...row.querySelector('.custom-checks').children].map(check=>{
          const kind=check.querySelector('.rule-kind').value;
          return {kind,expected:kind==='json_object'?'':check.querySelector('.rule-expected').value,
            pointer:kind==='json_field_equals'?check.querySelector('.rule-pointer').value:'',
            ignore_case:kind.startsWith('json_')?false:check.querySelector('.rule-ignore-case').checked};
        })
      }))};
  }
  function formReset() {
    editing=null;$('custom-suite-form').reset();$('custom-suite-form').elements.reference.readOnly=false;
    $('custom-suite-form').elements.fixture.disabled=false;$('custom-case-editor').replaceChildren();addCase();
    $('custom-edit-note').textContent='Create a reusable suite. Saving later changes creates another immutable revision.';
  }
  function fill(value,record=null) {
    editing=record;const form=$('custom-suite-form');
    for(const key of ['name','reference','description'])form.elements[key].value=value[key]||'';
    form.elements.fixture.checked=value.evidence==='fixture';form.elements.fixture.disabled=Boolean(record);
    form.elements.reference.readOnly=Boolean(record);
    $('custom-case-editor').replaceChildren();value.cases.forEach(addCase);
    $('custom-edit-note').textContent=record?`Editing revision ${record.revision}. Existing runs keep their original cases and checks.`:'Review these cases before saving a new suite.';
    $('custom-editor').open=true;$('custom-editor').scrollIntoView({block:'start'});
  }
  async function load() {
    const request=sequence+1;$('page-custom').setAttribute('aria-busy','true');
    try {await loadData();}
    finally {if(request===sequence)$('page-custom').setAttribute('aria-busy','false');}
  }
  async function loadData() {
    const current=++sequence,epoch=getEpoch();
    const [suiteRows,runRows]=await Promise.all([
      api(`/api/pilot/custom-evals/suites?page=${suitePage}&include_fixtures=${$('custom-fixtures').checked}`),
      api(`/api/pilot/custom-evals/runs?page=${runPage}`)]);
    if(epoch!==getEpoch()||current!==sequence)return;
    suites=suiteRows.items;runs=runRows.items;
    $('custom-suites').innerHTML=suites.map(row=>`<article class="panel"><div class="workflow-card-head"><div><h2>${esc(row.value.name)}</h2><p class="fine">${row.value.case_count} cases · revision ${row.revision} · ${esc(row.value.reference)}</p></div><span class="tag ${row.value.evidence==='fixture'?'warn':'accent'}">${row.value.evidence==='fixture'?'Fictional suite':'Company-defined checks'}${row.value.active?'':' · archived'}</span></div><p class="data-note">${esc(row.value.description)}</p><div class="row-actions"><button class="button" data-custom-template="${row.id}">Download answer template</button><button class="button" data-custom-suite-export="${row.id}">Download suite</button>${canEdit()?`<button class="button" data-custom-edit="${row.id}">Edit suite</button><button class="button" data-custom-active="${row.id}">${row.value.active?'Archive suite':'Restore suite'}</button>`:''}<button class="button" data-custom-history="${row.id}">View suite revisions</button></div></article>`).join('')||'<article class="panel"><h2>No suites in this view.</h2><p class="data-note">Create your own cases above or try the fictional example to see the workflow.</p></article>';
    $('custom-runs').innerHTML=runs.map(row=>`<article class="panel"><div class="workflow-card-head"><div><h2>${esc(row.name)}</h2><p class="fine">Suite revision ${row.suite_revision} · ${esc(new Date(row.created_at*1000).toLocaleString())}</p></div><span class="tag ${row.evidence==='fixture'?'warn':'accent'}">${row.evidence==='fixture'?'Fictional evidence':'Imported evidence'}</span></div><p class="data-note">${row.summaries.map(model=>`${esc(model.model)}: ${model.passed}/${model.cases} passed, ${model.critical_failures} critical failures`).join(' · ')}</p><button class="button" data-custom-inspect="${row.id}">Inspect custom results</button></article>`).join('')||'<p class="notice">No saved runs yet. Use an answer template from a saved suite, then choose the filled file above.</p>';
    for(const [kind,data,page] of [['suites',suiteRows,suitePage],['runs',runRows,runPage]]) {
      $('custom-'+kind+'-prev').disabled=page===0;$('custom-'+kind+'-next').disabled=!data.has_more;$('custom-'+kind+'-page').textContent=`Page ${page+1}`;
    }
  }
  function renderResult() {
    const result=selected;if(!result)return;
    const definitions=new Map(result.suite.cases.map(row=>[row.id,row]));
    const rows=result.cases.slice(casePage*25,(casePage+1)*25);
    $('custom-result').innerHTML=`<article class="panel"><div class="workflow-card-head"><div><p class="eyebrow">SAVED CUSTOM EVALUATION</p><h2>${esc(result.name)}</h2><p class="fine">Suite revision ${result.suite_revision} · ${esc(result.cost_basis.replaceAll('_',' '))}</p></div><span class="tag ${result.evidence==='fixture'?'warn':'accent'}">${result.evidence==='fixture'?'Fictional evidence':'Imported evidence'}</span></div>
      <div class="table-wrap"><table><thead><tr><th>Model label</th><th>Passed</th><th>Critical failures</th><th>Missing cases</th><th>Known cost subtotal</th><th>Cost coverage</th><th>Cost per passing case</th><th>Supplied p95</th></tr></thead><tbody>${result.summaries.map(row=>`<tr><td>${esc(row.model)}</td><td>${row.passed}/${row.cases}</td><td>${row.critical_failures}</td><td>${row.missing_cases}</td><td>${esc(usd(row.known_cost_usd))}</td><td>${row.known_cost_cases}/${row.cases}</td><td>${esc(usd(row.cost_per_passing_case_usd))}</td><td>${row.p95_ms===null?'Unmeasured':esc(row.p95_ms)+' ms'} · ${row.latency_cases}/${row.cases} timings</td></tr>`).join('')}</tbody></table></div>
      <ul class="proposal-copy">${result.limitations.map(text=>`<li>${esc(text)}</li>`).join('')}</ul><button class="button" data-custom-export-run="${result.id}">Download custom evaluation evidence</button>
      <div class="controls"><label class="field">Compare with an earlier run<select id="custom-baseline"><option value="">Choose a compatible saved run</option>${runs.filter(row=>row.id!==result.id&&row.suite_id===result.suite_id&&row.suite_revision===result.suite_revision&&row.evidence===result.evidence&&row.cost_basis===result.cost_basis).map(row=>`<option value="${row.id}">${esc(row.name)} · ${esc(new Date(row.created_at*1000).toLocaleString())}</option>`).join('')}</select></label><button class="button" data-custom-compare>Compare saved runs</button></div><p class="fine">The comparison list uses the current page of runs. The server also checks evaluator and model-roster compatibility.</p><div id="custom-comparison"></div>
      <h3>Case evidence</h3>${rows.map(row=>{
        const definition=definitions.get(row.case_id);
        return `<details class="workflow-case"><summary>${esc(row.model)} · ${esc(row.name)} · ${row.passed?'Passed':row.critical?'Critical failure':'Failed'}${row.status==='missing'?' · missing answer':''}</summary><p class="data-note">${esc(definition.input)}</p><p class="fine">Saved status: ${esc(row.status)} · case cost ${esc(usd(row.cost_usd))}</p><h3>Saved answer</h3><pre>${esc(row.output??'No saved output')}</pre><h3>Checks and expectations</h3><ul>${row.checks.map((check,index)=>`<li><strong>${check.passed?'PASSED':'FAILED'}</strong> · ${esc(kinds[check.kind])}${definition.checks[index].pointer?' · '+esc(definition.checks[index].pointer):''}<pre>${esc(definition.checks[index].expected)}</pre></li>`).join('')}</ul></details>`;
      }).join('')}<div class="pagination"><button class="button" data-custom-cases-prev ${casePage===0?'disabled':''}>Previous case evidence</button><span>Page ${casePage+1} · ${result.cases.length} model/case results</span><button class="button" data-custom-cases-next ${(casePage+1)*25>=result.cases.length?'disabled':''}>Next case evidence</button></div></article>`;
  }
  async function fileText(input) {
    const file=input.files[0];if(!file)return null;
    if(file.size>2_000_000)throw new Error('Use a JSON file under 2 MB.');
    return new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
  }
  $('custom-suite-form').onsubmit=event=>{
    event.preventDefault();action(async()=>{
      const button=event.submitter;button.disabled=true;
      try {
        const saved=await api(`/api/pilot/custom-evals/suites${editing?'/'+editing.id:''}`,{value:formValue(),revision:editing?.revision||0});
        if(saved.value.evidence==='fixture')$('custom-fixtures').checked=true;
        formReset();$('custom-editor').open=false;await load();notice(`Evaluation suite revision ${saved.revision} saved.`);
      } finally {button.disabled=false;}
    });
  };
  $('custom-example').onclick=()=>action(async()=>fill(await api('/api/pilot/custom-evals/example')));
  $('custom-add-case').onclick=()=>action(async()=>addCase());
  $('custom-new').onclick=formReset;
  $('custom-refresh').onclick=()=>action(load);
  $('custom-fixtures').onchange=()=>action(async()=>{suitePage=0;await load();});
  $('custom-suite-upload').onchange=()=>action(async()=>{
    const text=await fileText($('custom-suite-upload'));if(text===null)return;
    const definition=await api('/api/pilot/custom-evals/suites/preview',text,true);
    fill(definition);$('custom-suite-upload').value='';
  });
  $('custom-run-upload').onchange=()=>action(async()=>{
    const text=await fileText($('custom-run-upload'));if(text===null)return;
    const request=++resultSequence,result=await api('/api/pilot/custom-evals/runs',text,true);
    if(request!==resultSequence)return;
    selected=result;casePage=0;$('custom-run-upload').value='';await load();renderResult();$('custom-result').scrollIntoView({block:'start'});notice('Saved answers evaluated. Inspect the coverage and failed cases below.');
  });
  for(const kind of ['suites','runs'])for(const direction of ['prev','next']) {
    $('custom-'+kind+'-'+direction).onclick=()=>action(async()=>{const delta=direction==='prev'?-1:1;if(kind==='suites')suitePage+=delta;else runPage+=delta;await load();});
  }
  $('page-custom').addEventListener('input',event=>{
    if(event.target.matches('.case-name'))event.target.closest('.custom-case-editor-row').querySelector('.custom-case-title').textContent=event.target.value||'New case';
  });
  $('page-custom').addEventListener('change',event=>{if(event.target.matches('.rule-kind'))checkFields(event.target.closest('.custom-check'));});
  $('page-custom').addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button)return;const d=button.dataset;
    if(d.addCheck!==undefined)action(async()=>addCheck(button.closest('.custom-case-editor-row').querySelector('.custom-checks')));
    if(d.removeCheck!==undefined){const row=button.closest('.custom-check');if(row.parentElement.children.length>1)row.remove();}
    if(d.removeCase!==undefined&&$('custom-case-editor').children.length>1)button.closest('.custom-case-editor-row').remove();
    if(d.customEdit)action(async()=>{const record=await api(`/api/pilot/custom-evals/suites/${d.customEdit}/export`);fill(record.value,record);});
    if(d.customActive)action(async()=>{const record=await api(`/api/pilot/custom-evals/suites/${d.customActive}/export`);await api(`/api/pilot/custom-evals/suites/${record.id}`,{value:{...record.value,active:!record.value.active},revision:record.revision});await load();});
    if(d.customTemplate)action(async()=>download('workbench-saved-answers-template.json',await api(`/api/pilot/custom-evals/suites/${d.customTemplate}/template`)));
    if(d.customSuiteExport)action(async()=>download('workbench-evaluation-suite.json',await api(`/api/pilot/custom-evals/suites/${d.customSuiteExport}/export`)));
    if(d.customInspect)action(async()=>{const request=++resultSequence,result=await api(`/api/pilot/custom-evals/runs/${d.customInspect}`);if(request!==resultSequence)return;selected=result;casePage=0;renderResult();$('custom-result').scrollIntoView({block:'start'});});
    if(d.customExportRun)action(async()=>download('workbench-custom-evaluation.json',await api(`/api/pilot/custom-evals/runs/${d.customExportRun}/export`)));
    if(d.customCompare!==undefined)action(async()=>{
      const baseline=$('custom-baseline').value;if(!baseline)throw new Error('Choose a baseline run first.');
      const request=resultSequence,identity=selected.id;
      const comparison=await api(`/api/pilot/custom-evals/runs/${identity}/compare/${baseline}`);
      if(request!==resultSequence||selected?.id!==identity||$('custom-baseline')?.value!==baseline)return;
      $('custom-comparison').innerHTML=`<p class="data-note">${comparison.regressions.length} regressions · ${comparison.critical_regressions} critical regressions · ${comparison.improvements.length} improvements</p><ul>${comparison.regressions.map(row=>`<li>${esc(row.model)} · ${esc(row.case_id)}${row.critical?' · critical':''}</li>`).join('')}</ul><p class="fine">${esc(comparison.note)}</p>`;
    });
    if(d.customCasesPrev!==undefined){casePage--;renderResult();}
    if(d.customCasesNext!==undefined){casePage++;renderResult();}
    if(d.customHistory)action(async()=>{
      const request=++resultSequence;
      const record=await api(`/api/pilot/custom-evals/suites/${d.customHistory}/history`);
      if(request!==resultSequence)return;
      selected=null;
      $('custom-result').innerHTML=`<article class="panel"><h2>Suite revision history</h2><div class="row-actions">${record.revisions.map(row=>`<button class="button" data-custom-revision="${row.revision}" data-id="${record.id}">Download suite revision ${row.revision}</button>`).join('')}</div>${record.has_more?'<p class="fine">Showing the latest 25 revisions; older pages remain available through the history API.</p>':''}</article>`;$('custom-result').scrollIntoView({block:'start'});
    });
    if(d.customRevision)action(async()=>download('workbench-suite-revision.json',await api(`/api/pilot/custom-evals/suites/${d.id}/export?revision=${d.customRevision}`)));
  });
  function reset() {
    sequence++;resultSequence++;suites=[];runs=[];selected=null;suitePage=0;runPage=0;casePage=0;
    $('page-custom').setAttribute('aria-busy','false');
    for(const id of ['custom-suites','custom-runs','custom-result'])$(id).replaceChildren();
    $('custom-fixtures').checked=false;$('custom-suite-upload').value='';$('custom-run-upload').value='';
    formReset();$('custom-editor').open=false;
  }
  reset();
  return {load,reset};
}
