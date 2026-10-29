function createEvaluationInspector({api, getEpoch, download}) {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = value => value == null ? 'Unknown' : `$${value}`;
  const json = value => esc(JSON.stringify(value, null, 2));
  const label = value => String(value).replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
  const display = value => value == null ? 'Not returned' : typeof value==='boolean' ? (value?'Yes':'No') :
    typeof value==='object' ? esc(JSON.stringify(value)) : esc(label(value));
  function decisions(task) {
    const expected=task.expected, actual=task.assessment.decision || {};
    const rows=[
      ['Resolution',expected.resolution,actual.resolution],
      ['Category',expected.category,actual.category],
      ['Refund amount (minor currency units)',expected.refund_minor,actual.refund_minor],
      ['Policy citation',expected.policy,Array.isArray(actual.citations)?actual.citations.join(', '):actual.citations],
      ['Claims action already executed',false,actual.executed],
    ];
    return `<div class="table-wrap"><table><thead><tr><th>Decision detail</th><th>Expected decision</th><th>Actual decision</th></tr></thead>
      <tbody>${rows.map(([name,wanted,received])=>`<tr><th>${esc(name)}</th><td>${display(wanted)}</td><td>${display(received)}</td></tr>`).join('')}</tbody></table></div>
      ${actual.reply?`<h3>Saved customer reply</h3><p>${esc(actual.reply)}</p>`:''}`;
  }
  let sequence=0, job=null, model='', filter='failed', page=0;
  const critical = task => task.critical && !task.assessment.critical_passed;
  function reset() { sequence++; job=null; $('evaluation-result').replaceChildren(); }
  function cases() {
    const rows=job.analysis.tasks.filter(t=>(!model || t.model===model) &&
      (filter==='all' || (filter==='critical' ? critical(t) : !t.assessment.passed)));
    page=Math.min(page,Math.max(0,Math.ceil(rows.length/12)-1));
    $('evaluation-cases').innerHTML=rows.slice(page*12,(page+1)*12).map(t=>`
      <details class="panel evaluation-case" data-flow="compare">
        <summary><strong>${esc(t.title)}</strong> · ${esc(t.model)} · ${critical(t)?'Critical failure':t.assessment.passed?'Passed':'Failed'}</summary>
        <p class="data-note">Case ${esc(t.case_id)} · ${esc(t.family)} · ${esc(money(t.estimated_cost_usd))} captured API estimate</p>
        <h3>Checks</h3><ul>${[...t.assessment.checks].sort((a,b)=>Number(a.passed)-Number(b.passed)).map(c=>`<li>${c.passed?'Passed':'FAILED'} — ${esc(c.name)}</li>`).join('')}</ul>
        ${decisions(t)}
        <h3>Customer request</h3><p>${esc(t.ticket)}</p>
        <h3>Supplied facts</h3><dl class="result-guide">${Object.entries(t.facts).map(([key,value])=>`<div><dt>${esc(label(key))}</dt><dd>${display(value)}</dd></div>`).join('')}</dl>
        <p>Action-boundary decision: ${esc(t.governance.tier)}</p>
        <details><summary>Structured decision evidence</summary><pre>${json({expected:t.expected,actual:t.assessment.decision})}</pre></details>
        ${t.stages.map(s=>`<details><summary>Saved ${esc(s.name)} request and answer · ${esc(s.status)}</summary><h4>Request</h4><pre>${json(s.messages)}</pre><h4>Model answer</h4><pre>${esc(s.output)}</pre></details>`).join('')}
      </details>`).join('') || '<p class="notice">No cases match these filters.</p>';
    $('evaluation-case-count').textContent=`${rows.length} matching cases · Page ${page+1} of ${Math.max(1,Math.ceil(rows.length/12))}`;
    $('evaluation-previous').disabled=page===0;
    $('evaluation-next').disabled=(page+1)*12>=rows.length;
  }
  async function show(id) {
    const epoch=getEpoch(), token=++sequence;
    const value=await api(`/api/pilot/evaluations/${id}`);
    if(epoch!==getEpoch() || token!==sequence)return;
    if(!value.analysis)throw new Error('This evaluation has no saved result yet.');
    job=value; model=''; filter='failed'; page=0;
    const result=job.analysis;
    $('evaluation-result').innerHTML=`<article class="panel">
      <div class="section-head"><div><h2>How the models performed</h2><p>${result.total_calls} saved calls · ${esc(money(result.total_cost_usd))} estimated API cost · ${result.mode==='fixture'?'Synthetic test data':'Recorded model answers'}</p></div><button class="button soft" id="export-result">Export results</button></div>
      <div class="table-wrap"><table><thead><tr><th>Model</th><th>Tickets passed</th><th>Critical failures</th><th>Response time, p95</th><th>Cost per passing ticket</th></tr></thead>
      <tbody>${result.models.map((m,i)=>`<tr><td>${esc(m.model)}</td><td>${m.passed}/${m.evaluated}</td><td><button class="button small" data-critical-model="${i}" aria-label="Inspect ${m.critical_failures} critical failure${m.critical_failures===1?'':'s'} for ${esc(m.model)}">${m.critical_failures} critical failure${m.critical_failures===1?'':'s'}</button></td><td>${m.p95_ms===null?'Unknown':`${esc(m.p95_ms)} ms`}</td><td>${esc(money(m.cost_per_pass_usd))}</td></tr>`).join('')}</tbody></table></div>
      <dl class="result-guide"><div><dt>Tickets passed</dt><dd>All decision and action-boundary checks must pass.</dd></div><div><dt>Critical failures</dt><dd>Failures on critical decision cases exclude a model. Select the count to inspect those cases below.</dd></div><div><dt>Response time, p95</dt><dd>95% of recorded task runs finished within this time.</dd></div><div><dt>Cost per passing ticket</dt><dd>Includes money spent on failed tickets.</dd></div></dl>
      <p class="data-note">${result.mode==='fixture'?'Fixture answers cannot justify a measured recommendation or savings.':'These checks replay saved answers; they do not measure current model speed or quality on other tasks.'}</p>
      <details><summary>Saved evidence identity</summary><p class="fine">Recording: ${esc(result.recording_id)}<br>Evaluator: ${esc(result.evaluation_revision.sha256)}</p><pre>${json(result.evaluation_revision)}</pre></details>
      <button class="button primary" data-goto="proposals">Review routing criteria</button></article>
      <article class="panel"><h2>Inspect individual cases</h2><p>Start with failures. Open a case to compare the expected decision with the saved answer and every check.</p>
      <div class="row-actions"><label class="field">Model<select id="evaluation-model"><option value="">All models</option>${result.models.map(m=>`<option>${esc(m.model)}</option>`).join('')}</select></label>
      <label class="field">Case outcome<select id="evaluation-outcome"><option value="failed">Failed cases</option><option value="critical">Critical failures</option><option value="all">All cases</option></select></label></div>
      <p id="evaluation-case-count" class="fine" aria-live="polite"></p></article>
      <div id="evaluation-cases"></div><div class="pagination"><button class="button" id="evaluation-previous">Previous cases</button><button class="button" id="evaluation-next">Next cases</button></div>`;
    $('export-result').onclick=()=>download(`evaluation-${id}.json`,job);
    $('evaluation-model').onchange=e=>{model=e.target.value;page=0;cases();};
    $('evaluation-outcome').onchange=e=>{filter=e.target.value;page=0;cases();};
    $('evaluation-previous').onclick=()=>{page--;cases();};
    $('evaluation-next').onclick=()=>{page++;cases();};
    $('evaluation-result').querySelectorAll('[data-critical-model]').forEach(button=>{
      button.onclick=()=>{
        model=result.models[Number(button.dataset.criticalModel)].model;filter='critical';page=0;
        $('evaluation-model').value=model;$('evaluation-outcome').value=filter;cases();
        const first=$('evaluation-cases').querySelector('details');
        if(first)first.open=true;
        $('evaluation-case-count').scrollIntoView({block:'start'});
      };
    });
    cases();$('evaluation-result').scrollIntoView({block:'start'});
  }
  return {reset,show};
}
