/* Private team billing UI. Currency values remain exact server Decimal text. */
function createBilling({api, action, notice, isAdmin, getEpoch, onExample, onTasks}) {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = (value, currency='USD') => value === null || value === undefined ? 'Unavailable' : `${currency} ${esc(value)}`;
  const tag = (label, kind='accent') => `<span class="tag ${kind}">${esc(label)}</span>`;
  let report=null, pending=null, listingPage=0, request=0, importGeneration=0;
  const stable = epoch => epoch === getEpoch();
  const sourceName = id => report?.sources.find(s=>s.id===id)?.name || id;
  const card = (label,value,note) => `<article class="metric" data-flow="connect"><p class="metric-label">${esc(label)}</p><p class="metric-value small-value">${value}</p><p class="metric-sub">${note}</p></article>`;

  function reset() {
    report=null; pending=null; listingPage=0; request++; importGeneration++;
    for(const id of ['billing-report','billing-preview','billing-report-select','billing-list-page','billing-collection']) $(id).replaceChildren();
    $('billing-preview').hidden=true; $('billing-import-form').reset(); $('billing-files').value='';
    $('billing-example').disabled=false;
    $('billing-import-form').querySelector('button[type="submit"]').disabled=false;
    $('billing-previous').disabled=true; $('billing-next').disabled=true;
  }
  function invalidatePreview() {
    pending=null; importGeneration++; $('billing-preview').replaceChildren(); $('billing-preview').hidden=true;
  }
  async function load(selected, recoverMissing=true) {
    const epoch=getEpoch(), token=++request;
    const [value, collection]=await Promise.all([api(`/api/pilot/billing/reports?page=${listingPage}`),api('/api/pilot/billing/collection')]);
    if(!stable(epoch)||token!==request) return;
    const date = value => value ? new Date(value*1000).toLocaleString() : 'Never';
    $('billing-collection').innerHTML=collection.collectors.length?collection.collectors.map(c=>`<div class="billing-comparison"><div class="section-head"><strong>${esc(c.name)}</strong>${tag(c.stale?'Stopped reporting':c.status,c.stale||c.status==='failed'?'warn':'accent')}</div><p>Last attempt: ${esc(date(c.last_attempt_at))}. Last successful collection: ${esc(date(c.last_success_at))}.</p>${c.error?`<p class="data-note">${esc(c.error)} The last accepted snapshot is preserved.</p>`:''}</div>`).join(''):'<p>No automatic collector is configured. Manual CSV import remains available below. Operators can follow docs/BILLING-COLLECTION.md in the source checkout.</p>';
    const options=value.reports;
    const identity=selected || report?.id || options.find(r=>r.current)?.id || options[0]?.id;
    $('billing-report-select').innerHTML=options.length?options.map(r=>`<option value="${esc(r.id)}">${esc(r.name)} · ${esc(r.month)} · account …${esc(r.account_id.slice(-4))} · r${r.revision}${r.current?' · current':' · historical'}${r.evidence==='fixture'?' · fictional':''}</option>`).join(''):'<option value="">No billing snapshots yet</option>';
    $('billing-list-page').textContent=`Snapshot page ${value.page+1}`;
    $('billing-previous').disabled=!value.page; $('billing-next').disabled=!value.has_more;
    if(identity) {
      $('billing-report-select').value=identity;
      await show(identity,recoverMissing);
    } else {
      report=null;
      $('billing-report').innerHTML=`<article class="panel screen-guide"><h2>No billing report is connected yet.</h2><p>Usage overview contains captured API estimates. Import a complete billing export to compare provider charges against the appropriate captured sources.</p><p>${isAdmin()?'Start with the fictional example above or preview your CSV files below.':'An administrator can import billing records and declare source mappings. You can inspect the resulting comparisons here.'}</p></article>`;
    }
  }
  async function show(identity, recoverMissing=true) {
    const epoch=getEpoch(), token=++request;
    let value;
    try {
      value=await api(`/api/pilot/billing/reports/${encodeURIComponent(identity)}`);
    } catch(error) {
      if(!stable(epoch)||token!==request)return;
      report=null;
      $('billing-report-select').value='';
      $('billing-report').innerHTML='<article class="panel screen-guide"><h2>Billing snapshot unavailable.</h2><p>Refresh the billing view or choose another snapshot to inspect current evidence.</p></article>';
      // Retention can remove the selected revision between listing and reading.
      // Retry selection once, without retaining stale amounts or export actions.
      if(error.status===404&&recoverMissing){listingPage=0;await load(undefined,false);return;}
      throw error;
    }
    if(!stable(epoch)||token!==request) return;
    report=value; render();
    const select=$('billing-report-select');
    if(!Array.from(select.options).some(option=>option.value===identity)) {
      select.add(new Option(`${value.name} · ${value.month} · r${value.revision}${value.current?' · current':' · historical'}`,identity));
    }
    select.value=identity;
  }
  function groupTable(values, selectable=false) {
    return `<div class="table-wrap"><table class="billing-table"><thead><tr>${selectable?'<th>Select</th>':''}<th>Provider charge group</th><th>Imported charge</th><th>Reported units</th><th>State / explanation</th></tr></thead><tbody>${values.map(g=>`<tr>
      ${selectable?`<td><input type="checkbox" name="group_ids" value="${esc(g.id)}" aria-label="Select ${esc(g.usage_type || g.charge_type)}" ${!g.eligible||g.selected?'disabled':''}></td>`:''}
      <td><strong>${esc(g.usage_type || g.charge_type)}</strong><small>${esc(g.charge_type)} · ${esc(g.region || 'Region unavailable')}<br>${esc(g.model_hint || 'Model hint unavailable')}<br>${esc(g.operation || 'Operation unavailable')}</small></td>
      <td>${money(g.charge_amount,report.currency)}<small>${g.row_count} line items · ${esc(g.bases.join(', '))}${g.negative_adjustments!=='0'?`<br>Positive ${money(g.positive_charges,report.currency)} · adjustments ${money(g.negative_adjustments,report.currency)}`:''}</small></td>
      <td>${g.quantity===null?'Quantity unavailable':esc(g.quantity)} ${esc(g.unit)}<small>Original billing units; no token conversion assumed.</small></td>
      <td>${g.linked?tag('Linked by declared scope'):tag('Unassigned','warn')}<p class="fine">${g.linked?'Included in a comparison below. Individual task invoice costs remain unknown.':esc(g.unassigned_reason)}</p></td>
    </tr>`).join('')}</tbody></table></div>`;
  }
  function render() {
    const r=report, writable=isAdmin()&&r.current;
    const incomplete=r.comparisons.filter(c=>c.status==='incomplete').length;
    $('billing-report').innerHTML=`
      <article class="panel screen-guide billing-scope">
        <div class="section-head"><div><h2>${esc(r.name)}</h2><p>${esc(r.month)} · Account …${esc(r.account_id.slice(-4))} · Revision ${r.revision} · ${esc(r.currency)}</p></div><div class="row-actions">${tag(r.evidence==='fixture'?'FICTIONAL BILLING EXAMPLE':'Imported billing records',r.evidence==='fixture'?'warn':'accent')}${!r.current?tag('Historical snapshot') : ''}<button class="button" data-billing-export>Export reconciliation</button></div></div>
        <p>${r.uninvoiced_rows?`${r.uninvoiced_rows} lines have no invoice identifier. Treat this report as provisional; later exports may change it.`:r.row_count?'Invoice identifiers were supplied. Workbench has not independently authenticated this report.':'This snapshot contains no Bedrock charge rows. It does not establish a zero provider invoice.'}</p>
        <p class="fine">Scope: ${esc(r.period_start)} inclusive to ${esc(r.period_end)} exclusive. ${r.row_count} accepted rows; ${r.provenance.outside_bedrock_rows} other-service rows excluded; ${r.provenance.duplicate_rows} identical within-snapshot rows deduplicated.</p>
        ${r.evidence==='fixture'?'<p class="data-note">All billing amounts, tokens and timings in this example are synthetic. It makes zero provider calls and is excluded from real usage totals.</p>':''}
      </article>
      <div class="metrics billing-metrics">
        ${card('Imported Bedrock charges',money(r.imported_charges,r.currency),'Calculated with AxonLLM Ledger · net unblended where supplied; otherwise unblended.')}
        ${card('Charges linked to captured scope',money(r.linked_charges,r.currency),'Declared group matches with captured calls; no per-task invoice allocation.')}
        ${card('Unassigned net charges',money(r.unassigned_charges,r.currency),`${r.unassigned_groups} groups need attribution · positive ${money(r.unassigned_positive_charges,r.currency)} · adjustments ${money(r.unassigned_adjustments,r.currency)}`)}
        ${card('Usage comparisons',String(r.comparisons.length),`${incomplete} incomplete · differences need review before drawing conclusions.`)}
      </div>
      <article class="panel screen-guide"><h2>Compare like-for-like scopes.</h2><p>A billing group can cover many calls. Select the input and output groups together, then declare which sources and exact model/region/mode they cover. A source must belong to one AWS usage account. Model display names and profile ARNs are not automatically translated.</p><p class="fine">A difference can reflect report timing, discounts, missing capture or an incorrect scope. Fees and credits stay visible as adjustments. It does not establish realized savings.</p></article>
      <div id="billing-comparisons">${r.comparisons.map(c=>`<article class="panel billing-comparison">
        <div class="section-head"><h2>${esc(c.name)}</h2>${tag(c.status==='incomplete'?'Comparison incomplete':c.difference_usd==='0'?'Same reported total':'Difference to review',c.status==='incomplete'?'warn':'accent')}</div>
        <p class="fine">${esc(c.model)} · ${esc(c.region)} · ${esc(c.service_tier)} tier · ${esc(c.performance)} performance<br>${esc(c.source_ids.map(sourceName).join(', '))}</p>
        <dl class="result-guide billing-comparison-values"><div><dt>Selected billing charges</dt><dd>${money(c.billing_charge_amount)}</dd></div><div><dt>Captured-call estimate</dt><dd>${money(c.comparable_estimate_usd)}</dd></div><div><dt>Charges minus estimate</dt><dd>${money(c.difference_usd)}</dd></div></dl>
        <p>${c.calls} captured calls across ${c.tasks} task runs. ${c.unknown_cost_calls} calls without a supported estimate; ${c.incomplete_calls} with incomplete attempt/cost capture.</p>
        ${c.limitations.length?`<p class="data-note">${c.limitations.map(esc).join(' ')} Known estimate subtotal: ${money(c.known_estimate_usd)}.</p>`:''}
        ${c.carried_from_revision?`<p class="fine">This exact group mapping was carried forward from revision ${c.carried_from_revision}. Review it against the refreshed charges.</p>`:''}
        <div class="row-actions">${c.source_ids.map(id=>`<button class="button" data-billing-tasks="${esc(id)}">Inspect ${esc(sourceName(id))} tasks</button>`).join('')}${writable?`<button class="button" data-billing-remove="${esc(c.id)}">Unlink these groups</button>`:''}</div><p class="fine">Task navigation shows this source and billing month across all its models. Per-call invoice amounts remain unknown.</p>
      </article>`).join('') || '<p class="notice">No comparison is configured yet. An administrator can link eligible usage groups below.</p>'}</div>
      <article class="panel"><h2>Every imported charge stays visible.</h2><p class="fine">Unassigned charges remain in the total. Positive charges and negative adjustments are shown separately, even when their net is zero.</p>${r.groups.length?groupTable(r.groups):'<p class="notice">This is an empty Bedrock snapshot.</p>'}</article>
      ${writable&&r.currency==='USD'?`<details class="panel help-details" id="billing-mapping-details"><summary>Link billing groups to a captured model scope</summary>
        <form id="billing-mapping-form">
          <p>Select all comparable groups for the scope, including input and output where applicable. Each captured-call scope can be used once per snapshot.</p>
          ${groupTable(r.groups,true)}
          <div class="billing-form-grid">
            <label class="field">Comparison name<input name="name" required maxlength="100" placeholder="Support application · Nova Micro"></label>
            <label class="field">Captured Bedrock sources<select name="source_ids" multiple required size="${Math.min(5,Math.max(2,r.sources.length))}">${r.sources.map(s=>`<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('')}</select><small>Select every source covered by these groups. A source cannot span AWS accounts.</small></label>
            <label class="field">Exact captured model ID<input name="model" required maxlength="2048" placeholder="amazon.nova-micro-v1:0"><small>Copy the model ID from the captured-call details, including any profile prefix.</small></label>
            <label class="field">Region code<input name="region" required pattern="[a-z0-9-]+" maxlength="40" placeholder="us-east-1"></label>
            <label class="field">Captured service tier<select name="service_tier"><option value="default">Default</option><option value="priority">Priority</option><option value="flex">Flex</option><option value="reserved">Reserved</option></select></label>
            <label class="field">Captured performance mode<select name="performance"><option value="standard">Standard</option><option value="optimized">Optimized</option></select></label>
          </div>
          <label class="check billing-confirm"><input type="checkbox" name="account_binding_confirmed" required><span>I confirm these billing groups cover the selected sources and exact model/mode, and those sources use AWS account …${esc(r.account_id.slice(-4))}.</span></label>
          <button class="button primary" ${r.sources.length?'':'disabled'}>Save declared scope</button>
          ${r.sources.length?'':'<p class="fine">Create a Bedrock application source in Usage sources first.</p>'}
        </form>
      </details>`:''}
      <details class="panel help-details"><summary>Provenance, cost basis and interpretation</summary><p>${esc(r.scope_note)}</p><p>Report fingerprint: <code>${esc(r.fingerprint)}</code></p><p>Submitted CSV SHA-256: ${r.provenance.submitted_sha256.map(v=>`<code>${esc(v)}</code>`).join(' · ')}</p><p>These hashes identify submitted content; they are not a publisher signature. Billing charges use net unblended values where present and unblended values otherwise. No currency conversion or list-price fallback is applied. Operational usage is recalculated when you refresh or export; retention and late delivery can affect the comparison.</p></details>`;
    const form=$('billing-mapping-form');
    if(form) form.onsubmit=event=>{
      event.preventDefault();
      const button=event.submitter, epoch=getEpoch(), identity=report.id, data=new FormData(form);
      const body={name:data.get('name'),group_ids:data.getAll('group_ids'),source_ids:data.getAll('source_ids'),model:data.get('model'),region:data.get('region'),service_tier:data.get('service_tier'),performance:data.get('performance'),account_binding_confirmed:data.has('account_binding_confirmed')};
      if(!body.group_ids.length) return notice('Select at least one eligible billing group.',true);
      button.disabled=true;
      action(async()=>{
        try {await api(`/api/pilot/billing/reports/${identity}/mappings`,body);if(stable(epoch)){await show(identity);notice('Declared billing scope saved. Review its estimate and any remaining gaps.');}}
        finally {if(stable(epoch)&&button.isConnected)button.disabled=false;}
      });
    };
  }
  $('billing-import-form').addEventListener('input',invalidatePreview);
  $('billing-import-form').addEventListener('change',invalidatePreview);
  $('billing-import-form').onsubmit=event=>{
    event.preventDefault();
    const epoch=getEpoch(), token=++importGeneration, button=event.submitter, form=new FormData(event.target);
    const files=Array.from($('billing-files').files);
    const body={format:form.get('format'),account_id:form.get('account_id'),month:form.get('month'),currency:form.get('currency'),name:form.get('name'),complete_snapshot:form.has('complete_snapshot'),expected_revision:0};
    button.disabled=true;
    action(async()=>{
      try {
        if(!files.length||files.length>20||files.reduce((sum,f)=>sum+f.size,0)>8_000_000)throw new Error('Choose up to 20 CSV files totaling at most 8 MB.');
        body.files=await Promise.all(files.map(f=>f.text()));
        if(!stable(epoch)||token!==importGeneration)return;
        const value=await api('/api/pilot/billing/preview',body);
        if(!stable(epoch)||token!==importGeneration)return;
        pending={...body,expected_revision:value.expected_revision};
        $('billing-preview').innerHTML=`<article class="screen-guide"><h2>Review this import before saving.</h2><p><strong>${money(value.imported_charges,value.currency)}</strong> across ${value.row_count} Bedrock rows for account …${esc(value.account_id.slice(-4))}, ${esc(value.month)}.</p><p>${value.outside_bedrock_rows} other-service rows excluded. ${value.duplicate_rows} identical rows deduplicated. ${value.uninvoiced_rows} rows have no invoice identifier.</p><p>${value.expected_revision?`Current revision ${value.expected_revision} will be superseded if the accepted contents changed.`:'This creates the first snapshot for this account/month/currency.'}</p><p class="fine">${esc(value.notice)}</p><button class="button primary" id="billing-commit">Import snapshot</button></article>`;
        $('billing-preview').hidden=false;
        $('billing-commit').onclick=()=>{
          const document=pending, revision=importGeneration, before=getEpoch();if(!document)return;
          $('billing-commit').disabled=true;
          action(async()=>{
            try {
              const imported=await api('/api/pilot/billing/imports',document);
              if(!stable(before)||revision!==importGeneration)return;
              invalidatePreview();$('billing-files').value='';listingPage=0;
              await load(imported.id);
              notice(imported.unchanged?'Identical snapshot already exists. Charges were not counted again.':'Billing snapshot saved. Link the comparable groups and inspect unattributed charges.');
            } finally {if(stable(before)&&$('billing-commit'))$('billing-commit').disabled=false;}
          });
        };
        $('billing-preview').scrollIntoView({block:'nearest'});
      } finally {if(stable(epoch))button.disabled=false;}
    });
  };
  $('billing-example').onclick=()=>{
    const epoch=getEpoch();$('billing-example').disabled=true;
    action(async()=>{
      try {
        const result=await api('/api/pilot/billing/example',{});
        if(!stable(epoch))return;
        await onExample();if(!stable(epoch))return;listingPage=0;await load(result.id);
        notice('Loaded fictional billing records and two synthetic calls. No provider calls or charges were made.');
      } finally {if(stable(epoch))$('billing-example').disabled=false;}
    });
  };
  $('billing-report-select').onchange=()=>{if($('billing-report-select').value)action(()=>show($('billing-report-select').value));};
  $('billing-refresh').onclick=()=>action(()=>load(report?.id));
  $('billing-previous').onclick=()=>action(async()=>{listingPage=Math.max(0,listingPage-1);report=null;await load();});
  $('billing-next').onclick=()=>action(async()=>{listingPage++;report=null;await load();});
  $('billing-report').addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button||!report)return;
    const epoch=getEpoch(), identity=report.id;
    if(button.dataset.billingExport!==undefined)action(async()=>{
      const value=await api(`/api/pilot/billing/reports/${identity}/export`);
      if(!stable(epoch))return;
      const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
      const a=document.createElement('a');a.href=url;a.download='workbench-billing-reconciliation.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    });
    if(button.dataset.billingRemove)action(async()=>{
      await api(`/api/pilot/billing/reports/${identity}/mappings/${button.dataset.billingRemove}/remove`,{});
      if(stable(epoch)){await show(identity);notice('Groups unlinked. Their charges remain in the report.');}
    });
    if(button.dataset.billingTasks)action(()=>onTasks({source_id:button.dataset.billingTasks,start:report.period_start,end:report.period_end,include_fixtures:report.evidence==='fixture'}));
  });
  return {load,reset};
}
