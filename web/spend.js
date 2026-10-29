function createSpend({api,action,notice,isAdmin,getEpoch,download}) {
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const usd=value=>value===null||value===undefined?'Unknown':`$${String(value).replace(/(\.\d{2,}?)0+$/,'$1')}`;
  const labels={api_estimate_usd:'Estimated API spend',reported_model_estimate_usd:'Tool-reported model amount',reported_charge_usd:'Cursor-reported usage amount',allocated_usd:'Allocated monthly cost pools'};
  const states={at_limit:'At or above limit',warning:'Warning threshold reached',projected_over:'Projected over budget',incomplete:'Incomplete evidence',within_budget:'Within declared budget'};
  let budgets=[],allocations=[],sources=[],budgetPage=0,allocationPage=0,sequence=0;
  let budgetEdit=null,allocationEdit=null;
  const month=()=>new Date().toISOString().slice(0,7);
  const query=()=>`include_fixtures=${$('spend-fixtures').checked}`;
  const tag=(text,kind='accent')=>`<span class="tag ${kind}">${esc(text)}</span>`;
  function formReset(kind) {
    const form=$(kind+'-form');form.reset();
    form.elements.month.value=month();
    form.elements.reference.readOnly=false;form.elements.month.readOnly=false;form.elements.fixture.disabled=false;
    if(kind==='budget') {budgetEdit=null;$('budget-edit-note').textContent='Create a new budget. Revisions to an existing budget are saved separately.';sourceOptions();}
    else {allocationEdit=null;$('allocation-edit-note').textContent='Use the same reference and month when correcting an existing cost pool.';$('allocation-shares').replaceChildren();addShare();$('allocation-preview-result').replaceChildren();}
  }
  function sourceOptions() {
    const field=$('budget-source'),selected=field.value,basis=$('budget-form').elements.cost_basis.value;
    const kinds={api_estimate_usd:['axonllm','bedrock'],reported_model_estimate_usd:['claude_code','cursor'],reported_charge_usd:['cursor'],allocated_usd:[]}[basis];
    field.innerHTML='<option value="">All compatible sources</option>'+sources.filter(s=>kinds.includes(s.kind)).map(s=>`<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('');
    field.value=[...field.options].some(option=>option.value===selected)?selected:'';
    field.disabled=basis==='allocated_usd';
  }
  function addShare(value={project:'',weight:1}) {
    if($('allocation-shares').children.length>=100)throw new Error('A cost pool supports at most 100 project shares.');
    $('allocation-preview-result').replaceChildren();
    const row=document.createElement('div');row.className='workflow-share';
    row.innerHTML=`<label class="field">Project<input class="share-project" required maxlength="100" value="${esc(value.project)}"></label><label class="field">Relative weight<input class="share-weight" type="number" min="1" max="1000000" step="1" required value="${esc(value.weight)}"></label><button class="button small" type="button" data-remove-share>Remove share</button>`;
    $('allocation-shares').append(row);
  }
  function valueFrom(kind) {
    const form=$(kind+'-form'),data=new FormData(form),editing=kind==='budget'?budgetEdit:allocationEdit;
    const value={reference:data.get('reference'),name:data.get('name'),month:data.get('month'),
      active:editing?.value.active??true,evidence:form.elements.fixture.checked?'fixture':'declared'};
    if(kind==='budget')Object.assign(value,{limit_usd:data.get('limit_usd'),cost_basis:data.get('cost_basis'),
      warning_percent:Number(data.get('warning_percent')),project:data.get('project')||null,
      source_id:form.elements.source_id.disabled?null:data.get('source_id')||null,
      coverage_confirmed:form.elements.coverage_confirmed.checked});
    else Object.assign(value,{amount_usd:data.get('amount_usd'),category:data.get('category'),reason:data.get('reason'),
      shares:[...$('allocation-shares').children].map(row=>({project:row.querySelector('.share-project').value,
        weight:Number(row.querySelector('.share-weight').value)}))});
    return {value,revision:editing?.revision||0};
  }
  function allocationTable(result) {
    return `<div class="table-wrap"><table><thead><tr><th>Project</th><th>Weight</th><th>Allocated USD</th></tr></thead><tbody>${result.allocations.map(row=>`<tr><td>${esc(row.project)}</td><td>${row.weight}</td><td>${esc(usd(row.allocated_usd))}</td></tr>`).join('')}</tbody></table></div><p class="data-note">Total allocated: ${esc(usd(result.allocated_total_usd))}. ${esc(result.note)}</p>`;
  }
  function budgetCard(row) {
    const v=row.value,r=row.result,source=sources.find(item=>item.id===v.source_id);
    const state=v.active?states[r.status]:'Archived';
    return `<article class="panel"><div class="workflow-card-head"><div><h2>${esc(v.name)}</h2><p class="fine">${esc(v.month)} UTC · ${esc(v.project||'All projects')} · ${esc(source?.name||'All compatible sources')} · revision ${row.revision}</p></div>${tag(state,r.status==='at_limit'?'bad':r.status==='within_budget'?'good':'warn')}${v.evidence==='fixture'?tag('Fictional example','warn'):''}</div>
      <p class="data-note">${esc(labels[v.cost_basis])}</p>
      <div class="workflow-measures"><div><small>Tracked amount</small><strong>${esc(usd(r.tracked_usd))}</strong></div><div><small>Monthly limit</small><strong>${esc(usd(r.limit_usd))}</strong></div><div><small>${v.cost_basis==='allocated_usd'?'Confirmed monthly allocation':'Captured-pace month projection'}</small><strong>${esc(usd(r.forecast_usd))}</strong></div></div>
      <p class="fine">${r.priced_records} of ${r.records} ${esc(r.record_kind)} have amounts. ${esc(r.amount_note)}</p>
      ${r.projection_unavailable_reasons.length?`<ul class="proposal-copy">${r.projection_unavailable_reasons.map(text=>`<li>${esc(text)}</li>`).join('')}</ul>`:`<p class="data-note">${esc(r.projection_basis)}</p>`}
      <div class="row-actions">${isAdmin()?`<button class="button" data-budget-edit="${row.id}">Edit budget</button><button class="button" data-spend-active="budget" data-id="${row.id}">${v.active?'Archive budget':'Restore budget'}</button>`:''}<button class="button" data-spend-export="budget" data-id="${row.id}">Download budget evidence</button><button class="button" data-spend-history="budget" data-id="${row.id}">View revisions</button></div></article>`;
  }
  function allocationCard(row) {
    const v=row.value;
    return `<article class="panel"><div class="workflow-card-head"><div><h2>${esc(v.name)}</h2><p class="fine">${esc(v.month)} UTC · ${esc(v.category.replace('_',' '))} · ${esc(v.reference)} · revision ${row.revision}</p></div>${tag(v.active?'Declared allocation':'Voided',v.active?'accent':'warn')}${v.evidence==='fixture'?tag('Fictional example','warn'):''}</div><p class="data-note">${esc(v.reason)}</p>${allocationTable(row.result)}
      <div class="row-actions">${isAdmin()?`<button class="button" data-allocation-edit="${row.id}">Edit cost pool</button><button class="button" data-spend-active="allocation" data-id="${row.id}">${v.active?'Void cost pool':'Restore cost pool'}</button>`:''}<button class="button" data-spend-export="allocation" data-id="${row.id}">Download allocation</button><button class="button" data-spend-history="allocation" data-id="${row.id}">View revisions</button></div></article>`;
  }
  async function load() {
    const request=sequence+1;$('page-spend').setAttribute('aria-busy','true');
    try {await loadData();}
    finally {if(request===sequence)$('page-spend').setAttribute('aria-busy','false');}
  }
  async function loadData() {
    const current=++sequence,epoch=getEpoch();
    const selectedMonth=$('allocation-summary-month').value||month();
    $('allocation-summary-month').value=selectedMonth;
    const [budgetRows,allocationRows,sourceRows,summary,fictional]=await Promise.all([
      api(`/api/pilot/spend/budgets?page=${budgetPage}&${query()}`),
      api(`/api/pilot/spend/allocations?page=${allocationPage}&${query()}`),
      api('/api/pilot/sources'),
      api(`/api/pilot/spend/summary?month=${encodeURIComponent(selectedMonth)}`),
      $('spend-fixtures').checked?api(`/api/pilot/spend/summary?month=${encodeURIComponent(selectedMonth)}&fixture=true`):null]);
    if(epoch!==getEpoch()||current!==sequence)return;
    budgets=budgetRows.items;allocations=allocationRows.items;sources=sourceRows.sources;sourceOptions();
    $('budget-list').innerHTML=budgets.map(budgetCard).join('')||'<article class="panel"><h2>No budgets in this view.</h2><p class="data-note">An administrator can create a monthly budget above. Select a cost basis that matches the amounts your source provides.</p></article>';
    $('allocation-list').innerHTML=allocations.map(allocationCard).join('')||'<article class="panel"><h2>No declared cost pools in this view.</h2><p class="data-note">An administrator can enter a monthly charge and choose how to share it among projects.</p></article>';
    const totals=(data,label)=>`<h3>${label}</h3>`+(data.projects.length?`<p class="data-note">${data.pools} current cost pools · ${esc(usd(data.allocated_total_usd))} allocated</p><div class="table-wrap"><table><thead><tr><th>Project</th><th>Cost pools</th><th>Allocated USD</th></tr></thead><tbody>${data.projects.map(row=>`<tr><td>${esc(row.project)}</td><td>${row.pools}</td><td>${esc(usd(row.allocated_usd))}</td></tr>`).join('')}</tbody></table></div>`:'<p class="data-note">No current cost pools for this month. The total remains unknown.</p>');
    $('allocation-summary').innerHTML=totals(summary,'Declared company cost pools')+(fictional?totals(fictional,'Fictional cost pools — shown separately'):'');
    for(const [kind,data,page] of [['budget',budgetRows,budgetPage],['allocation',allocationRows,allocationPage]]) {
      $(kind+'-prev').disabled=page===0;$(kind+'-next').disabled=!data.has_more;$(kind+'-page').textContent=`Page ${page+1}`;
    }
  }
  function edit(kind,row) {
    const form=$(kind+'-form'),v=row.value;
    if(kind==='budget')budgetEdit=row;else allocationEdit=row;
    for(const [key,value] of Object.entries(v))if(form.elements[key]&&key!=='evidence'&&key!=='shares') {
      const field=form.elements[key];if(field.type==='checkbox')field.checked=Boolean(value);else field.value=value??'';
    }
    if(kind==='budget'){sourceOptions();form.elements.source_id.value=v.source_id||'';}
    else {$('allocation-shares').replaceChildren();v.shares.forEach(addShare);$('allocation-preview-result').replaceChildren();}
    form.elements.fixture.checked=v.evidence==='fixture';form.elements.fixture.disabled=true;
    form.elements.reference.readOnly=true;form.elements.month.readOnly=true;
    $(kind+'-edit-note').textContent=`Editing revision ${row.revision}. Saving creates the next revision. The reference, month and evidence type stay fixed.`;
    $(kind+'-editor').open=true;$(kind+'-editor').scrollIntoView({block:'start'});
  }
  for(const kind of ['budget','allocation']) {
    $(kind+'-form').addEventListener('submit',event=>{
      event.preventDefault();action(async()=>{
        const button=event.submitter,editing=kind==='budget'?budgetEdit:allocationEdit;button.disabled=true;
        try {
          const payload=valueFrom(kind),plural=kind==='budget'?'budgets':'allocations';
          const saved=await api(`/api/pilot/spend/${plural}${editing?'/'+editing.id:''}`,payload);
          if(saved.value.evidence==='fixture')$('spend-fixtures').checked=true;
          formReset(kind);$(kind+'-editor').open=false;await load();notice(`${kind==='budget'?'Budget':'Cost pool'} revision ${saved.revision} saved.`);
        } finally {button.disabled=false;}
      });
    });
    $(kind+'-new').onclick=()=>formReset(kind);
    $(kind+'-prev').onclick=()=>action(async()=>{if(kind==='budget')budgetPage--;else allocationPage--;await load();});
    $(kind+'-next').onclick=()=>action(async()=>{if(kind==='budget')budgetPage++;else allocationPage++;await load();});
  }
  $('budget-form').elements.cost_basis.onchange=sourceOptions;
  $('allocation-add-share').onclick=()=>action(async()=>addShare());
  $('allocation-form').addEventListener('input',()=>$('allocation-preview-result').replaceChildren());
  $('allocation-preview').onclick=()=>action(async()=>{
    if(!$('allocation-form').reportValidity())return;
    const payload=valueFrom('allocation');
    const result=await api('/api/pilot/spend/allocations/preview',payload);
    if(JSON.stringify(payload)===JSON.stringify(valueFrom('allocation')))
      $('allocation-preview-result').innerHTML=allocationTable(result);
  });
  $('spend-refresh').onclick=()=>action(load);
  $('spend-fixtures').onchange=()=>action(async()=>{budgetPage=0;allocationPage=0;await load();});
  $('allocation-summary-month').onchange=()=>action(load);
  $('page-spend').addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button)return;const d=button.dataset;
    if(d.removeShare!==undefined){if($('allocation-shares').children.length>1)button.closest('.workflow-share').remove();$('allocation-preview-result').replaceChildren();return;}
    if(d.budgetEdit)edit('budget',budgets.find(row=>row.id===d.budgetEdit));
    if(d.allocationEdit)edit('allocation',allocations.find(row=>row.id===d.allocationEdit));
    if(d.spendActive)action(async()=>{
      const kind=d.spendActive,row=(kind==='budget'?budgets:allocations).find(item=>item.id===d.id);
      if(kind==='allocation'&&row.value.active&&!confirm('Void this declared cost pool? It will stop contributing to current allocations. Earlier revisions remain available.'))return;
      await api(`/api/pilot/spend/${kind==='budget'?'budgets':'allocations'}/${row.id}`,
        {value:{...row.value,active:!row.value.active},revision:row.revision});
      await load();
    });
    if(d.spendExport)action(async()=>download('workbench-spend-evidence.json',await api(`/api/pilot/spend/${d.spendExport}/${d.id}/export`)));
    if(d.spendHistory)action(async()=>{
      const result=await api(`/api/pilot/spend/${d.spendHistory}/${d.id}/history`);
      $('spend-history').innerHTML=`<article class="panel"><h2>Saved policy revisions</h2><p class="fine">Budget status is recalculated when exported and includes its calculation time.</p><div class="row-actions">${result.revisions.map(row=>`<button class="button" data-spend-revision="${row.revision}" data-kind="${d.spendHistory}" data-id="${result.id}">Download revision ${row.revision}</button>`).join('')}</div>${result.has_more?'<p class="fine">Showing the most recent 25 revisions. Older pages remain available through the history API.</p>':''}</article>`;
      $('spend-history').scrollIntoView({block:'start'});
    });
    if(d.spendRevision)action(async()=>download('workbench-spend-revision.json',await api(`/api/pilot/spend/${d.kind}/${d.id}/export?revision=${d.spendRevision}`)));
  });
  function reset() {
    sequence++;budgets=[];allocations=[];sources=[];budgetPage=0;allocationPage=0;
    $('page-spend').setAttribute('aria-busy','false');
    for(const id of ['budget-list','allocation-list','allocation-summary','spend-history'])$(id).replaceChildren();
    $('spend-fixtures').checked=false;$('allocation-summary-month').value=month();
    formReset('budget');formReset('allocation');
    $('budget-editor').open=false;$('allocation-editor').open=false;
  }
  reset();
  return {load,reset};
}
