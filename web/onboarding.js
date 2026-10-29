function createOnboarding({api,action,notice,getEpoch,download}) {
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels={ready:'Ready',needed:'Needed',waiting:'Waiting',received:'Received',connected:'Heartbeat current',unmonitored:'No heartbeat',token_required:'Active token needed',stale:'Heartbeat stale',backlog:'Delivery backlog'};
  let source=null,report=null,sequence=0;
  async function refresh() {
    if(!source)return;
    const epoch=getEpoch(),current=++sequence;
    const value=await api(`/api/pilot/sources/${encodeURIComponent(source)}/setup?project=${encodeURIComponent($('onboarding-project').value||'engineering')}`);
    if(epoch!==getEpoch()||current!==sequence)return;
    report=value;$('onboarding-panel').hidden=false;$('onboarding-title').textContent=value.source.name;
    $('onboarding-steps').innerHTML=`<div class="workflow-step-list">${value.steps.map(step=>`<div><h3>${esc(step.name)}</h3><span class="tag ${['ready','received','connected'].includes(step.state)?'good':'warn'}">${esc(labels[step.state]||step.state)}</span><p class="fine">${esc(step.detail)}</p></div>`).join('')}</div>`;
    $('onboarding-limit').textContent=value.limitation;
    $('onboarding-commands').innerHTML=(value.application_guide?`<div class="workflow-rule"><h3>Instrument your existing application</h3><p class="data-note">Add the capture wrapper described in ${esc(value.application_guide)} in your checkout. Use project ${esc(value.project)} and outbox ${esc(value.outbox)} for capture and delivery.</p></div>`:'')+
      value.commands.map((item,index)=>`<div class="workflow-rule"><h3>${esc(item.title)}</h3><p class="data-note">${esc(item.description)}</p><pre class="workflow-code">${esc(item.command)}</pre><button class="button small" data-setup-copy="${index}">Copy command</button></div>`).join('');
  }
  async function open(identity) {
    source=identity;await refresh();$('onboarding-panel').scrollIntoView({block:'start'});
  }
  $('onboarding-refresh').onclick=()=>action(refresh);
  $('onboarding-project').onchange=()=>action(refresh);
  $('onboarding-close').onclick=()=>{$('onboarding-panel').hidden=true;};
  $('onboarding-download').onclick=()=>{if(report)download('workbench-connection-setup.json',report);};
  $('onboarding-panel').addEventListener('click',event=>{
    const button=event.target.closest('[data-setup-copy]');if(!button||!report)return;
    action(async()=>{await navigator.clipboard.writeText(report.commands[Number(button.dataset.setupCopy)].command);notice('Command copied. Run it in your Workbench checkout on the collector host.');});
  });
  function reset() {
    sequence++;source=null;report=null;$('onboarding-panel').hidden=true;$('onboarding-project').value='engineering';
    for(const id of ['onboarding-title','onboarding-steps','onboarding-limit','onboarding-commands'])$(id).replaceChildren();
  }
  return {open,refresh,reset};
}
