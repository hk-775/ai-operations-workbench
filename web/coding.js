/* Saved coding evidence only. No executable patch or provider request leaves this view. */
function createCoding({api, action, notice, getEpoch}) {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = value => value === null || value === undefined ? 'Unknown' : `$${esc(value)}`;
  const duration = value => value === null || value === undefined ? 'Unmeasured' : `${esc(value)} ms`;
  let report=null, sequence=0, taskPage=0, candidate='', outcome='all';
  function reset() {
    report=null;sequence++;$('coding-upload').value='';
    $('coding-result').innerHTML='<p class="notice">Load the demonstration or preview a result produced by the coding runner.</p>';
  }
  function render() {
    const r=report, fixture=r.mode==='fixture';
    taskPage=0;candidate='';outcome='all';
    $('coding-result').innerHTML=`
      <article class="panel screen-guide"><span class="tag ${fixture?'warn':'accent'}">${fixture?'AUTHORED MODEL EXAMPLE':'IMPORTED MODEL RECORDING'}</span>
      <h2>${fixture?'Real test execution. Authored candidate patches.':'Inspect the submitted coding evidence.'}</h2>
      <p>${fixture?'No model generated these patches. Model tokens, latency and API estimates are fictional teaching values; container test outcomes and test duration were measured.':'Model calls and patch history come from an operator-supplied recording. Checksums establish consistency, not independent authenticity.'}</p>
      <p class="fine">Hardware and electricity: unmeasured. Replay model API cost: $0. End-to-end agent duration is shown only when present in the original recording.</p>
      <label class="field">Required acceptance rate <select id="coding-threshold"><option value="100">100% · all tasks</option><option value="90">90%</option><option value="50">50% · exploratory</option></select></label>
      <p class="data-note">Inspect the frozen tasks, repeated runs and every recorded attempt. ${fixture?'Fixture evidence cannot justify a real model recommendation.':'Run a representative held-out workload and independent review before choosing a production model.'}</p>
      <div id="coding-gates"></div>
      <div class="table-wrap"><table><thead><tr><th>Candidate</th><th>Accepted patches</th><th>Attempts</th><th>All API estimates</th><th>API cost per accepted patch</th></tr></thead><tbody>${r.summary.map(s=>`<tr><td><strong>${esc(s.candidate)}</strong>${!s.complete_cases?'<small>Incomplete case coverage</small>':''}</td><td>${s.accepted}/${s.tasks}<small>${s.failed} failed tasks · ${s.regressions} regressions</small></td><td>${s.attempts}</td><td>${money(s.api_estimate_usd)}</td><td>${money(s.cost_per_accepted_patch_usd)}<small>Includes every attempt and failed task${fixture?' · fictional estimates':''}</small></td></tr>`).join('')}</tbody></table></div>
      <button class="button" id="coding-export">Download this result</button></article>
      <div class="section-head"><h2>Inspect the attempt history and final patch</h2></div>
      <div class="row-actions"><label class="field">Candidate<select id="coding-candidate"><option value="">All candidates</option>${r.summary.map(s=>`<option>${esc(s.candidate)}</option>`).join('')}</select></label>
      <label class="field">Patch outcome<select id="coding-outcome"><option value="all">All patches</option><option value="failed">Failed patches</option><option value="accepted">Accepted patches</option><option value="regression">Regressions</option></select></label></div>
      <p id="coding-task-count" class="fine" aria-live="polite"></p><div id="coding-tasks"></div>
      <div class="pagination"><button class="button" id="coding-previous">Previous patches</button><button class="button" id="coding-next">Next patches</button></div>
      <article class="panel"><h2>Evidence scope and limits</h2><p class="data-note">The limitations below were saved with this result. Workbench now supports Codex, Claude Code and Cursor usage connectors in Usage sources. Usage metadata alone does not establish code quality.</p><ul>${r.limitations.map(text=>`<li>${esc(text)}</li>`).join('')}</ul><p class="fine">Dataset ${esc(r.dataset_sha256)}<br>Result ${esc(r.sha256)}</p></article>`;
    const taskList=()=>{
      const rows=r.tasks.filter(t=>(!candidate || t.candidate===candidate) &&
        (outcome==='all' || (outcome==='failed'?!t.accepted:outcome==='accepted'?t.accepted:t.regression)));
      taskPage=Math.min(taskPage,Math.max(0,Math.ceil(rows.length/12)-1));
      $('coding-tasks').innerHTML=rows.length ? `${rows.slice(taskPage*12,(taskPage+1)*12).map(t=>`<article class="panel" data-flow="tasks"><div class="section-head"><div><h2>${esc(t.title)}</h2><p>${esc(t.candidate)} · repetition ${t.repetition}</p></div><span class="tag ${t.accepted?'good':'warn'}">${t.accepted?'Accepted':'Failed'}</span></div>
        <p>${t.public_tests} public tests and ${t.acceptance_tests} acceptance tests per attempt. Final patch ${t.regression?'introduces a regression':'has no detected regression'}.</p>
        <dl class="result-guide"><div><dt>All attempt API estimates</dt><dd>${money(t.api_estimate_usd)}</dd></div><div><dt>Measured replay test duration</dt><dd>${duration(t.test_duration_ms)}</dd></div><div><dt>Recorded end-to-end duration</dt><dd>${duration(t.observed_end_to_end_duration_ms)}</dd></div></dl>
        ${t.attempts.map((a,i)=>`<details class="help-details"><summary>Attempt ${a.number}${i===t.attempts.length-1?' · final patch':''} · ${a.passed?'passed':'failed'} · ${esc(a.execution_status)}</summary><p>Public tests: ${a.public_passed}/${t.public_tests}. Acceptance tests: ${a.acceptance_passed}/${t.acceptance_tests}. API estimate ${money(a.api_estimate_usd)}. Test duration ${duration(a.test_duration_ms)}.</p><pre>${esc(a.patch || '(No change from the broken snapshot)')}</pre><p class="fine">Source SHA-256: ${esc(a.source_sha256)}</p></details>`).join('')}
      </article>`).join('')}
` : '<p class="notice">No patches match these filters.</p>';
      $('coding-task-count').textContent=`${rows.length} matching patches · Page ${taskPage+1} of ${Math.max(1,Math.ceil(rows.length/12))}`;
      $('coding-previous').disabled=taskPage===0;$('coding-next').disabled=(taskPage+1)*12>=rows.length;
    };
    $('coding-candidate').onchange=e=>{candidate=e.target.value;taskPage=0;taskList();};
    $('coding-outcome').onchange=e=>{outcome=e.target.value;taskPage=0;taskList();};
    $('coding-previous').onclick=()=>{taskPage--;taskList();};
    $('coding-next').onclick=()=>{taskPage++;taskList();};
    taskList();
    const gates=()=>{
      const threshold=Number($('coding-threshold').value)/100;
      $('coding-gates').innerHTML=r.summary.map(s=>`<p><strong>${esc(s.candidate)}</strong>: ${s.complete_cases&&s.cost_complete&&s.accepted>0&&s.accepted/s.tasks>=threshold&&!s.regressions?'Meets these demonstration gates':'Excluded by acceptance, coverage, regression, or cost evidence'}</p>`).join('');
    };
    $('coding-threshold').onchange=gates;gates();
    $('coding-export').onclick=()=>{
      const url=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:'application/json'}));
      const link=document.createElement('a');link.href=url;link.download='coding-evaluation.json';link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
  }
  $('coding-example').onclick=()=>action(async()=>{
    const epoch=getEpoch(), token=++sequence;
    const value=await api('/api/pilot/coding/example');
    if(epoch!==getEpoch()||token!==sequence)return;
    report=value;render();
    notice('Loaded saved container test results. No patches or model calls were executed.');
  });
  $('coding-calibration').onclick=()=>action(async()=>{
    const epoch=getEpoch(), token=++sequence;
    const value=await api('/api/pilot/coding/calibration');
    if(epoch!==getEpoch()||token!==sequence)return;
    report=value;render();
    notice('Loaded the recorded 18-task comparison. Viewing it makes no model calls and does not change company usage.');
  });
  $('coding-upload').onchange=()=>action(async()=>{
    const file=$('coding-upload').files[0];if(!file)return;
    const epoch=getEpoch(), token=++sequence;
    if(file.size>8_000_000)throw new Error('Coding result must be under 8 MB');
    const value=await api('/api/pilot/coding/preview',JSON.parse(await file.text()));
    if(epoch!==getEpoch()||token!==sequence)return;
    report=value;render();$('coding-upload').value='';
    notice('Integrity and accounting checked. This preview is not saved; executor claims are supplied by the file.');
  });
  $('coding-choose-file').onclick=()=>$('coding-upload').click();
  $('coding-clear').onclick=reset;
  return {reset};
}
