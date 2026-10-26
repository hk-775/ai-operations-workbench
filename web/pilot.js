const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const amount = value => value === null || value === undefined ? 'Unknown' : `$${value}`;
const date = value => value ? new Date(value * 1000).toLocaleString() : 'Not received';
const badge = (text, kind='accent') => `<span class="tag ${kind}">${escape(text)}</span>`;
let session, page = 'usage', usage, jobRows = [], proposalRows = [], filters = '';
let generation = 0;
let taskPage = 0, loginMethods = {local:true,company:false}, usageRequest = 0;
const canEdit = () => session?.user && session.user.role !== 'viewer';
const isAdmin = () => session?.user?.role === 'admin';

async function api(path, body) {
  const epoch = generation;
  const response = await fetch(path, {credentials:'same-origin', cache:'no-store',
    ...(body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json', 'X-Workbench-CSRF':session?.csrf || ''}, body:JSON.stringify(body)})});
  const value = await response.json();
  if (epoch !== generation) throw new Error('Session changed. Retry after signing in.');
  if (!response.ok) {
    if (response.status === 401 && !path.endsWith('/login')) showLogin();
    throw new Error(value.detail || `Request failed (${response.status})`);
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
  usage = null; jobRows = []; proposalRows = [];
  for (const id of ['metrics','task-list','sources','jobs','evaluation-result','proposals','users','audit',
                    'recording-select','proposal-job','evidence-counts','cost-note',
                    'operations-metrics','operations-alerts','operations-retention']) $(id).replaceChildren();
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
  $('page-label').textContent = document.querySelector(`[data-page="${page}"]`).textContent;
  document.querySelector('.content').scrollTo({top:0,behavior:'instant'});
  window.scrollTo({top:0,behavior:'instant'});
  if (page === 'proposals') action(loadProposals);
  if (page === 'team') action(loadTeam);
  if (page === 'operations') action(loadOperations);
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
async function loadUsage() {
  const epoch = generation;
  const request = ++usageRequest;
  const params = new URLSearchParams(filters);
  params.set('page',String(taskPage));
  const result = await api(`/api/pilot/usage?${params}`);
  if (epoch !== generation || request !== usageRequest) return;
  usage = result;
  $('metrics').innerHTML = metric('Captured API subtotal', amount(usage.api_estimate_usd), 'Published-rate estimate · USD','connect') +
    metric('Captured tasks', usage.task_count, `${usage.events} call events`,'tasks') +
    metric('Unknown call costs', usage.unknown_cost_calls, 'Missing usage or reviewed pricing','compare') +
    metric('Calls with coverage gaps', usage.uncovered_attempt_calls, 'Costs or attempt coverage incomplete','proposal');
  $('cost-note').textContent = usage.cost_note;
  $('evidence-counts').textContent = Object.entries(usage.evidence_counts).map(([k,v])=>`${k}: ${v} calls`).join(' · ') || 'No events yet. Create a source or load the recorded comparison.';
  const tasks = usage.tasks;
  $('task-list').innerHTML = tasks.map((task,index) => `<details class="panel task-card">
    <summary><strong>${escape(task.calls[0]?.case_id ? `${task.calls[0].case_id} · ${task.calls[0].model}` : task.task_id)}</strong><span>${escape(amount(task.api_estimate_usd))} · ${task.call_count} calls</span></summary>
    <p class="data-note">${escape(task.project)} · ${task.unknown_cost_calls} unknown costs · ${task.uncovered_attempt_calls} coverage gaps</p>
    <div class="table-wrap"><table><thead><tr><th>Stage / evidence</th><th>Provider / model</th><th>API estimate</th><th>Usage &amp; coverage</th><th>Latency</th></tr></thead><tbody>${task.calls.map(c=>`<tr>
      <td>${escape(c.stage)}<br>${badge(c.evidence)} ${badge(c.status,c.status==='success'?'good':'warn')}</td>
      <td>${escape(c.provider)}<br>${escape(c.model)}</td><td>${escape(amount(c.api_estimate_usd))}<br><small>${escape(c.unknown_reason || `Rate card ${c.pricebook_id.slice(0,12)}`)}</small></td>
      <td>${escape(c.usage_basis)}<br>${escape(c.attempt_coverage)}<br><small>${c.usage ? `${c.usage.prompt_tokens} input / ${c.usage.completion_tokens} output / ${c.usage.cached_tokens} cached` : 'Tokens unknown'}</small></td>
      <td>${escape(c.latency_ms)} ms</td></tr>`).join('')}</tbody></table></div>
      ${task.calls_has_more?`<button class="button" data-more-calls="${index}">Load more calls</button>`:''}</details>`).join('') ||
      '<article class="panel"><h2>No tasks in this view yet.</h2><p class="data-note">Connect an AxonLLM source or load the recorded example from Model evaluations.</p></article>';
  $('tasks-page').textContent = usage.task_count ? `Page ${usage.page+1} · ${usage.task_count} tasks · most expensive first` : 'No tasks';
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
    button.closest('details').querySelector('tbody').insertAdjacentHTML('beforeend', result.calls.map(c=>`<tr><td>${escape(c.stage)}<br>${badge(c.evidence)} ${badge(c.status,c.status==='success'?'good':'warn')}</td><td>${escape(c.provider)}<br>${escape(c.model)}</td><td>${escape(amount(c.api_estimate_usd))}<br><small>${escape(c.unknown_reason || `Rate card ${c.pricebook_id.slice(0,12)}`)}</small></td><td>${escape(c.usage_basis)}<br>${escape(c.attempt_coverage)}<br><small>${c.usage?`${c.usage.prompt_tokens} input / ${c.usage.completion_tokens} output / ${c.usage.cached_tokens} cached`:'Tokens unknown'}</small></td><td>${escape(c.latency_ms)} ms</td></tr>`).join(''));
    button.hidden = !result.has_more;
  } finally { button.disabled=false; }
}
async function loadSources() {
  const result = await api('/api/pilot/sources');
  const selected = $('source-filter').value;
  $('source-filter').innerHTML = '<option value="">All sources</option>' + result.sources.map(s=>`<option value="${escape(s.id)}">${escape(s.name)}</option>`).join('');
  $('source-filter').value = selected;
  $('sources').innerHTML = result.sources.map(s=>`<article class="panel source-row"><div><h2>${escape(s.name)}</h2>
    <p class="fine">${escape(s.kind)} · ${s.event_count} events · Last received: ${escape(date(s.last_received_at))}</p>
    <div class="fine">${s.tokens.map(t=>`<p>${escape(t.prefix)}… · ${t.revoked?'revoked':`expires ${escape(date(t.expires_at))}`}
      ${isAdmin()&&!t.revoked?`<button class="button small" data-revoke-token="${t.id}" data-source="${s.id}">Revoke token ${escape(t.prefix)}</button>`:''}</p>`).join('')}</div></div>
    ${isAdmin() && s.kind==='axonllm' ? `<div class="row-actions"><button class="button soft" data-token="${s.id}">Issue token</button><button class="button" data-revoke="${s.id}">Revoke all tokens</button></div>` : ''}</article>`).join('') ||
      '<p class="notice">No sources connected yet. An administrator can create the first AxonLLM source.</p>';
}
async function loadRecordings() {
  const result = await api('/api/pilot/recordings');
  const selected = $('recording-select').value;
  $('recording-select').innerHTML = result.recordings.map(r=>`<option value="${r.id}">${r.id.slice(0,16)} · ${escape(date(r.created_at))}</option>`).join('');
  if (result.recordings.some(r=>r.id===selected)) $('recording-select').value = selected;
}
async function loadJobs() {
  const epoch = generation;
  const result = await api('/api/pilot/evaluations');
  if (epoch !== generation) return;
  jobRows = result.evaluations;
  $('worker-status').textContent = result.worker_healthy ? 'Worker connected' : 'Worker unavailable';
  $('worker-status').className = `tag ${result.worker_healthy?'good':'warn'}`;
  $('jobs').innerHTML = jobRows.map(j=>`<article class="panel job-row"><div><strong>${escape(j.id.slice(0,8))}</strong> ${badge(j.status,j.status==='complete'?'good':j.status==='failed'?'danger':'accent')}
    <p class="fine">Recording ${j.recording_id.slice(0,12)} · attempts ${j.attempts} · ${escape(date(j.created_at))}</p>${j.error?`<p class="data-note">${escape(j.error)}</p>`:''}</div><div class="row-actions">
    ${j.status==='complete'?`<button class="button soft" data-result="${j.id}">Inspect results</button>`:''}
    ${canEdit() && ['queued','running'].includes(j.status)?`<button class="button" data-cancel="${j.id}">Cancel</button>`:''}</div></article>`).join('') || '<p class="notice">No evaluations queued yet.</p>';
  const selected = $('proposal-job').value;
  $('proposal-job').innerHTML = jobRows.filter(j=>j.status==='complete').map(j=>`<option value="${j.id}">${j.id.slice(0,8)} · recording ${j.recording_id.slice(0,12)}</option>`).join('');
  if (jobRows.some(j=>j.id===selected && j.status==='complete')) $('proposal-job').value = selected;
}
async function showResult(id) {
  const job = await api(`/api/pilot/evaluations/${id}`);
  const result = job.analysis;
  $('evaluation-result').innerHTML = `<article class="panel"><div class="section-head"><div><h2>Evaluation ${id.slice(0,8)}</h2><p>${result.total_calls} saved calls · ${escape(amount(result.total_cost_usd))} · ${escape(result.mode)} evidence</p></div><button class="button soft" id="export-result">Export results</button></div>
    <div class="table-wrap"><table><thead><tr><th>Model</th><th>Passed</th><th>Critical failures</th><th>p95</th><th>Cost per passing task</th></tr></thead><tbody>${result.models.map(m=>`<tr><td>${escape(m.model)}</td><td>${m.passed}/${m.evaluated}</td><td>${m.critical_failures}</td><td>${escape(m.p95_ms)} ms</td><td>${escape(amount(m.cost_per_pass_usd))}</td></tr>`).join('')}</tbody></table></div><p class="data-note">Saved-output replay, not a new model measurement. Review the individual checks in the exported result.</p><button class="button primary" data-goto="proposals">Review routing criteria</button></article>`;
  $('export-result').onclick = () => download(`evaluation-${id}.json`, job);
  $('evaluation-result').scrollIntoView({block:'start'});
}
async function loadProposals() {
  const result = await api('/api/pilot/proposals');
  proposalRows = result.proposals;
  $('proposals').innerHTML = proposalRows.map(p=>`<article class="panel"><div class="section-head"><div><p class="eyebrow">SAVED ROUTING REVIEW</p><h2>${p.recommended_model?escape(p.recommended_model):p.status==='fixture_only'?'Fixture evidence only':'No model qualifies'}</h2></div>${badge('Not applied','warn')}</div>
    <p class="data-note">${escape(p.scope)}</p><p class="proposal-copy">Minimum pass rate: ${p.min_pass_rate*100}% · Zero critical failures · p95 ≤ ${p.max_p95_ms} ms · ${p.monthly_tasks} monthly tasks assumed</p>
    <div class="table-wrap"><table><thead><tr><th>Candidate</th><th>Decision</th><th>Reasons</th></tr></thead><tbody>${p.candidates.map(c=>`<tr><td>${escape(c.model)}</td><td>${badge(c.eligible?'Eligible':'Excluded',c.eligible?'good':'warn')}</td><td>${escape(c.exclusions.join('; ') || 'Meets the selected checks')}</td></tr>`).join('')}</tbody></table></div>
    <p class="proposal-copy">Projected monthly API savings: ${escape(amount(p.projected_monthly_api_savings_usd))}</p><ul class="limitations">${p.limitations.map(l=>`<li>${escape(l)}</li>`).join('')}</ul>
    <p class="fine">Recording ${p.recording_id.slice(0,16)} · evaluator ${p.evaluation_revision.slice(0,16)}</p><button class="button soft" data-export-proposal="${p.id}">Export routing review</button></article>`).join('') || '<p class="notice">Complete an evaluation, then save a review using the criteria above.</p>';
}
async function loadTeam() {
  const [members, audit] = await Promise.all([api('/api/pilot/users'), api('/api/pilot/audit')]);
  $('users').innerHTML = members.users.map(u=>`<article class="panel user-row"><div><strong>${escape(u.username)}</strong> ${badge(u.role)} ${!u.active?badge('Disabled','warn'):''}</div>${u.active?`<button class="button" data-disable="${u.id}">Disable account</button>`:''}</article>`).join('');
  $('audit').innerHTML = `<table><thead><tr><th>When</th><th>Actor</th><th>Action</th></tr></thead><tbody>${audit.events.map(e=>`<tr><td>${escape(date(e.created_at))}</td><td>${escape(e.actor)}</td><td>${escape(e.action)}</td></tr>`).join('')}</tbody></table>`;
}
async function loadOperations() {
  const state = await api('/api/pilot/operations');
  $('operations-status').textContent = state.status === 'healthy' ? 'Services healthy' : 'Needs attention';
  $('operations-status').className = `tag ${state.status === 'healthy'?'good':'warn'}`;
  $('operations-metrics').innerHTML = metric('Evaluation worker',state.worker_healthy?'Connected':'Unavailable','Checked against persisted heartbeat','connect') +
    metric('Waiting evaluations',state.jobs.queued || 0,`Oldest wait: ${state.oldest_queued_seconds} seconds`,'tasks') +
    metric('Failed evaluations',state.failed_jobs_24h,'Last 24 hours','compare') +
    metric('Unknown call costs',state.unknown_cost_calls_24h,`${state.observed_calls_24h} observed calls in 24 hours`,'proposal');
  $('operations-alerts').innerHTML = state.alerts.length ? state.alerts.map(a=>`<p class="data-note">${badge(a.severity,a.severity==='critical'?'warn':'accent')} ${escape(a.message)}</p>`).join('') : '<p class="data-note">No active operational alerts.</p>';
  $('operations-retention').textContent = `${state.retention_days ? `Usage metadata: ${state.retention_days} days. Evidence and saved reviews: ${state.evidence_retention_days || 'unlimited'} days. Audit history: ${state.audit_retention_days || 'unlimited'} days.` : 'Scheduled data retention is not enabled in this local environment.'} ${state.maintenance_age_seconds===null?'Maintenance has not run yet.':`Last maintenance completed ${Math.floor(state.maintenance_age_seconds/60)} minutes ago.`}`;
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
submit('source-form', async data=>{await api('/api/pilot/sources',{name:data.get('name')}); $('source-form').reset(); await loadSources(); notice('Source created. Issue a token to connect the application.');});
submit('evaluate-form', async()=>{await api('/api/pilot/evaluations',{recording_id:$('recording-select').value}); await loadJobs(); notice('Evaluation queued. You can leave this page; the worker will save its result.');});
submit('proposal-form', async data=>{
  await api(`/api/pilot/evaluations/${$('proposal-job').value}/recommend`,{min_pass_rate:Number(data.get('pass'))/100,max_p95_ms:Number(data.get('latency')),monthly_tasks:Number(data.get('volume'))});
  await loadProposals(); notice('Routing review saved. No route was changed.');
});
submit('user-form', async data=>{await api('/api/pilot/users',Object.fromEntries(data)); $('user-form').reset(); await loadTeam(); notice('Team member added.');});
submit('identity-form', async data=>{await api('/api/pilot/identities',Object.fromEntries(data)); $('identity-form').reset(); await loadTeam(); notice('Company member added.');});
$('load-example').onclick = ()=>action(async()=>{
  await api('/api/pilot/recordings/example',{}); await Promise.all([loadUsage(),loadRecordings(),loadSources()]);
  notice('Loaded the saved comparison. These are recorded model calls on authored tickets, not new traffic.');
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
  if (d.page || d.goto) navigate(d.page || d.goto);
  if (d.moreCalls !== undefined) action(()=>moreCalls(button));
  if (d.result) action(()=>showResult(d.result));
  if (d.cancel) action(async()=>{await api(`/api/pilot/evaluations/${d.cancel}/cancel`,{}); await loadJobs();});
  if (d.token) action(async()=>{const token=await api(`/api/pilot/sources/${d.token}/token`,{}); $('token-value').value=token.token; $('token-panel').hidden=false; await loadSources(); $('token-panel').scrollIntoView();});
  if (d.revoke && confirm('Revoke all tokens for this source? Its connectors will need a new token.')) action(async()=>{await api(`/api/pilot/sources/${d.revoke}/revoke`,{}); $('dismiss-token').click(); await loadSources();});
  if (d.revokeToken && confirm('Revoke this token? Other tokens for this source will keep working.')) action(async()=>{await api(`/api/pilot/sources/${d.source}/tokens/${d.revokeToken}/revoke`,{}); $('dismiss-token').click(); await loadSources();});
  if (d.disable && confirm('Disable this account and revoke its active sessions?')) action(async()=>{await api(`/api/pilot/users/${d.disable}/disable`,{}); await loadTeam();});
  if (d.exportProposal) download('routing-review.json',proposalRows.find(p=>p.id===d.exportProposal));
});
setInterval(()=>{ if (session && page==='evaluations' && !document.hidden) action(loadJobs); },3000);
setInterval(()=>{ if (session?.user && page==='usage' && !document.hidden) action(loadUsage); },10000);
setInterval(()=>{ if (session?.user && page==='operations' && !document.hidden) action(loadOperations); },15000);
(async()=>{
  try {
    session=await api('/api/auth/session');
    loginMethods=session.login_methods;
    $('login-form').hidden=!loginMethods.local;
    $('company-login').hidden=!loginMethods.company;
    if (new URLSearchParams(location.search).get('signin')==='failed') {
      $('login-error').textContent='Company sign-in failed. Check your MFA method and account access with your administrator.';
      $('login-error').hidden=false;
      history.replaceState(null,'','/');
    }
    if (session.user) await enter();
    else $('setup-note').textContent = session.initialized ? 'Use the account your team administrator created.' :
      'An operator must initialize this team first. Follow the pilot setup instructions in docs/PILOT.md.';
  } catch(error) { $('setup-note').textContent='Workbench could not reach the team database. Check the pilot services.'; }
})();
