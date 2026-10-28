const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const amount = value => value === null || value === undefined ? 'Unknown' : `$${value}`;
const date = value => value ? new Date(value * 1000).toLocaleString() : 'Not received';
const badge = (text, kind='accent') => `<span class="tag ${kind}">${escape(text)}</span>`;
const modelName = value => String(value || 'Model unavailable').replace(/-\d{4}-\d{2}-\d{2}$/, '').replace(/^gpt-/,'GPT-');
const readable = value => String(value || 'Unknown').replace(/[_.]/g,' ');
const evidenceName = value => ({recorded:'Saved recording',observed:'Captured from application',fixture:'Synthetic test data'}[value] || readable(value));
const stageName = value => ({triage:'Classify request',draft:'Draft decision and reply'}[value] || readable(value));
const stageHelp = value => ({triage:'Identify what the customer needs.',draft:'Propose a policy-based decision and a customer reply.'}[value] || 'A model call captured by your application.');
const coverageName = value => ({single_attempt:'This attempt captured',final_response_only:'Final response only; earlier attempts may be missing',unknown:'Attempt capture is unknown'}[value] || readable(value));
const usageName = value => ({provider_reported:'Tokens reported by provider',estimated:'Estimated tokens',unknown:'Token usage unknown'}[value] || readable(value));
const timing = value => value === null || value === undefined ? 'Unmeasured' : `${value} ms`;
const tokenDetails = call => !call.usage ? 'Tokens unknown' : call.schema_version==='bedrock.usage.v1' ?
  `${call.usage.input_tokens} input / ${call.usage.output_tokens} output / ${call.usage.cache_read_input_tokens} cache read / ${call.usage.cache_write_input_tokens} cache write tokens (AWS categories)` :
  `${call.usage.prompt_tokens} input / ${call.usage.completion_tokens} output / ${call.usage.cached_tokens} cached tokens`;
const taskAmount = task => task.call_count > 0 && task.unknown_cost_calls === task.call_count ? 'Unknown' : amount(task.api_estimate_usd);
const exclusionName = value => ({
  'Contract pass rate below threshold':'Too few tickets passed all checks',
  'Task p95 exceeds the latency limit':'Recorded response time exceeds your limit',
  'Critical decision checks failed':'Failed a critical policy or safety check',
  'Incomplete dataset or unknown request costs':'Missing test cases or unknown call costs',
}[value] || value);
let session, page = 'usage', usage, jobRows = [], proposalRows = [], filters = '';
let generation = 0;
let taskPage = 0, loginMethods = {local:true,company:false}, usageRequest = 0;
const canEdit = () => session?.user && session.user.role !== 'viewer';
const isAdmin = () => session?.user?.role === 'admin';
const billing = createBilling({api, action, notice, isAdmin, getEpoch:()=>generation,
  onExample:()=>Promise.all([loadUsage(),loadSources()]),
  onTasks:async scope=>{
    const params=new URLSearchParams({...scope,include_fixtures:String(scope.include_fixtures)});
    filters=params.toString();taskPage=0;
    const form=$('filters');form.reset();
    form.elements.source_id.value=scope.source_id;
    form.elements.start.value=scope.start.slice(0,10);form.elements.end.value=scope.end.slice(0,10);
    form.elements.include_fixtures.checked=scope.include_fixtures;
    await loadUsage();navigate('tasks');
  }
});

async function api(path, body) {
  const epoch = generation;
  const response = await fetch(path, {credentials:'same-origin', cache:'no-store',
    ...(body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json', 'X-Workbench-CSRF':session?.csrf || ''}, body:JSON.stringify(body)})});
  const value = await response.json();
  if (epoch !== generation) throw new Error('Session changed. Retry after signing in.');
  if (!response.ok) {
    if (response.status === 401 && !path.endsWith('/login')) showLogin();
    const error = new Error(value.detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return value;
}
function notice(text, error=false) {
  $('message').textContent = text;
  $('message').className = `notice${error ? ' error' : ''}`;
  $('message').hidden = !text;
}
async function action(fn) {
  try { await fn(); } catch (error) { notice(error.message, true); }
}
function showLogin() {
  session = null; generation++;
  billing.reset();
  usage = null; jobRows = []; proposalRows = [];
  for (const id of ['metrics','task-list','sources','jobs','evaluation-result','proposals','users','audit',
                    'recording-select','proposal-job','evidence-counts','cost-note',
                    'operations-metrics','operations-alerts','operations-retention','usage-guide']) $(id).replaceChildren();
  $('team-view').hidden = true; $('login-view').hidden = false;
  $('token-value').value = ''; $('token-panel').hidden = true;
  $('setup-note').textContent = 'Sign in with the account your team administrator created.';
  $('login-form').hidden = !loginMethods.local;
  $('company-login').hidden = !loginMethods.company;
}
function navigate(next) {
  if (['team','operations'].includes(next) && !isAdmin()) return;
  page = next;
  document.querySelectorAll('[id^="page-"]').forEach(el => { if (el.tagName === 'SECTION') el.hidden = el.id !== `page-${page}`; });
  document.querySelectorAll('[data-page]').forEach(el => el.classList.toggle('active', el.dataset.page === page));
  document.querySelectorAll('.journey-step').forEach(el => {
    if (el.dataset.goto === page) el.setAttribute('aria-current','step');
    else el.removeAttribute('aria-current');
  });
  $('page-label').textContent = document.querySelector(`[data-page="${page}"]`).textContent;
  document.querySelector('.content').scrollTo({top:0,behavior:'instant'});
  window.scrollTo({top:0,behavior:'instant'});
  if (page === 'proposals') action(loadProposals);
  if (page === 'team') action(loadTeam);
  if (page === 'operations') action(loadOperations);
  if (page === 'billing') action(()=>billing.load());
}
function access() {
  document.querySelectorAll('[data-admin]').forEach(el => el.hidden = !isAdmin());
  document.querySelectorAll('[data-analyst]').forEach(el => el.hidden = !canEdit());
  $('user-form').hidden = !loginMethods.local;
  $('identity-form').hidden = !loginMethods.company;
}
async function enter() {
  generation++;
  $('login-view').hidden = true; $('team-view').hidden = false;
  $('team-name').textContent = session.user.team_name;
  $('user-role').textContent = session.user.role;
  $('signed-in').textContent = session.user.username;
  access(); navigate('usage');
  await Promise.all([loadUsage(), loadSources(), loadRecordings(), loadJobs()]);
}
function metric(label, value, note, flow) {
  return `<article class="metric" data-flow="${flow}"><p class="metric-label">${escape(label)}</p><p class="metric-value small-value">${escape(value)}</p><p class="metric-sub">${escape(note)}</p></article>`;
}
function usageGuide() {
  if (!usage.events) {
    const filtered = [...new URLSearchParams(filters)].some(([key,value])=>value && !(key==='include_fixtures' && value==='false'));
    return `<h2>${filtered?'No usage matches these filters.':'Start with an example or connect your application.'}</h2>
      <p>${filtered?'Change or clear the overview filters to see more task runs.':'The recorded example lets you explore task costs and model quality. Connecting an application lets you collect your own usage.'}</p>
      <div class="row-actions">${filtered?'<button class="button" data-reset-filters>Clear filters</button>':''}
      <button class="button" data-goto="evaluations">Explore saved model answers</button><button class="button" data-goto="sources">Connect an application</button></div>
      ${canEdit()?'':'<p class="fine">Your viewer role can inspect results. Ask an analyst or administrator to load data or connect an application.</p>'}`;
  }
  const hasSupport = usage.tasks.some(task=>task.context?.kind==='support_comparison');
  return `<h2>${hasSupport?'Understand the recorded support example.':'Follow the cost from task to model call.'}</h2>
    <p>${hasSupport?'A task run is one support ticket handled by one model. Testing the same ticket with another model creates another run. The bundled example has 24 tickets × 3 models = 72 runs, with two calls per run.':'A task run groups related model calls from an application. One run can include several steps, models, or attempts.'}</p>
    <p class="fine">${hasSupport?'Recorded calls were saved from an earlier run. Opening these pages and replaying checks makes no new model API calls.':'Open Task explorer to inspect the captured steps. Use Model evaluations when you have saved answers to check for quality.'}</p>`;
}
function orderedCalls(task) {
  const calls=[...task.calls];
  return task.context ? calls.sort((a,b)=>['triage','draft'].indexOf(a.stage)-['triage','draft'].indexOf(b.stage)) :
    calls.sort((a,b)=>a.occurred_at.localeCompare(b.occurred_at));
}
function callDetail(call) {
  return `<tr><td>${escape(readable(call.stage))}<br>${badge(evidenceName(call.evidence))}</td>
    <td>${escape(call.provider)}<br>${escape(call.model)}</td>
    <td>${escape(amount(call.api_estimate_usd))}<br><small>${escape(call.unknown_reason || `Saved price reference ${call.pricebook_id.slice(0,12)}`)}</small></td>
    <td>${escape(usageName(call.usage_basis))}<br>${escape(coverageName(call.attempt_coverage))}<br><small>${escape(tokenDetails(call))}</small>${call.bedrock?`<br><small>${escape(call.bedrock.region)} · ${escape(call.bedrock.service_tier)} tier · SDK retries: ${call.bedrock.sdk_retry_count ?? 'unknown'}${call.bedrock.capture_issue?` · ${escape(readable(call.bedrock.capture_issue))}`:''}</small>`:''}</td>
    <td>${escape(timing(call.latency_ms))}${call.bedrock?`<br><small>Provider: ${escape(timing(call.bedrock.provider_latency_ms))}</small>`:''}</td></tr>`;
}
function taskBody(task,index) {
  const calls=orderedCalls(task);
  return `${task.context?`<div class="task-request"><p class="eyebrow">CUSTOMER REQUEST · AUTHORED EXAMPLE</p><p>${escape(task.context.request)}</p></div>`:
    '<p class="data-note">This source provides usage details only. A business description for this task is unavailable.</p>'}
    <ol class="task-steps" aria-label="Captured model calls">${calls.map(call=>`<li>
      <div class="section-head"><strong>${escape(task.context?stageName(call.stage):readable(call.stage))}</strong>${badge(call.status==='success'?'Call completed':call.status==='error'?'Call failed':'Call interrupted',call.status==='success'?'good':'danger')}</div>
      <p>${escape(task.context?stageHelp(call.stage):'A model call captured by your application.')}</p>
      <p class="call-cost">${escape(amount(call.api_estimate_usd))}<small>estimated API cost</small></p>
      <p class="fine">${escape(modelName(call.model))} · ${escape(timing(call.latency_ms))} · ${escape(evidenceName(call.evidence))}</p>
      ${call.unknown_reason?`<p class="data-note">${escape(call.unknown_reason)}</p>`:''}
    </li>`).join('')}</ol>
    <div class="task-total"><span>${task.unknown_cost_calls?'Known API subtotal':'Total estimated API cost'}<small>${task.call_count} captured model calls${task.unknown_cost_calls?` · ${task.unknown_cost_calls} with unknown cost`:''}${task.uncovered_attempt_calls?` · ${task.uncovered_attempt_calls} with incomplete attempt capture`:''}</small></span><strong>${escape(taskAmount(task))}</strong></div>
    <p class="fine">“Call completed” means the API returned a response. Model evaluations checks whether the answer was correct.</p>
    <details class="help-details technical-details"><summary>Tokens, timings, and capture details</summary>
      <p>Tokens are the input and output units used to price a model call. Cached tokens are reused input. Each cost uses the saved model price; missing usage or unsupported prices remain unknown.</p>
      <div class="table-wrap"><table><thead><tr><th>Step / evidence</th><th>Provider / model version</th><th>API estimate</th><th>Tokens / attempt capture</th><th>Time taken</th></tr></thead><tbody>${calls.map(callDetail).join('')}</tbody></table></div>
      <p class="fine">Project: ${escape(task.project)}<br>Task reference: ${escape(task.task_id)}</p>
    </details>
    ${task.calls_has_more?`<p class="fine">Showing ${task.calls.length} of ${task.call_count} captured calls. The subtotal covers all captured calls in the current filters.</p><button class="button" data-more-calls="${index}">Load more calls</button>`:''}
    ${task.context?'<button class="button task-next" data-goto="evaluations">Check saved answer quality</button>':''}`;
}
async function loadUsage() {
  const epoch = generation;
  const request = ++usageRequest;
  const params = new URLSearchParams(filters);
  params.set('page',String(taskPage));
  const result = await api(`/api/pilot/usage?${params}`);
  if (epoch !== generation || request !== usageRequest) return;
  usage = result;
  $('metrics').innerHTML = metric('Estimated API spend', usage.events && usage.unknown_cost_calls===usage.events?'Unknown':amount(usage.api_estimate_usd), 'Known captured costs · USD · not an invoice','connect') +
    metric('Task runs', usage.task_count, `${usage.events} model calls grouped into these runs`,'connect') +
    metric('Calls without a price', usage.unknown_cost_calls, 'Missing token usage or supported model pricing','connect') +
    metric('Calls with incomplete capture', usage.uncovered_attempt_calls, 'Cost or attempt information is missing','connect');
  $('usage-guide').innerHTML = usageGuide();
  $('cost-note').textContent = usage.cost_note;
  $('evidence-counts').textContent = Object.entries(usage.evidence_counts).map(([k,v])=>`${evidenceName(k)}: ${v} calls`).join(' · ') || 'No calls in this view yet.';
  const tasks = usage.tasks;
  $('task-guide').textContent = tasks.some(task=>task.context) ?
    'In this support comparison, each ticket/model pair is a separate run. “Classify request” identifies the customer’s need; “Draft decision and reply” proposes a response. Open a card to see the customer request and both costs.' :
    'For example, handling a support request can involve classifying the request, then drafting a reply. Your application groups related calls into a task run.';
  $('task-list').innerHTML = tasks.map((task,index) => `<details class="panel task-card">
    <summary><span class="task-summary-main"><strong>${escape(task.context?.title || `Task run · ${task.task_id.slice(0,24)}`)}</strong><small>${escape([...new Set(task.calls.map(c=>modelName(c.model)))].join(', '))} · ${task.call_count} model calls${task.context?` · Example ${escape(task.context.case_id)}`:''}</small></span>
      <span class="task-summary-cost"><strong>${escape(taskAmount(task))}</strong><small>${task.unknown_cost_calls?'known costs only':'estimated API cost'}</small><span class="expand-cue">View steps <span aria-hidden="true">⌄</span></span></span></summary>
    <div class="task-body">${taskBody(task,index)}</div></details>`).join('') ||
      '<article class="panel"><h2>No task runs in this view yet.</h2><p class="data-note">Load saved answers in Model evaluations, connect an application in Usage sources, or change your overview filters.</p><div class="row-actions"><button class="button" data-goto="evaluations">Explore the recorded example</button><button class="button" data-goto="usage">Check usage filters</button></div></article>';
  $('tasks-page').textContent = usage.task_count ? `Page ${usage.page+1} · ${usage.task_count} task runs · highest known cost first` : 'No task runs';
  $('tasks-previous').disabled = taskPage === 0;
  $('tasks-next').disabled = !usage.has_more;
}
async function moreCalls(button) {
  const task = usage.tasks[Number(button.dataset.moreCalls)];
  const params = new URLSearchParams(filters);
  params.set('source_id',task.source_id); params.set('task_id',task.task_id);
  params.set('offset',String(task.calls.length));
  button.disabled = true;
  try {
    const result = await api(`/api/pilot/calls?${params}`);
    task.calls.push(...result.calls);
    task.calls_has_more=result.has_more;
    button.closest('.task-body').innerHTML=taskBody(task,Number(button.dataset.moreCalls));
  } finally { button.disabled=false; }
}
async function loadSources() {
  const result = await api('/api/pilot/sources');
  const selected = $('source-filter').value;
  $('source-filter').innerHTML = '<option value="">All sources</option>' + result.sources.map(s=>`<option value="${escape(s.id)}">${escape(s.name)}</option>`).join('');
  $('source-filter').value = selected;
  $('sources').innerHTML = result.sources.map(s=>`<article class="panel source-row"><div><h2>${escape(s.kind==='recording'?'Recorded support comparison':s.name)}</h2>
    <p class="fine">${s.kind==='recording'?'Saved example; not a live connection':s.kind==='bedrock'?'Amazon Bedrock · Converse / ConverseStream':'AxonLLM application connection'} · ${s.event_count} captured calls · Last received: ${escape(date(s.last_received_at))}</p>
    ${sourceHealth(s)}
    ${s.kind!=='recording' && !s.event_count?'<p class="data-note">Waiting for calls. Configure the application connector with an active token to begin sending usage.</p>':''}
    <div class="fine">${s.tokens.map(t=>`<p>Connection token ${escape(t.prefix)}… · ${t.revoked?'revoked':`expires ${escape(date(t.expires_at))}`}
      ${isAdmin()&&!t.revoked?`<button class="button small" data-revoke-token="${t.id}" data-source="${s.id}">Revoke token ${escape(t.prefix)}</button>`:''}</p>`).join('')}</div></div>
    ${isAdmin() && s.kind!=='recording' ? `<div class="row-actions"><button class="button soft" data-token="${s.id}">Issue token</button><button class="button" data-revoke="${s.id}">Revoke all tokens</button></div>` : ''}</article>`).join('') ||
      '<p class="notice">No sources connected yet. An administrator can create an AxonLLM or Amazon Bedrock source.</p>';
}
function sourceHealth(source) {
  const state=source.collection;
  if (!state || source.kind==='recording') return '';
  const labels={connected:'Connected',backlog:'Delivery backlog',stale:'Collector stopped reporting',unmonitored:'Health not reported',token_required:'Active token required'};
  const explanations={connected:'Delivery is running. An idle application can have zero calls.',
    backlog:'Events are waiting in the local outbox. Check the delivery process and retry status.',
    stale:'No heartbeat from one or more collectors for over three minutes. Check the application host and delivery process; costs may be missing.',
    unmonitored:'Run deliver --watch with this source token to report collection health.',
    token_required:'Issue or rotate a token, then restart delivery with the new token.'};
  return `<p>${badge(labels[state.status] || 'Unknown',state.status==='connected'?'good':'warn')}</p><p class="data-note">${escape(explanations[state.status] || '')}</p>
    ${state.collectors?`<p class="fine">Last reported: ${state.pending_events} waiting · ${state.retrying_events} retrying · ${state.inflight_calls} in progress or interrupted. Heartbeat: ${escape(date(state.last_heartbeat_at))}${state.oldest_pending_at?` · Oldest waiting: ${escape(state.oldest_pending_at)}`:''}</p><p class="fine">After an application crash, stop capture before running recover-inflight. Interrupted calls keep unknown costs.</p>`:''}
    ${isAdmin()&&state.reports?.some(r=>r.stale)?`<details class="help-details"><summary>Retire a collector you have stopped permanently</summary><p>Retiring removes this collector’s stale warning. Check and deliver its remaining outbox first.</p>${state.reports.filter(r=>r.stale).map(r=>`<button class="button small" data-retire-collector="${escape(r.collector_id)}" data-source="${escape(source.id)}">Retire collector ${escape(r.collector_id.slice(0,8))}</button>`).join('')}</details>`:''}`;
}
async function loadRecordings() {
  const result = await api('/api/pilot/recordings');
  const selected = $('recording-select').value;
  $('recording-select').innerHTML = result.recordings.map(r=>`<option value="${r.id}">Support comparison · ${escape(date(r.created_at))} · ${r.id.slice(0,8)}</option>`).join('');
  if (result.recordings.some(r=>r.id===selected)) $('recording-select').value = selected;
  $('evaluate-form').querySelector('button').disabled=!result.recordings.length;
  $('evaluation-help').textContent=result.recordings.length ?
    'Choose saved answers, then run the evaluation. The checks continue even if you leave this page.' :
    canEdit()?'Load the recorded example or upload a compatible recording to enable Run evaluation.':'Ask an analyst or administrator to load saved answers. Your viewer role can inspect completed results.';
}
async function loadJobs() {
  const epoch = generation;
  const result = await api('/api/pilot/evaluations');
  if (epoch !== generation) return;
  jobRows = result.evaluations;
  $('worker-status').textContent = result.worker_healthy ? 'Evaluation service ready' : 'Evaluation service unavailable';
  $('worker-status').className = `tag ${result.worker_healthy?'good':'warn'}`;
  $('jobs').innerHTML = jobRows.map(j=>`<article class="panel job-row"><div><strong>Support policy evaluation</strong> ${badge({complete:'Checks complete',queued:'Waiting to run',running:'Checking answers',failed:'Evaluation failed',cancelled:'Cancelled'}[j.status] || readable(j.status),j.status==='complete'?'good':j.status==='failed'?'danger':'accent')}
    <p class="fine">Started ${escape(date(j.created_at))} · Run ${escape(j.id.slice(0,8))}</p>${j.error?`<p class="data-note">${escape(j.error)}</p>`:''}</div><div class="row-actions">
    ${j.status==='complete'?`<button class="button soft" data-result="${j.id}">Inspect results</button>`:''}
    ${canEdit() && ['queued','running'].includes(j.status)?`<button class="button" data-cancel="${j.id}">Cancel</button>`:''}</div></article>`).join('') || '<p class="notice">No evaluations yet. Choose saved answers above and run the checks to compare model quality.</p>';
  const selected = $('proposal-job').value;
  $('proposal-job').innerHTML = jobRows.filter(j=>j.status==='complete').map(j=>`<option value="${j.id}">Support evaluation · ${escape(date(j.created_at))} · ${j.id.slice(0,8)}</option>`).join('');
  if (jobRows.some(j=>j.id===selected && j.status==='complete')) $('proposal-job').value = selected;
  const complete=jobRows.some(j=>j.status==='complete');
  $('proposal-form').querySelector('button').disabled=!complete;
  $('review-help').textContent=complete?'A completed evaluation is available. Set your requirements below to save a review.':
    'Complete an evaluation in Model evaluations first. This enables the review form below.';
}
async function showResult(id) {
  const job = await api(`/api/pilot/evaluations/${id}`);
  const result = job.analysis;
  $('evaluation-result').innerHTML = `<article class="panel"><div class="section-head"><div><h2>How the models performed</h2><p>${result.total_calls} saved calls · ${escape(amount(result.total_cost_usd))} estimated API cost · ${result.mode==='fixture'?'Synthetic test data':'Recorded model answers'}</p></div><button class="button soft" id="export-result">Export results</button></div>
    <div class="table-wrap"><table><thead><tr><th>Model</th><th>Tickets passed</th><th>Critical failures</th><th>Response time, p95</th><th>Cost per passing ticket</th></tr></thead><tbody>${result.models.map(m=>`<tr><td>${escape(modelName(m.model))}</td><td>${m.passed}/${m.evaluated}</td><td>${m.critical_failures}</td><td>${m.p95_ms===null?'Unknown':`${escape(m.p95_ms)} ms`}</td><td>${escape(amount(m.cost_per_pass_usd))}</td></tr>`).join('')}</tbody></table></div>
    <dl class="result-guide"><div><dt>Tickets passed</dt><dd>A ticket passes only when all its decision and action-boundary checks pass.</dd></div><div><dt>Critical failures</dt><dd>Failures on critical cases, such as identity or policy restrictions. Any critical failure excludes a model from a recommendation.</dd></div><div><dt>Response time, p95</dt><dd>95% of the recorded task runs finished within this time.</dd></div><div><dt>Cost per passing ticket</dt><dd>Total model cost divided by tickets passed, including money spent on failed tickets.</dd></div></dl>
    <p class="data-note">These checks replay saved answers. They do not measure current model speed or quality on other tasks. Export results to inspect individual tickets and checks.</p><button class="button primary" data-goto="proposals">Review routing criteria</button></article>`;
  $('export-result').onclick = () => download(`evaluation-${id}.json`, job);
  $('evaluation-result').scrollIntoView({block:'start'});
}
async function loadProposals() {
  const result = await api('/api/pilot/proposals');
  proposalRows = result.proposals;
  $('proposals').innerHTML = proposalRows.map(p=>`<article class="panel"><div class="section-head"><div><p class="eyebrow">SAVED ROUTING REVIEW</p><h2>${p.recommended_model?escape(p.recommended_model):p.status==='fixture_only'?'Fixture evidence only':'No model qualifies'}</h2></div>${badge('Not applied','warn')}</div>
    <p class="data-note">${p.recommended_model?'This candidate meets the saved requirements. Review the supporting cases before changing your application.':'Every candidate failed at least one requirement. Inspect the reasons below and address the failing cases before changing your model.'}</p><p class="proposal-copy">Required: ${p.min_pass_rate*100}% tickets passed · Zero critical failures · p95 within ${p.max_p95_ms} ms · ${p.monthly_tasks} task runs per month assumed</p>
    <div class="table-wrap"><table><thead><tr><th>Model</th><th>Decision</th><th>Why</th></tr></thead><tbody>${p.candidates.map(c=>`<tr><td>${escape(modelName(c.model))}</td><td>${badge(c.eligible?'Meets requirements':'Excluded',c.eligible?'good':'warn')}</td><td>${escape(c.exclusions.map(exclusionName).join('; ') || 'Meets the selected checks')}</td></tr>`).join('')}</tbody></table></div>
    <p class="proposal-copy">Projected monthly API savings: <strong>${p.projected_monthly_api_savings_usd===null?'Unavailable':escape(amount(p.projected_monthly_api_savings_usd))}</strong>${p.projected_monthly_api_savings_usd===null?'<br><span class="fine">A qualifying model and complete comparison costs are required to calculate savings.</span>':''}</p>
    <details class="help-details"><summary>Scope, assumptions, and saved evidence</summary><p>${escape(p.scope)}</p><ul class="limitations">${p.limitations.map(l=>`<li>${escape(l)}</li>`).join('')}</ul><p class="fine">Recording ${p.recording_id.slice(0,16)} · evaluator ${p.evaluation_revision.slice(0,16)}</p></details>
    <button class="button soft" data-export-proposal="${p.id}">Export routing review</button></article>`).join('') || '<p class="notice">No saved reviews yet. Choose a completed evaluation and your requirements above, then save the recommendation.</p>';
}
async function loadTeam() {
  const [members, audit] = await Promise.all([api('/api/pilot/users'), api('/api/pilot/audit')]);
  $('users').innerHTML = members.users.map(u=>`<article class="panel user-row"><div><strong>${escape(u.username)}</strong> ${badge(u.role)} ${!u.active?badge('Disabled','warn'):''}</div>${u.active?`<button class="button" data-disable="${u.id}">Disable account</button>`:''}</article>`).join('');
  const actions={'session.created':'Signed in','session.sso_created':'Signed in with SSO','session.revoked':'Signed out',
    'source.token_issued':'Connection token created','source.token_revoked':'Connection token revoked','source.tokens_revoked':'All source tokens revoked',
    'proposal.created':'Routing review saved','recording.imported':'Saved answers imported','usage.ingested':'Usage received',
    'demo.seeded':'Recorded demo loaded','user.sso_provisioned':'SSO member added'};
  $('audit').innerHTML = `<table><thead><tr><th>When</th><th>Person or service</th><th>Activity</th></tr></thead><tbody>${audit.events.map(e=>`<tr><td>${escape(date(e.created_at))}</td><td>${escape(e.actor)}</td><td>${escape(actions[e.action] || readable(e.action))}</td></tr>`).join('')}</tbody></table>`;
}
async function loadOperations() {
  const state = await api('/api/pilot/operations');
  $('operations-status').textContent = state.status === 'healthy' ? 'Services healthy' : 'Needs attention';
  $('operations-status').className = `tag ${state.status === 'healthy'?'good':'warn'}`;
  $('operations-metrics').innerHTML = metric('Evaluation service',state.worker_healthy?'Ready':'Unavailable','Runs your queued checks in the background','connect') +
    metric('Evaluations waiting',state.jobs.queued || 0,`Oldest wait: ${state.oldest_queued_seconds} seconds`,'tasks') +
    metric('Failed evaluations',state.failed_jobs_24h,'Last 24 hours','compare') +
    metric('Calls without a price',state.unknown_cost_calls_24h,`Out of ${state.observed_calls_24h} new application calls in 24 hours`,'proposal');
  $('operations-alerts').innerHTML = state.alerts.length ? state.alerts.map(a=>`<p class="data-note">${badge(a.severity,a.severity==='critical'?'warn':'accent')} ${escape(a.message)}</p>`).join('') : '<p class="data-note">No active operational alerts.</p>';
  $('operations-retention').textContent = `${state.retention_days ? `Usage metadata: ${state.retention_days} days. Evidence, billing snapshots and saved reviews: ${state.evidence_retention_days || 'unlimited'} days. Audit history: ${state.audit_retention_days || 'unlimited'} days.` : 'Scheduled usage retention is not enabled in this local environment.'} ${state.maintenance_age_seconds===null?'Maintenance has not run yet.':`Last maintenance completed ${Math.floor(state.maintenance_age_seconds/60)} minutes ago.`}`;
}
function download(name, data) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)], {type:'application/json'}));
  const link = document.createElement('a'); link.href=url; link.download=name; link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function submit(id, fn) {
  $(id).addEventListener('submit', async event=>{
    event.preventDefault();
    const button = event.submitter; if (button) button.disabled = true;
    try { await action(()=>fn(new FormData(event.target))); } finally { if (button) button.disabled=false; }
  });
}
$('login-form').onsubmit = async event => {
  event.preventDefault(); const button = event.submitter; button.disabled=true; $('login-error').hidden=true;
  try {
    const form = new FormData(event.target);
    session = await api('/api/auth/login', {username:form.get('username'),password:form.get('password')});
    event.target.reset(); await enter();
  } catch(error) { $('login-error').textContent=error.message; $('login-error').hidden=false; }
  finally { button.disabled=false; }
};
$('logout').onclick = ()=>action(async()=>{await api('/api/auth/logout',{}); showLogin();});
$('motion').onclick = ()=>{
  const paused = document.body.classList.toggle('paused');
  $('motion').textContent=paused?'Resume motion':'Pause motion'; $('motion').setAttribute('aria-pressed',String(paused));
};
submit('filters', async data=>{
  const params = new URLSearchParams({project:data.get('project'),source_id:data.get('source_id'),include_fixtures:String(data.has('include_fixtures'))});
  for (const key of ['start','end']) if (data.get(key)) params.set(key,`${data.get(key)}T00:00:00Z`);
  filters=params.toString(); taskPage=0;
  await loadUsage();
});
$('tasks-previous').onclick = ()=>action(async()=>{taskPage=Math.max(0,taskPage-1); await loadUsage(); navigate('tasks');});
$('tasks-next').onclick = ()=>action(async()=>{taskPage++; await loadUsage(); navigate('tasks');});
$('refresh-operations').onclick = ()=>action(loadOperations);
submit('source-form', async data=>{await api('/api/pilot/sources',{name:data.get('name'),kind:data.get('kind')}); $('source-form').reset(); $('create-source').textContent='Create AxonLLM source'; await loadSources(); notice('Source created. Issue a token to connect the application.');});
$('source-kind').onchange=()=>{$('create-source').textContent=$('source-kind').value==='bedrock'?'Create Amazon Bedrock source':'Create AxonLLM source';};
$('refresh-sources').onclick=()=>action(loadSources);
submit('evaluate-form', async()=>{await api('/api/pilot/evaluations',{recording_id:$('recording-select').value}); await loadJobs(); notice('Evaluation queued. You can leave this page; the worker will save its result.');});
submit('proposal-form', async data=>{
  await api(`/api/pilot/evaluations/${$('proposal-job').value}/recommend`,{min_pass_rate:Number(data.get('pass'))/100,max_p95_ms:Number(data.get('latency')),monthly_tasks:Number(data.get('volume'))});
  await loadProposals(); notice('Routing review saved. No route was changed.');
});
submit('user-form', async data=>{await api('/api/pilot/users',Object.fromEntries(data)); $('user-form').reset(); await loadTeam(); notice('Team member added.');});
submit('identity-form', async data=>{await api('/api/pilot/identities',Object.fromEntries(data)); $('identity-form').reset(); await loadTeam(); notice('Company member added.');});
$('load-example').onclick = ()=>action(async()=>{
  await api('/api/pilot/recordings/example',{}); await Promise.all([loadUsage(),loadRecordings(),loadSources()]);
  notice('Loaded the saved comparison. Explore its tasks or select Run evaluation to check the saved answers. No new model calls were made.');
});
$('recording-upload').onchange = ()=>action(async()=>{
  const file = $('recording-upload').files[0]; if (!file) return;
  if (file.size > 8_000_000) throw new Error('Recording must be under 8 MB');
  await api('/api/pilot/recordings',JSON.parse(await file.text()));
  $('recording-upload').value=''; await Promise.all([loadUsage(),loadRecordings(),loadSources()]); notice('Recording imported and validated.');
});
$('dismiss-token').onclick = ()=>{ $('token-value').value=''; $('token-panel').hidden=true; };
document.addEventListener('click', event=>{
  const button=event.target.closest('button'); if (!button) return;
  const d=button.dataset;
  if (d.resetFilters !== undefined) action(async()=>{$('filters').reset();filters='';taskPage=0;await loadUsage();});
  if (d.page || d.goto) navigate(d.page || d.goto);
  if (d.moreCalls !== undefined) action(()=>moreCalls(button));
  if (d.result) action(()=>showResult(d.result));
  if (d.cancel) action(async()=>{await api(`/api/pilot/evaluations/${d.cancel}/cancel`,{}); await loadJobs();});
  if (d.token) action(async()=>{const token=await api(`/api/pilot/sources/${d.token}/token`,{}); $('token-value').value=token.token; $('token-panel').hidden=false; await loadSources(); $('token-panel').scrollIntoView();});
  if (d.revoke && confirm('Revoke all tokens for this source? Its connectors will need a new token.')) action(async()=>{await api(`/api/pilot/sources/${d.revoke}/revoke`,{}); $('dismiss-token').click(); await loadSources();});
  if (d.revokeToken && confirm('Revoke this token? Other tokens for this source will keep working.')) action(async()=>{await api(`/api/pilot/sources/${d.source}/tokens/${d.revokeToken}/revoke`,{}); $('dismiss-token').click(); await loadSources();});
  if (d.retireCollector && confirm('Retire this collector? Check its host and undelivered outbox first.')) action(async()=>{await api(`/api/pilot/sources/${d.source}/collectors/${d.retireCollector}/retire`,{}); await loadSources();});
  if (d.disable && confirm('Disable this account and revoke its active sessions?')) action(async()=>{await api(`/api/pilot/users/${d.disable}/disable`,{}); await loadTeam();});
  if (d.exportProposal) download('routing-review.json',proposalRows.find(p=>p.id===d.exportProposal));
});
setInterval(()=>{ if (session && page==='evaluations' && !document.hidden) action(loadJobs); },3000);
setInterval(()=>{ if (session?.user && page==='usage' && !document.hidden) action(loadUsage); },10000);
setInterval(()=>{ if (session?.user && page==='operations' && !document.hidden) action(loadOperations); },15000);
setInterval(()=>{ if (session?.user && page==='sources' && !document.hidden) action(loadSources); },15000);
(async()=>{
  try {
    session=await api('/api/auth/session');
    loginMethods=session.login_methods;
    if (session.deployment === 'hosted_test') {
      $('company-login').textContent = 'Sign in to hosted test';
    }
    $('login-form').hidden=!loginMethods.local;
    $('company-login').hidden=!loginMethods.company;
    if (new URLSearchParams(location.search).get('signin')==='failed') {
      $('login-error').textContent = session.deployment === 'hosted_test' ?
        'Test sign-in failed. Check your test account access.' :
        'Company sign-in failed. Check your MFA method and account access with your administrator.';
      $('login-error').hidden=false;
      history.replaceState(null,'','/');
    }
    if (session.user) await enter();
    else $('setup-note').textContent = session.deployment === 'hosted_test' ?
      'Hosted test with SSO. Use your test account; MFA is not required.' :
      session.initialized ? 'Use the account your team administrator created.' :
      'An operator must initialize this team first. Follow the pilot setup instructions in docs/PILOT.md.';
  } catch(error) { $('setup-note').textContent='Workbench could not reach the team database. Check the pilot services.'; }
})();
