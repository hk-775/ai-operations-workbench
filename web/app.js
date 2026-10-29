'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dollars = (value, places = 5) => value === null || value === undefined ? 'Unmeasured' : '$' + Number(value).toLocaleString('en-US', {minimumFractionDigits: places, maximumFractionDigits: places});
const ms = value => value === null || value === undefined ? '—' : (Number(value) / 1000).toFixed(2) + 's';
const label = model => ({'gpt-4.1-2025-04-14':'GPT-4.1','gpt-4.1-mini-2025-04-14':'GPT-4.1 mini','gpt-4o-mini-2024-07-18':'GPT-4o mini'}[model] || model);
const pct = value => (Number(value) * 100).toFixed(1) + '%';
let state = {connected:false}, analysis = null, proposal = null, view = 'overview', selected = null, busy = false;
let constraints = {min_pass_rate:.95, max_p95_ms:20000, monthly_tasks:10000};

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Please check the supplied values.');
  return result;
}
function notice(message = '', error = false) {
  $('#notice').innerHTML = message ? `<div class="notice ${error?'error':''}">${esc(message)}</div>` : '';
}
function nav(next) {
  view = next;
  document.querySelectorAll('[data-view]').forEach(button => button.classList.toggle('active', button.dataset.view === view));
  $('#current-view').textContent = ({overview:'Overview',tasks:'Task explorer',compare:'Model comparison',proposal:'Routing proposal'})[view];
  $('#current-view').dataset.flow = view === 'overview' ? 'connect' : view;
  render();
  $('.content').scrollTo({top:0,behavior:'instant'});
  window.scrollTo({top:0,behavior:'instant'});
}
async function refresh() {
  state = await api('/api/state');
  $('#connect').disabled = !state.source.available;
  if (state.evaluated) analysis = await api('/api/analysis');
  else { analysis = null; proposal = null; }
  selected = selected && state.tasks?.find(t => t.id === selected.id) || state.tasks?.[0] || null;
  document.querySelectorAll('.journey-step').forEach((button,index) => button.classList.toggle('done', index < (analysis ? 4 : state.connected ? 2 : 0)));
  render();
}
function icon(name) {
  return `<svg class="ui-icon" aria-hidden="true"><use href="#icon-${esc(name)}"/></svg>`;
}
function metric(title, value, subtitle, highlight = false, flow = 'connect', glyph = flow === 'connect' ? 'usage' : flow) {
  return `<div class="metric ${highlight?'highlight':''}" data-flow="${esc(flow)}"><div class="metric-head"><div class="metric-label">${esc(title)}</div><span class="metric-icon">${icon(glyph)}</span></div><div class="metric-value ${value==='Unmeasured'?'metric-word':''}">${esc(value)}</div><div class="metric-sub">${esc(subtitle)}</div></div>`;
}
function empty() {
  return `<section class="empty" data-flow="connect"><div><p class="eyebrow">ONE WORKFLOW. A CLEAR DECISION.</p><h2>Your next optimization<br>starts with one task.</h2><p>Connect a recorded support run to see what each model call cost, inspect the most expensive task, and compare alternatives against the same checks.</p><button class="button primary" data-action="sources" data-flow="connect">Connect recorded usage <span>→</span></button></div><div class="preview-stack"><div class="preview-row" data-flow="connect"><span>01 / Usage and cost</span><strong>Follow the spend</strong></div><div class="preview-row" data-flow="compare"><span>02 / Model evidence</span><strong>Test the alternatives</strong></div><div class="preview-row" data-flow="proposal"><span>03 / Routing proposal</span><strong>Explain the decision</strong></div><p class="fine">24 synthetic cases · 3 models · 2 model calls per task<br>Replay is local. No API key needed to explore.</p></div></section>`;
}
function taskTable(tasks) {
  return `<div class="table-wrap"><table><thead><tr><th>Task</th><th>Model</th><th class="num">API estimate</th><th class="num">Task time</th><th></th></tr></thead><tbody>${tasks.map(t => `<tr class="clickable" data-task="${esc(t.id)}" tabindex="0" role="button" aria-label="Inspect ${esc(t.title)}"><td class="task-name">${esc(t.title)}<small>${esc(t.id)} · ${esc(t.family.replaceAll('-',' '))}</small></td><td><span class="tag">${esc(label(t.model))}</span></td><td class="num">${dollars(t.cost_usd)}</td><td class="num muted">${ms(t.latency_ms)}</td><td class="muted">↗</td></tr>`).join('')}</tbody></table></div>`;
}
function overview() {
  const baseline = state.tasks || [];
  const top = baseline[0];
  const known = baseline.reduce((sum,t) => sum + Number(t.cost_usd),0);
  return `<div class="metrics">
    ${metric(state.incomplete_tasks?'Known API subtotal':'Recorded API estimate', dollars(state.api_cost_usd,4), `${state.calls} model-stage records · all candidates`,true,'connect','cost')}
    ${metric('Baseline tasks', String(baseline.length), 'Same two-stage workflow per case', false, 'tasks')}
    ${metric('Models recorded', String(state.models_recorded), 'Candidates in this connected run', false, 'compare')}
    ${metric('Hardware / electricity', 'Unmeasured', 'Kept separate from API charges', false, 'proposal', 'hardware')}
  </div>
  <div class="grid-two"><section class="panel flush" data-flow="tasks"><div class="section-head"><div><h2>Start with the expensive tasks</h2><p>Baseline ${esc(label(state.baseline))} · ranked by recorded API estimate</p></div><button class="button subtle small" data-action="tasks" data-flow="tasks">View all →</button></div>${taskTable(baseline.slice(0,5))}<div class="section-foot">Cost includes both triage and draft calls. Provider invoices are not connected.</div></section>
  <div><section class="panel spotlight investigation" data-flow="tasks"><div class="spotlight-heading"><p class="eyebrow">YOUR FIRST INVESTIGATION</p><span class="spotlight-icon">${icon('tasks')}</span></div><h2>${esc(top?.title || 'Inspect a baseline task')}</h2><div class="insight-number">${dollars(top?.cost_usd,5)}</div><div class="mini-label">RECORDED MODEL API ESTIMATE</div><p style="font-size:12px;margin-top:18px">Open the task to see the input, both model calls, and where its cost comes from.</p><button class="button" data-flow="tasks" data-task="${esc(top?.id)}">Inspect this task <span>↗</span></button></section><div class="data-note">Synthetic support tickets. ${state.mode==='fixture'?'Fixture responses—no live model evidence.':'Recorded model responses and provider-reported token usage.'} ${analysis?'Checks replayed locally.':'Evaluation checks have not been replayed yet.'}</div></div></div>
  <section class="panel" data-flow="connect"><div class="section-head"><div><h2>One source. Three kinds of evidence.</h2><p>Keep financial estimates, runtime behavior, and task correctness distinct.</p></div><button class="button subtle small" data-action="about" data-flow="connect">View components</button></div><div class="grid-two"><p class="fine">AxonLLM supplied the model calls. Ostiari checks the draft-only action boundary. Workbench joins their evidence into a reviewable comparison.</p><p class="fine">Baseline API estimate: ${dollars(known,4)} across ${baseline.length} tasks. Hardware, subscriptions, human review, and invoices are not included.</p></div></section>`;
}
function tasksView() {
  const task = selected || state.tasks[0];
  if (!task) return empty();
  const total = Number(task.cost_usd) || 1;
  const stageNames = {triage:'Classify the support request',draft:'Prepare the grounded draft'};
  return `<div class="section-head"><div><h2>Inside an expensive task</h2><p>${esc(task.id)} · ${esc(task.title)} · ${esc(label(task.model))}</p></div><button class="button primary" data-action="evaluate" data-flow="compare" ${busy?'disabled':''}>${busy?'Replaying checks…':'Evaluate alternatives'} <span>→</span></button></div>
  <div class="metrics">${metric('Task API estimate',dollars(task.cost_usd),'Sum of the two model calls',true,'tasks','cost')}${metric('Recorded task time',ms(task.latency_ms),'Sequential workflow wall time',false,'compare','clock')}${metric('Model calls',String(task.stages.length),'Triage → draft',false,'connect')}${metric('External tool API fees','$0.00','Local checks; no paid tool invoked',false,'proposal','cost')}</div>
  <div class="grid-two"><section class="panel" data-flow="tasks"><p class="eyebrow">EXECUTION BREAKDOWN</p><div class="phase"><span class="phase-number">1</span><div><h3>Load ticket and support policy</h3><p>Local synthetic facts. No retrieval API.</p></div><div class="cost">$0.00<small>external API fees</small></div></div>
  ${task.stages.map((s,i) => `<div class="phase"><span class="phase-number">${i+2}</span><div><h3>${stageNames[s.name]}</h3><p>${esc(label(task.model))} · ${s.usage?Number(s.usage.prompt_tokens).toLocaleString()+' input + '+Number(s.usage.completion_tokens).toLocaleString()+' output tokens':'Usage unavailable'}</p><details><summary>Inspect recorded request and response</summary><pre>${esc(JSON.stringify({messages:s.messages,response:s.output,usage:s.usage,status:s.status},null,2))}</pre></details></div><div class="cost">${dollars(s.estimated_cost_usd)}<small>${ms(s.latency_ms)}</small></div></div>`).join('')}
  <div class="phase"><span class="phase-number">4</span><div><h3>Check the decision and action boundary</h3><p>Deterministic contract checks + Ostiari Guard. No subscription or payment changes.</p></div><div class="cost">$0.00<small>external API fees</small></div></div></section>
  <div><section class="panel" data-flow="connect"><p class="eyebrow">THE CUSTOMER REQUEST</p><h2>${esc(task.title)}</h2><p style="font-size:13px;margin:18px 0;color:var(--text)">${esc(task.ticket)}</p><details><summary>Supplied facts</summary><pre>${esc(JSON.stringify(task.facts,null,2))}</pre></details><div class="bar-row"><div class="bar-caption"><span>Model API cost split</span><span>${dollars(task.cost_usd)}</span></div><div class="cost-bar">${task.stages.map(s=>`<span style="width:${Math.max(0,Number(s.estimated_cost_usd||0)/total*100)}%"></span>`).join('')}</div><div class="legend"><span><i></i>Triage</span><span><i></i>Draft</span></div></div></section><section class="panel spotlight" data-flow="compare"><p class="eyebrow">THE NEXT QUESTION</p><h2>Could a cheaper model pass the same checks?</h2><p style="font-size:12px;margin-top:12px">Replay the complete comparison before recommending a change. Failed cases stay in the denominator.</p><button class="button" data-action="evaluate" data-flow="compare" ${busy?'disabled':''}>${busy?'Replaying…':'Run evaluation replay'} →</button></section></div></div>
  <section class="panel flush" data-flow="tasks"><div class="section-head"><div><h2>Other baseline tasks</h2><p>Choose another task to inspect its complete recorded input and output.</p></div></div>${taskTable(state.tasks)}</section>`;
}
function comparisonPlot() {
  const models = analysis.models.filter(m=>m.mean_cost_usd!==null);
  if (!models.length) return '<p class="data-note">No complete cost measurements are available to plot.</p>';
  const max = Math.max(...models.map(m=>Number(m.mean_cost_usd))) * 1.25 || 1;
  const color = ['var(--chart-baseline)','var(--accent)','var(--chart-secondary)'];
  return `<svg class="plot" viewBox="0 0 620 260" role="img" aria-label="Model API cost per task versus contract pass rate">
    ${[0,25,50,75,100].map(p=>`<line x1="58" x2="580" y1="${215-p*1.7}" y2="${215-p*1.7}" stroke="var(--line)"/><text x="15" y="${219-p*1.7}">${p}%</text>`).join('')}
    <text x="59" y="17">Contract pass rate ↑</text><text x="290" y="253">API estimate per task →</text>
    ${[0,1/3,2/3,1].map(f=>`<text x="${65+f*490}" y="235" text-anchor="middle">${dollars(max*f,4)}</text>`).join('')}
    ${models.map((m,i)=>{const x=65+Number(m.mean_cost_usd)/max*490,y=215-m.pass_rate*170;return `<circle cx="${x}" cy="${y}" r="7" fill="${color[i]}" stroke="var(--accent-strong)" stroke-width="1"><title>${esc(label(m.model))}: ${pct(m.pass_rate)} pass, ${dollars(m.mean_cost_usd)} API per task</title></circle><text class="label" x="${Math.min(x+12,490)}" y="${y+(i===2?27:-12)}">${esc(label(m.model))}</text>`}).join('')}
  </svg>`;
}
function compareView() {
  if (!analysis) return `<section class="empty" data-flow="compare"><div><p class="eyebrow">EVALUATE THE SAME WORKLOAD</p><h2>Cost is only half<br>of the decision.</h2><p>Replay deterministic checks across every recorded response. Compare case pass rates, critical failures, cost, and task latency with the original failures retained.</p><button class="button primary" data-action="evaluate" data-flow="compare" ${busy?'disabled':''}>${busy?'<span class="busy-dot"></span> Replaying evidence…':'Run evaluation replay →'}</button><p class="fine" style="margin-top:15px">Local replay uses saved responses. It makes no model calls.</p></div><div class="preview-stack"><div class="preview-row" data-flow="compare"><span>Decision contract</span><strong>Is the decision right?</strong></div><div class="preview-row" data-flow="proposal"><span>Critical cases</span><strong>Are boundaries respected?</strong></div><div class="preview-row" data-flow="tasks"><span>Operational evidence</span><strong>What did it cost?</strong></div></div></section>`;
  return `<div class="section-head"><div><h2>Same workload. Visible tradeoffs.</h2><p>24 authored cases per model · two sequential calls per task · one recorded run</p></div><button class="button primary" data-action="proposal" data-flow="proposal">Review routing proposal →</button></div>
  <section class="panel flush" data-flow="compare"><div class="table-wrap"><table><thead><tr><th>Model</th><th class="num">Cases passed</th><th class="num">Critical failures</th><th class="num">API / task</th><th class="num">Cost / passing task</th><th class="num">Task p95</th><th></th></tr></thead><tbody>${analysis.models.map(m=>`<tr><td class="task-name">${esc(label(m.model))}<small>${m.model===state.baseline?'Current baseline':'Alternative'} · ${m.evaluated}/${m.planned} recorded</small></td><td class="num">${m.passed}/${m.evaluated}<small style="display:block;color:var(--muted)">${pct(m.pass_rate)}</small></td><td class="num"><span class="tag ${m.critical_failures?'danger':'good'}">${m.critical_failures}</span></td><td class="num">${dollars(m.mean_cost_usd)}</td><td class="num">${dollars(m.cost_per_pass_usd)}</td><td class="num">${ms(m.p95_ms)}</td><td><button class="button subtle small" data-model-cases="${esc(m.model)}">Inspect cases</button></td></tr>`).join('')}</tbody></table></div><div class="section-foot">Cost per passing task = API estimate for all evaluated tasks ÷ passing tasks. Incomplete evidence is ineligible.</div></section>
  <div class="grid-two"><section class="panel" data-flow="compare"><h2>Cost and contract quality</h2><p class="fine">Lower cost and higher pass rate identify candidates for further testing.</p>${comparisonPlot()}</section><section class="panel" data-flow="proposal"><p class="eyebrow">GUARDRAILS, CHECKED</p><h2>Drafts stay drafts.</h2><div style="margin-top:15px">${analysis.controls.map(c=>`<div class="bar-caption" style="padding:9px 0;border-bottom:1px solid var(--line)"><span>${esc(c.action)}</span><span class="tag ${c.tier==='allow'?'good':c.tier==='block'?'danger':'warn'}">${esc(c.tier)}</span></div>`).join('')}</div><p class="fine" style="margin-top:19px">These decisions come from the actual Ostiari Guard in the evaluation worker. No external action is executed.</p></section></div>
  <div class="data-note">This is a small synthetic comparison, not a production-quality guarantee. Checks evaluate the structured decision and selected execution claims; they do not fully grade reply prose.</div>`;
}
function constraintForm() {
  return `<section class="panel" data-flow="proposal"><div class="section-head"><div><h2>Your acceptance criteria</h2><p>Critical failures and incomplete evidence always exclude a model.</p></div><span class="tag accent">REVIEW ONLY</span></div><form id="constraints" class="controls"><div class="field"><label for="min-pass">Minimum case pass rate (%)</label><input id="min-pass" name="min-pass" type="number" min="0" max="100" step="1" value="${constraints.min_pass_rate*100}"></div><div class="field"><label for="max-latency">Maximum task p95 (seconds)</label><input id="max-latency" name="max-latency" type="number" min=".001" max="3600" step=".001" value="${constraints.max_p95_ms/1000}"></div><div class="field"><label for="monthly-tasks">Projected tasks / month</label><input id="monthly-tasks" name="monthly-tasks" type="number" min="1" max="10000000" step="1" value="${constraints.monthly_tasks}"></div><button class="button primary" type="submit">Update proposal →</button></form></section>`;
}
function proposalView() {
  if (!analysis) return compareView();
  if (!proposal) { getProposal(); return '<section class="panel" data-flow="proposal"><span class="busy-dot"></span> Checking model eligibility…</section>'; }
  const winner = proposal.candidates.find(m=>m.model===proposal.recommended_model);
  return `${constraintForm()}<section class="recommendation" data-flow="proposal"><div><span class="tag ${winner?'accent':'warn'}">${proposal.status==='fixture_only'?'FIXTURE EVIDENCE ONLY':winner?'CANDIDATE FOR FURTHER TESTING':'NO MODEL MEETS THESE CRITERIA'}</span><h2>${proposal.status==='fixture_only'?'Collect recorded model evidence.':winner?'Consider '+esc(label(winner.model)):'Keep the current route under review.'}</h2><p>${proposal.status==='fixture_only'?'Synthetic answers, usage and timings cannot justify a measured recommendation or savings.':winner?`${winner.passed}/${winner.planned} cases passed, zero critical decision failures, and ${ms(winner.p95_ms)} task p95 in this recording. This is a proposal for a held-out evaluation, not approval to deploy.`:'No model qualifies under these criteria, including the baseline. Review the failed cases and collect stronger evidence before changing a route.'}</p></div>${winner?`<div><div class="amount">${dollars(proposal.projected_monthly_api_savings_usd,2)}</div><div class="amount-label">projected API savings / month<br>at ${Number(proposal.monthly_tasks).toLocaleString()} identical-mix tasks</div></div>`:''}</section>
  <div class="grid-two"><section class="panel" data-flow="compare"><div class="section-head"><div><p class="eyebrow">THE REASONING IS VISIBLE</p><h2>Candidate eligibility</h2></div></div>${proposal.candidates.map(m=>`<div style="padding:13px 0;border-bottom:1px solid var(--line)"><div class="bar-caption"><strong>${esc(label(m.model))}</strong><span class="tag ${m.eligible?'good':'warn'}">${m.eligible?'Eligible':'Excluded'}</span></div><p class="fine">${m.eligible?`${pct(m.pass_rate)} case pass rate · ${ms(m.p95_ms)} p95 · ${dollars(m.cost_per_pass_usd)} per passing task`:m.exclusions.map(esc).join(' · ')}</p></div>`).join('')}<button class="button primary" data-action="export" data-flow="proposal" style="margin-top:21px">Export evidence and proposal ↓</button></section>
  <section class="panel" data-flow="connect"><p class="eyebrow">BEFORE CHANGING A ROUTE</p><h2>What this evidence can support</h2><ul class="limitations">${proposal.limitations.map(l=>`<li>${esc(l)}</li>`).join('')}</ul><div class="data-note">Routing status: <strong>Not applied.</strong><br>${esc(proposal.next_step)}</div></section></div>`;
}
function render() {
  const currentStep = view === 'overview' ? 'connect' : view;
  document.querySelectorAll('.journey-step').forEach(button => {
    if (button.dataset.step === currentStep) button.setAttribute('aria-current','step');
    else button.removeAttribute('aria-current');
  });
  const fixture = state.mode==='fixture' ? '<div class="notice warn">Fixture evidence: responses, token usage, latency, and costs are synthetic. This run cannot substantiate model performance or savings.</div>' : '';
  const incomplete = state.incomplete_tasks ? `<div class="notice warn">${state.incomplete_tasks} recorded task(s) are incomplete; ${state.unknown_cost_calls} request costs are unknown. Monetary totals are known subtotals; incomplete models cannot qualify.</div>` : '';
  $('#view').innerHTML = fixture + incomplete + (!state.connected ? empty() : ({overview, tasks:tasksView, compare:compareView, proposal:proposalView}[view])());
}
async function getProposal() {
  try { proposal = await api('/api/recommend',constraints); if(view==='proposal') render(); }
  catch(error) { notice(error.message,true); }
}
async function evaluate() {
  if (busy) return;
  if (!state.connected) { $('#sources').showModal(); return; }
  busy = true; nav('compare');
  notice('Replaying saved outputs in the local evaluation worker. No model calls.');
  try {
    const job = await api('/api/evaluate',{});
    let result;
    for (let i=0;i<120;i++) {
      await new Promise(resolve=>setTimeout(resolve,750));
      result = await api('/api/jobs/'+job.job_id);
      if (result.status !== 'running') break;
    }
    if (result?.status !== 'complete') throw new Error(result?.detail || 'Evaluation is still running. Refresh in a moment.');
    await refresh();
    notice('Evidence replay complete. Contract checks and Ostiari action boundaries are available.');
  } catch(error) { notice(error.message,true); }
  finally { busy=false; render(); }
}
function inspectCase(task) {
  $('#detail-content').innerHTML = `<div class="dialog-head"><div><p class="eyebrow">${esc(label(task.model))} · ${esc(task.case_id)}</p><h2>${esc(task.title)}</h2></div><button class="icon-button" data-close="detail" aria-label="Close case details">×</button></div><p class="ticket">${esc(task.ticket)}</p><div class="checks">${task.assessment.checks.map(c=>`<span class="tag ${c.passed?'good':'warn'}">${c.passed?'✓':'×'} ${esc(c.name)}</span>`).join('')}</div><details open><summary>Expected decision</summary><pre>${esc(JSON.stringify(task.expected,null,2))}</pre></details>${task.stages.map(s=>`<details ${s.name==='draft'?'open':''}><summary>${esc(s.name)} · recorded response</summary><pre>${esc(s.output||s.error_type||'No response')}</pre></details>`).join('')}<p class="fine">The expected decision is used only by the grader; it was not included in the model request.</p>`;
  $('#detail').showModal();
}
function modelCases(model) {
  const tasks = analysis.tasks.filter(t=>t.model===model).sort((a,b)=>Number(a.assessment.passed)-Number(b.assessment.passed));
  $('#detail-content').innerHTML = `<div class="dialog-head"><div><p class="eyebrow">CASE-LEVEL EVIDENCE</p><h2>${esc(label(model))}</h2></div><button class="icon-button" data-close="detail" aria-label="Close case list">×</button></div><p>Failures are shown first. Open any case to inspect the expected decision and actual response.</p><div class="table-wrap" style="margin-top:20px"><table><thead><tr><th>Case</th><th>Result</th><th>Critical</th></tr></thead><tbody>${tasks.map(t=>`<tr class="clickable" data-case="${esc(t.id)}" tabindex="0" role="button" aria-label="Inspect ${esc(t.title)}"><td class="task-name">${esc(t.title)}<small>${esc(t.case_id)}</small></td><td><span class="tag ${t.assessment.passed?'good':'warn'}">${t.assessment.passed?'Pass':'Fail'}</span></td><td class="muted">${t.critical?'Yes':'—'}</td></tr>`).join('')}</tbody></table></div>`;
  $('#detail').showModal();
}
document.addEventListener('click',async event=>{
  const close = event.target.closest('[data-close]');
  if(close) return $('#'+close.dataset.close).close();
  const navButton=event.target.closest('[data-view]');
  if(navButton) return nav(navButton.dataset.view);
  const step=event.target.closest('[data-step]');
  if(step) { if(step.dataset.step==='connect') $('#sources').showModal(); else nav(step.dataset.step); return; }
  const task=event.target.closest('[data-task]');
  if(task) {selected=state.tasks.find(t=>t.id===task.dataset.task);nav('tasks');return;}
  const caseButton=event.target.closest('[data-case]');
  if(caseButton) {$('#detail').close();inspectCase(analysis.tasks.find(t=>t.id===caseButton.dataset.case));return;}
  const caseList=event.target.closest('[data-model-cases]');
  if(caseList) return modelCases(caseList.dataset.modelCases);
  const action=event.target.closest('[data-action]')?.dataset.action;
  if(action==='sources') $('#sources').showModal();
  if(action==='tasks') nav('tasks');
  if(action==='proposal') nav('proposal');
  if(action==='evaluate') evaluate();
  if(action==='about') {
    try {const data=await api('/api/integrations');$('#about-content').innerHTML=data.components.map(c=>`<div class="source-option"><div><h3>${esc(c.name)} <span class="tag">${esc(c.version)}</span></h3><p>${esc(c.role)}</p></div></div>`).join('')+`<p class="fine">${esc(data.native_connectors)}</p>`;$('#about').showModal();}catch(error){notice(error.message,true);}
  }
  if(action==='export') {
    try {
      const recording = await api('/api/recording');
      const evidence={schema:'ai-ops.proposal.v1',exported_at:new Date().toISOString(),recording_id:state.recording_id,contract_hash:analysis.contract_hash,evaluation_revision:analysis.evaluation_revision,proposal,model_summaries:analysis.models,provenance:state.provenance,recording,assessments:analysis.tasks.map(t=>({case_id:t.case_id,model:t.model,expected:t.expected,assessment:t.assessment,governance:t.governance})),controls:analysis.controls};
      const url=URL.createObjectURL(new Blob([JSON.stringify(evidence,null,2)],{type:'application/json'}));
      const link=document.createElement('a');link.href=url;link.download='routing-proposal.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    } catch(error) { notice(error.message,true); }
  }
});
document.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&event.target.matches('tr[role="button"]')){event.preventDefault();event.target.click();}});
document.addEventListener('submit',async event=>{
  if(event.target.id!=='constraints') return;
  event.preventDefault();
  constraints={min_pass_rate:Number($('#min-pass').value)/100,max_p95_ms:Number($('#max-latency').value)*1000,monthly_tasks:Number($('#monthly-tasks').value)};
  await getProposal();
});
$('#sources-button').addEventListener('click',()=>$('#sources').showModal());
$('#connect').addEventListener('click',async()=>{
  $('#connect').disabled=true;
  try {const result=await api('/api/connect',{});$('#sources').close();await refresh();nav('overview');notice(result.deduplicated?'This recording is already connected. No duplicate charges were added.':`Connected ${result.added_events} model-stage records. Start by inspecting a baseline task.`);}
  catch(error){notice(error.message,true);$('#sources').close();}
  finally{$('#connect').disabled=false;}
});
$('#upload').addEventListener('change',async event=>{
  const file=event.target.files[0];if(!file)return;
  try {if(file.size>8000000)throw new Error('Recording exceeds 8 MB.');const data=JSON.parse(await file.text());await api('/api/import',data);$('#sources').close();await refresh();notice('Recording imported. Its structure and cost calculation were checked; external provenance is self-reported.');}
  catch(error){notice(error.message,true);$('#sources').close();}
  finally{event.target.value='';}
});
$('#motion').addEventListener('click',()=>{
  const paused=$('.journey').classList.toggle('paused');$('#motion').setAttribute('aria-pressed',String(paused));$('#motion').setAttribute('aria-label',paused?'Resume workflow animation':'Pause workflow animation');$('#motion').textContent=paused?'▷':'Ⅱ';
});
refresh().catch(error=>notice(error.message,true));
