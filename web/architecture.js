'use strict';
// Authored architecture and bundled media. No API/cloud requests, credentials, or live traffic.
const colors = {
  sky:['#f0f9ff','#bae6fd','#0284c7'], yellow:['#fefce8','#fef08a','#a16207'],
  violet:['#f5f3ff','#ddd6fe','#7c3aed'], teal:['#f0fdfa','#99f6e4','#0f766e'],
};
const node = (id,title,subtitle,x,y,color,owner,copy,data,proof,boundary,w=250,h=100) =>
  ({id,title,subtitle,x,y,color,owner,copy,data,proof,boundary,w,h});
const edge = (from,to,path) => ({from,to,path});
const product = {
  title:'One task. Two kinds of evidence.', scope:'Implemented team workspace',
  limitTitle:'A model recommendation needs usage and answer quality.',
  limitCopy:'Application ingestion accepts usage metadata. Quality checks require separately validated support-v1 recordings. The evaluator replays saved answers; it makes no new model API calls. A saved routing review does not activate a model route. Costs are rate-card estimates, with missing costs kept unknown and hardware/electricity unmeasured.',
  nodes:[
    node('app','Application + AxonLLM','Captured model-call metadata',40,70,'sky','YOUR APPLICATION',
      'Your application uses AxonLLM to call a model. The Workbench connector keeps captured usage in a durable outbox and retries unacknowledged deliveries.',
      'Task and event IDs, model, tokens, timing, status, and capture coverage. Prompt and answer text stay outside this metadata feed.',
      'Which calls were captured and which task they belong to.',
      'A successful API response is not proof that the model answered correctly. Final-response capture can miss attempts.'),
    node('ingest','Scoped ingestion API','Source token + team boundary',365,70,'sky','WORKBENCH API',
      'An application source sends a batch with its scoped bearer token. Workbench derives the team and source from the token.',
      'Validated metadata events and immutable pricebook references.',
      'Repeated events are acknowledged. Conflicting payloads roll back the batch.',
      'Reported token usage and provider response IDs are not authenticated provider invoices.'),
    node('ledger','PostgreSQL ledger','Usage, evidence, and job state',690,70,'yellow','WORKBENCH DATABASE',
      'The ledger keeps events, historical price facts, recordings, queued jobs, results, and saved reviews in team scope. Version 0.5.0 adds imported Bedrock billing snapshots and declared comparison scopes.',
      'Known API estimates and imported charges as separate precise decimal amounts; unknown usage remains unknown.',
      'A durable cost trail and reproducible links from a review to its input evidence.',
      'Billing reconciliation uses administrator-supplied CSV and declared group mappings. It does not authenticate invoices or allocate them to tasks. Automated billing feeds remain future work.'),
    node('recording','Saved support answers','Validated support-v1 recording',40,280,'yellow','EXPLICIT EVIDENCE IMPORT',
      'An analyst imports compatible saved model answers or loads the bundled recorded comparison of 24 fictional subscription-support tickets and three models.',
      'Case corpus, policy, prompts, model responses, usage, timings, and price basis.',
      'Internal consistency and compatibility with the implemented support evaluator.',
      'Application usage alone cannot be used to infer answer quality or attach a fictional customer description.'),
    node('worker','Evaluation worker','Leased offline replay',365,280,'violet','WORKBENCH WORKER',
      'A supervised worker claims a persisted job, replays the saved recording, and stores its result. The work continues after the browser closes.',
      'Validated recording, job lease, evaluator revision, and bounded execution time.',
      'Durable evaluation progress with lease recovery and stale-worker fencing.',
      'Replay grades saved responses. It does not measure current model behavior or fresh inference latency.'),
    node('checks','Contract + Ostiari Guard','Decision and action checks',690,280,'violet','WORKBENCH + OSTIARI GUARD',
      'Deterministic contract checks grade support decisions. The real Ostiari Guard package verifies the configured action boundaries during replay.',
      'Saved decisions, policy facts, proposed actions, and expected outcomes.',
      'Per-ticket passes, critical-case failures, and evidence explaining each result.',
      'This embeds Ostiari Guard, not its entire gateway, billing, identity, or approvals platform.'),
    node('dashboard','Team dashboard','Inspect, compare, and export',40,500,'sky','AUTHORIZED TEAM MEMBER',
      'An administrator, analyst, or viewer sees the views permitted by their role. Task Explorer connects a recorded request to its captured call costs.',
      'Cost coverage, saved evaluation results, routing reviews, and portable evidence.',
      'A person can inspect the reasons and limitations behind a model choice.',
      'No button activates routing. Company adoption and deployment remain a separate process.'),
    node('review','Routing review','Apply explicit requirements',365,500,'teal','WORKBENCH RECOMMENDATION',
      'The review checks minimum pass rate, zero critical failures, and a response-time bound before comparing eligible candidates.',
      'A completed evaluation, selected constraints, and an assumed monthly volume.',
      'A justified candidate or an explicit “No model qualifies” result.',
      'Projected savings require complete comparison costs and a qualifying model; they are not guaranteed savings.'),
    node('results','Saved evaluation results','Provenance + individual checks',690,500,'violet','WORKBENCH EVIDENCE STORE',
      'Evaluation results are persisted in PostgreSQL with the original recording and evaluator revision, then returned through the team API.',
      'Pass counts, critical failures, captured timing, cost per passing ticket, and provenance.',
      'A review remains tied to the exact saved evidence and grading revision.',
      'These results cover the authored support workload. They are not a general ranking of model intelligence.'),
  ],
  edges:[
    edge('app','ingest','M290 120 H365'),edge('ingest','ledger','M615 120 H690'),
    edge('recording','ledger','M290 330 H325 V215 H815 V170'),
    edge('ledger','worker','M760 170 V235 H490 V280'),
    edge('worker','checks','M615 330 H690'),
    edge('checks','results','M815 380 V500'),
    edge('results','review','M690 550 H615'),
    edge('review','dashboard','M365 550 H290'),
  ],
  flows:[
    {name:'Capture usage',color:'sky',steps:['app','ingest','ledger']},
    {name:'Evaluate answers',color:'violet',steps:['recording','ledger','worker','checks','results']},
    {name:'Review model choice',color:'teal',steps:['results','review','dashboard']},
  ],
};
const aws = {
  title:'Two workspaces. One test host.', scope:'Implemented optional AWS acceptance',
  limitTitle:'This diagram describes the hosted test that was exercised.',
  limitCopy:'The deployment is a single EC2 host with separate seeded and clean stacks. MFA is disabled only in the explicit hosted-test profile; the standard production profile retains its MFA requirement. HTTPS ends at CloudFront; private VPC and container hops use HTTP. Alarm delivery was tested to a private queue. Human on-call delivery, high availability, rebuilt-host recovery, and workload capacity remain outside this acceptance result.',
  groups:[{x:20,y:200,w:630,h:490,title:'Amazon EC2 · encrypted EBS · host role · no SSH ingress'}],
  nodes:[
    node('browser','User browser','Separate HTTPS origins',40,65,'sky','TEAM ACCESS',
      'Each workspace has its own HTTPS origin and browser cookie namespace.',
      'Browser requests and the authorization-code sign-in flow.',
      'A demo sign-in does not create an authenticated clean-workspace session.',
      'This is an architecture illustration; it does not connect to the deployed workspaces.'),
    node('edge','CloudFront + AWS WAF','HTTPS + private VPC origin',365,65,'sky','AWS EDGE',
      'Two CloudFront distributions provide HTTPS, disable caching, and forward to the private VPC origin. AWS WAF applies an IP request-rate limit.',
      'Authenticated requests, required cookies, and OIDC callback parameters.',
      'The origin accepts the CloudFront network; no inbound SSH rule is configured.',
      'TLS terminates here. Private origin and Docker hops use HTTP.'),
    node('identity','Amazon Cognito','Two confidential OIDC clients',690,65,'violet','TEST IDENTITY PROVIDER',
      'Administrator-created test users sign in through a dedicated Cognito user pool. Each workspace has its own authorization-code client.',
      'PKCE-bound sign-in and exact issuer/subject identity mapping to Workbench roles.',
      'Real provider sign-in and isolated application sessions.',
      'Password-only SSO is an explicit test exception. This is not production MFA verification.'),
    node('proxy','Caddy origin proxy','Routes each workspace hostname',365,265,'sky','INSIDE THE EC2 HOST',
      'Caddy accepts the private origin request and routes its hostname to the appropriate loopback application listener.',
      'Requests for either the seeded demo or clean installation.',
      'Each origin reaches its own application and cookie namespace.',
      'Both stacks share one host; this is not host-level isolation or high availability.'),
    node('demo','Seeded workspace','API + workers + PostgreSQL',50,435,'yellow','INDEPENDENT DEMO STACK',
      'The demo has a separate API, evaluation worker, maintenance process, and PostgreSQL database. Explicit seeding loads the recorded support comparison.',
      '144 saved call events, 72 model/task runs, one evaluation, and one saved review at acceptance.',
      'A complete usage-to-review journey can be explored without new model calls.',
      'The tickets are fictional and the responses are saved. This is not current company traffic.'),
    node('clean','Clean workspace','API + workers + PostgreSQL',365,435,'violet','INDEPENDENT CLEAN STACK',
      'The clean stack has its own database, credentials, Cognito client, host origin, and browser cookies. It imports no example evidence.',
      'Only explicitly connected application metadata and uploaded evidence after installation.',
      'A new company can start with an empty workspace.',
      'The shared EC2 host remains a common failure boundary.'),
    node('backup','Amazon S3 backups','Encrypted + private + versioned',690,265,'teal','OFF-HOST RECOVERY STORAGE',
      'The backup timer uploads private database dumps and checksum receipts. Acceptance downloaded and restored both backups into temporary databases.',
      'Encrypted PostgreSQL dumps with metadata and SHA-256 receipts.',
      'The scheduled backup can be retrieved and checked through a real restore.',
      'Backups expire after 30 days. The small restores on this host do not prove rebuilt-host recovery.'),
    node('monitor','Amazon CloudWatch','Readiness and backup-age alarms',690,435,'violet','FOUR CLOUDWATCH ALARMS',
      'Host monitoring requests each public readiness endpoint and checks the age of its latest off-host backup. Missing metric samples also alarm.',
      'One readiness signal and one backup-age signal per workspace.',
      'The controlled demo-worker outage produced an alarm and a later recovery notification.',
      'Metrics and alarms need a response process to be operationally useful.'),
    node('timers','Host timers','Daily backup · minutely monitoring',50,595,'teal','SYSTEMD ON THE HOST',
      'Protected systemd jobs run as the host account with a dedicated Docker client configuration. The instance role provides temporary AWS access.',
      'Database backup jobs, external readiness checks, and backup freshness.',
      'Backups and monitoring were exercised through the actual scheduled jobs.',
      'Stopping the single host suspends both applications and their backup jobs.',565,70),
    node('alerts','Amazon SNS → SQS','Encrypted topic + private queue',690,595,'teal','ALARM DELIVERY RECEIPTS',
      'CloudWatch publishes alarm and recovery events to an SNS topic encrypted with AWS KMS. A private encrypted SQS queue receives test receipts.',
      'Machine-readable alarm and recovery notifications.',
      'Actual delivery was matched to the controlled outage and recovery.',
      'No person receives these test notifications. Human on-call delivery remains an operator choice.',250,90),
  ],
  edges:[
    edge('browser','edge','M290 115 H365'),
    edge('browser','identity','M165 65 V35 H815 V65'),
    edge('identity','browser','M690 145 H665 V185 H165 V165'),
    edge('edge','proxy','M615 115 H635 V315 H615'),
    edge('proxy','demo','M430 365 V400 H175 V435'),
    edge('proxy','clean','M540 365 V435'),
    edge('demo','timers','M175 535 V595'),
    edge('clean','timers','M490 535 V595'),
    edge('timers','backup','M615 630 H666 V315 H690'),
    edge('timers','monitor','M615 650 H676 V485 H690'),
    edge('monitor','alerts','M815 535 V595'),
  ],
  flows:[
    {name:'Open seeded workspace',color:'sky',steps:['browser','edge','proxy','demo']},
    {name:'Sign in',color:'violet',steps:['browser','identity','browser','edge','proxy','clean']},
    {name:'Back up data',color:'teal',steps:['demo','timers','backup']},
    {name:'Detect an outage',color:'violet',steps:['timers','monitor','alerts']},
  ],
};
const $ = id => document.getElementById(id);
const NS='http://www.w3.org/2000/svg';
function svg(tag,attributes={},text) {
  const element=document.createElementNS(NS,tag);
  for(const [key,value] of Object.entries(attributes)) element.setAttribute(key,String(value));
  if(text!==undefined) element.textContent=text;
  return element;
}
let view=product,flowIndex=0,stepIndex=0,selected='',paths=[],markers=[],frame=0,elapsed=0,last=null;
let paused=false;
const preference=matchMedia('(prefers-reduced-motion: reduce)');
let tourState='idle',narrationEnabled=true,clip=null,clipKey='',tourToken=0,silentTimer=null;
try { narrationEnabled=localStorage.getItem('workbench-architecture-narration')!=='off'; } catch {}
function clipInfo() {
  const key=(view===aws?'aws-':'product-')+selected;
  return {key,...(window.WorkbenchNarration?.[key]||{})};
}
function updateTour() {
  $('play-flow').textContent={idle:'Play flow',playing:'Pause flow',paused:'Resume flow',complete:'Replay flow'}[tourState];
  $('narration-toggle').textContent=narrationEnabled?'Narration on':'Narration off';
  $('narration-toggle').setAttribute('aria-pressed',String(narrationEnabled));
}
function cancelClip(discard=true) {
  tourToken++;
  clearTimeout(silentTimer);silentTimer=null;
  if(clip) {
    clip.onended=null;clip.onerror=null;clip.pause();
    if(discard) { clip.removeAttribute('src');clip.load();clip=null;clipKey=''; }
  }
}
function stopTour() {
  cancelClip();tourState='idle';updateTour();$('tour-status').textContent='Ready to play';
}
function playStep(resume=false) {
  cancelClip(!resume);
  const token=tourToken;
  const info=clipInfo();
  const finish=()=>{
    if(token!==tourToken||tourState!=='playing') return;
    if(stepIndex>=view.flows[flowIndex].steps.length-1) {
      cancelClip();tourState='complete';updateTour();$('tour-status').textContent='Flow complete';
    } else {
      stepIndex++;walkthrough();playStep();
    }
  };
  if(!narrationEnabled||!info.src) {
    $('tour-status').textContent=narrationEnabled?'Audio unavailable · reading mode':'Playing without narration';
    silentTimer=setTimeout(finish,5000);return;
  }
  if(!clip||clipKey!==info.key) {
    clip=new Audio(new URL(info.src,document.baseURI).href);
    clipKey=info.key;
  }
  const fallback=()=>{
    if(token!==tourToken||tourState!=='playing') return;
    clearTimeout(silentTimer);
    $('tour-status').textContent='Audio unavailable · continuing with text';
    silentTimer=setTimeout(finish,5000);
  };
  clip.onended=finish;clip.onerror=fallback;
  $('tour-status').textContent='Narrating · '+view.nodes.find(n=>n.id===selected).title;
  clip.play().catch(fallback);
}
function toggleTour() {
  if(tourState==='playing') {
    cancelClip(false);tourState='paused';updateTour();$('tour-status').textContent='Paused';return;
  }
  const resume=tourState==='paused';
  if(tourState==='complete'||stepIndex<0) { stepIndex=0;walkthrough(); }
  tourState='playing';updateTour();playStep(resume);
}
function select(id) {
  selected=id;
  const item=view.nodes.find(n=>n.id===id);
  for(const el of document.querySelectorAll('.node')) el.setAttribute('aria-pressed',String(el.dataset.id===id));
  document.querySelector('.details').dataset.color=item.color;
  for(const [field,value] of Object.entries({owner:item.owner,title:item.title,copy:item.copy,data:item.data,proof:item.proof,boundary:item.boundary}))
    $('detail-'+field).textContent=value;
  $('narration-copy').textContent=clipInfo().text||item.copy;
}
function walkthrough() {
  const steps=view.flows[flowIndex].steps;
  select(steps[stepIndex]);
  $('step-label').textContent=`${stepIndex+1} of ${steps.length} · ${view.nodes.find(n=>n.id===selected).title}`;
  $('previous').disabled=stepIndex===0;
  $('next').disabled=stepIndex===steps.length-1;
}
function inspect(id) {
  stopTour();
  const index=view.flows[flowIndex].steps.indexOf(id);
  stepIndex=index;
  if(index>=0) walkthrough();
  else {
    select(id);
    $('step-label').textContent='Exploring component · Next step returns to the walkthrough';
    $('previous').disabled=true;
    $('next').disabled=false;
  }
}
function position() {
  markers.forEach((circle,i)=>{
    const path=paths[i], point=path.getPointAtLength(((elapsed/2500+i*.29)%1)*path.getTotalLength());
    circle.setAttribute('cx',point.x);
    circle.setAttribute('cy',point.y);
  });
}
function tick(now) {
  if(last!==null) elapsed+=now-last;
  last=now;position();
  frame=requestAnimationFrame(tick);
}
function motion() {
  cancelAnimationFrame(frame);last=null;
  const stopped=paused||preference.matches||document.hidden;
  $('motion').textContent=preference.matches?'Reduced motion enabled':paused?'Resume motion':'Pause motion';
  $('motion').disabled=preference.matches;
  $('motion').setAttribute('aria-pressed',String(stopped));
  position();
  if(!stopped) frame=requestAnimationFrame(tick);
}
function render() {
  const current=view.flows[flowIndex];
  $('diagram-title').textContent=view.title;
  $('scope').textContent=view.scope;
  $('limit-title').textContent=view.limitTitle;
  $('limit-copy').textContent=view.limitCopy;
  const diagram=$('diagram');
  diagram.replaceChildren(svg('title',{id:'svg-title'},view.title),svg('desc',{id:'svg-description'},'Select a component with click, Enter, or Space. Solid circles illustrate the selected flow.'));
  const definitions=svg('defs');
  for(const [name,palette] of Object.entries({...colors,muted:['','','#d6d3d1']})) {
    const arrow=svg('marker',{id:'arrow-'+name,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:5,markerHeight:5,orient:'auto-start-reverse'});
    arrow.append(svg('path',{d:'M0 0 L10 5 L0 10 Z',fill:palette[2]}));definitions.append(arrow);
  }
  diagram.append(definitions);
  for(const box of view.groups||[]) {
    diagram.append(svg('rect',{x:box.x,y:box.y,width:box.w,height:box.h,rx:18,class:'group-box'}));
    diagram.append(svg('text',{x:box.x+18,y:box.y+28,class:'group-label'},box.title));
  }
  paths=[];markers=[];
  for(const item of view.edges) {
    const active=current.steps.some((id,i)=>id===item.from&&current.steps[i+1]===item.to);
    const path=svg('path',{d:item.path,class:'edge'+(active?' active':''),'marker-end':`url(#arrow-${active?current.color:'muted'})`});
    if(active) path.style.stroke=colors[current.color][2];
    diagram.append(path);
    if(active) {
      const circle=svg('circle',{r:4.5,fill:colors[current.color][2],class:'marker'});
      paths.push(path);markers.push(circle);
    }
  }
  diagram.append(...markers);
  for(const item of view.nodes) {
    const group=svg('g',{class:'node',role:'button',tabindex:0,'aria-label':item.title,'aria-pressed':false,'data-id':item.id});
    const palette=colors[item.color];
    group.append(svg('rect',{x:item.x,y:item.y,width:item.w,height:item.h,rx:13,fill:palette[0],stroke:palette[1]}));
    group.append(svg('text',{x:item.x+18,y:item.y+(item.h<80?26:39)},item.title));
    group.append(svg('text',{x:item.x+18,y:item.y+(item.h<80?49:65),class:'sub'},item.subtitle));
    group.addEventListener('click',()=>inspect(item.id));
    group.addEventListener('keydown',event=>{
      if(event.key==='Enter'||event.key===' ') { event.preventDefault();inspect(item.id); }
    });
    diagram.append(group);
  }
  $('flows').replaceChildren(...view.flows.map((item,index)=>{
    const button=document.createElement('button');
    button.textContent=item.name;button.setAttribute('aria-pressed',String(index===flowIndex));
    button.onclick=()=>{stopTour();flowIndex=index;stepIndex=0;render();};
    return button;
  }));
  walkthrough();motion();
}
for(const button of document.querySelectorAll('[data-view]')) button.onclick=()=>{
  stopTour();
  view=button.dataset.view==='aws'?aws:product;flowIndex=0;stepIndex=0;
  for(const other of document.querySelectorAll('[data-view]')) other.setAttribute('aria-pressed',String(other===button));
  render();
};
$('previous').onclick=()=>{stopTour();stepIndex--;walkthrough();};
$('next').onclick=()=>{stopTour();stepIndex++;walkthrough();};
$('play-flow').onclick=toggleTour;
$('restart-flow').onclick=()=>{stopTour();stepIndex=0;walkthrough();};
$('narration-toggle').onclick=()=>{
  narrationEnabled=!narrationEnabled;
  try { localStorage.setItem('workbench-architecture-narration',narrationEnabled?'on':'off'); } catch {}
  updateTour();
  if(tourState==='playing') playStep();
  else cancelClip();
};
$('motion').onclick=()=>{paused=!paused;motion();};
preference.addEventListener('change',motion);
document.addEventListener('visibilitychange',()=>{
  motion();
  if(document.hidden&&tourState==='playing') toggleTour();
});
window.addEventListener('pagehide',stopTour);
render();updateTour();
