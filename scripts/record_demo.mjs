// Record actual localhost UI with fictional support evidence. No hosted login is used.
// Requires the locked npm dependencies, ffmpeg, and a disposable PostgreSQL URL file.
import {chromium,expect} from '@playwright/test';
import {spawn,execFileSync} from 'node:child_process';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomBytes} from 'node:crypto';
import vm from 'node:vm';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const build=resolve(root,'artifacts/demo-build');
const media=resolve(root,'web/media');
await mkdir(build,{recursive:true});
await mkdir(media,{recursive:true});
const script=JSON.parse(await readFile(resolve(root,'docs/demo/storyboard.json'),'utf8'));
const speechMarks=JSON.parse(await readFile(resolve(root,'docs/demo/speech-marks.json'),'utf8'));
const sandbox={window:{}};
vm.runInNewContext(await readFile(resolve(root,'web/architecture-narration.js'),'utf8'),sandbox,{timeout:1000});
const narration=sandbox.window.WorkbenchNarration;
const port=process.env.WORKBENCH_DEMO_RECORDING_PORT||'19770';
const checkOnly=process.argv.includes('--check');
const origin=`http://127.0.0.1:${port}`;
if(!process.env.WORKBENCH_TEST_DATABASE_URL_FILE) throw new Error('Supply a disposable PostgreSQL URL file.');
const password=randomBytes(32).toString('base64url');
const server=spawn('uv',['run','--locked','python','tests/pilot_server.py'],{
  cwd:root,env:{...process.env,WORKBENCH_PILOT_TEST_PORT:port,WORKBENCH_BROWSER_PASSWORD:password},
  stdio:['ignore','ignore','pipe'],detached:true,
});
let serverErrors='';
server.stderr.on('data',chunk=>{serverErrors=(serverErrors+chunk.toString()).slice(-4000);});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let browser,context;
const audit={base_commit:execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim(),
  capture:'Actual local team UI and authored architecture; isolated PostgreSQL browser-test schema.',
  synchronization:'A temporary corner marker identifies narration start and is removed during encoding.',
  model_calls_during_capture:0,voice:'Amazon Polly neural / Joanna',scenes:[],unexpected_requests:[]};
const colors={sky:['#f0f9ff','#0284c7'],yellow:['#fefce8','#854d0e'],violet:['#f5f3ff','#7c3aed'],teal:['#f0fdfa','#0f766e']};
const introHtml=`<!doctype html><html lang="en"><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:#fafaf9;color:#1c1917;font-family:Arial,sans-serif}
main{padding:170px 110px 120px;min-height:900px;background:linear-gradient(120deg,#f5f3ff,white 55%,#eef2ff)}
.eyebrow{font-size:17px;letter-spacing:3px;color:#7c3aed;font-weight:700}h1{font-size:66px;line-height:1.13;letter-spacing:-2px;max-width:1190px;margin:26px 0 36px}
.lede{font-size:26px;color:#57534e;max-width:1150px;line-height:1.55}
.stages{display:flex;gap:18px;margin-top:64px}.stage{border:1px solid #ddd6fe;border-radius:18px;padding:24px 28px;flex:1;font-size:20px;font-weight:600}
.stage:nth-child(1){background:#f0f9ff;border-color:#bae6fd}.stage:nth-child(2){background:#fefce8;border-color:#fef08a}
.stage:nth-child(3){background:#f5f3ff}.stage:nth-child(4){background:#f0fdfa;border-color:#99f6e4}
</style><main><div class="eyebrow">AI OPERATIONS WORKBENCH</div><h1 id="film-title"></h1><p class="lede" id="film-copy"></p>
<div class="stages"><div class="stage">01 · Capture usage</div><div class="stage">02 · Inspect a task</div><div class="stage">03 · Evaluate answers</div><div class="stage">04 · Review the choice</div></div></main></html>`;

async function recordingStyle(page,name,content) {
  // Same-origin authoring styles preserve the app's real CSP.
  const url=origin+'/__recording/'+name+'.css';
  await page.route(url,route=>route.fulfill({contentType:'text/css',body:content}));
  await page.addStyleTag({url});
}
async function decorate(page,scene) {
  await recordingStyle(page,'film',`
    #team-view.shell{position:fixed!important;top:62px!important;left:0;right:0;height:calc(100dvh - 166px)!important}
    body{padding-top:0!important}
    #film-top{position:fixed;inset:0 0 auto;height:62px;z-index:10000;display:flex;align-items:center;justify-content:space-between;padding:0 32px;font:600 16px Arial,sans-serif;color:#1c1917;border-bottom:1px solid #e7e5e4;background:white}
    #film-chapter{font-size:14px;border-radius:20px;padding:9px 16px;background:${colors[scene.color][0]};color:${colors[scene.color][1]}}
    #film-bottom{position:fixed;inset:auto 0 0;height:104px;z-index:10000;background:#fffefb;border-top:1px solid #e7e5e4;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:10px;padding:12px 60px;font-family:Arial,sans-serif}
    #film-caption{font-size:22px;font-weight:500;line-height:1.4;color:#1c1917;text-align:center;max-width:1390px}
    #film-disclosure{font-size:11px;color:#78716c;letter-spacing:.4px}
    #film-sync{position:fixed;top:2px;left:2px;width:12px;height:12px;background:#ff00ff;z-index:10001;display:none}
    body[data-recording-ready="true"] #film-sync{display:block}
  `);
  await page.evaluate(({title,chapter})=>{
    const top=document.createElement('div');top.id='film-top';
    const name=document.createElement('span');name.textContent='Workbench · '+title;
    const tag=document.createElement('span');tag.id='film-chapter';tag.textContent=chapter;
    top.append(name,tag);
    const bottom=document.createElement('div');bottom.id='film-bottom';
    const caption=document.createElement('div');caption.id='film-caption';
    const disclosure=document.createElement('div');disclosure.id='film-disclosure';
    disclosure.textContent='Fictional support cases · Saved model responses · Illustrative architecture motion · Synthetic narration';
    const sync=document.createElement('span');sync.id='film-sync';sync.setAttribute('aria-hidden','true');
    bottom.append(caption,disclosure);document.body.append(top,bottom,sync);
  },scene);
}
async function navigate(page,label) {
  await page.locator('nav').getByRole('button',{name:label,exact:true}).click();
}
async function ready(page,scene) {
  if(['intro','close'].includes(scene.id)) {
    await page.goto(origin+'/__recording/title');
    await page.locator('#film-title').evaluate((el,text)=>{el.textContent=text;},scene.title);
    await page.locator('#film-copy').evaluate((el,text)=>{el.textContent=text;},scene.id==='intro'?
      'One complete workflow: captured API cost, saved answer quality, and a model decision you can explain.':
      'Explore the recorded demo. Inspect the evidence. Connect your application when you are ready.');
  } else if(['architecture','aws'].includes(scene.id)) {
    await page.goto(origin+'/static/architecture.html');
    if(scene.id==='aws') {
      await page.getByRole('button',{name:'AWS hosted test',exact:true}).click();
      await page.getByRole('button',{name:'Back up data',exact:true}).click();
    } else await page.getByRole('button',{name:'Evaluate answers',exact:true}).click();
    await recordingStyle(page,'architecture',`
      body>header,.intro,.scope-note,footer{display:none!important}
      main{padding:78px 24px 120px!important;max-width:none!important}
      .toolbar{margin:0 0 10px!important}.canvas-heading{display:none!important}
      .explorer{grid-template-columns:minmax(0,1fr) 400px!important}
      .diagram-help{display:none!important}.flows{padding-top:12px!important}
      .tour-controls{padding-top:10px!important}.diagram-scroll svg{height:480px!important;min-width:0!important}
      .details{padding:20px!important}.details h2{font-size:22px!important}
      .details p,.details dd{font-size:12px!important;line-height:1.55!important}
      .details dl{margin:16px 0!important}.details dt{margin-top:14px!important}
      .boundary{padding-top:12px!important}.narration-transcript{display:none!important}
      .walkthrough{padding:10px 20px!important}
    `);
  } else {
    await page.goto(origin+'/');
    await expect(page.getByRole('heading',{name:'Know what your tasks cost.'})).toBeVisible();
    const views={clean:'Usage overview',usage:'Usage overview',task:'Task explorer',sources:'Usage sources',
      evaluate:'Model evaluations',results:'Model evaluations',review:'Routing review',operations:'Operations'};
    await navigate(page,views[scene.id]);
    if(scene.id==='clean') {
      await expect(page.locator('#usage-guide')).toContainText('Start with an example');
    }
    if(scene.id==='usage') {
      await expect(page.getByText('$0.088074750',{exact:true})).toBeVisible();
    }
    if(scene.id==='task') {
      await expect(page.locator('.task-card').first()).toBeVisible();
      let found=false;
      for(let i=0;i<8;i++) {
        if(await page.locator('.task-card').filter({hasText:'Refund inside the window'}).count()) {found=true;break;}
        if(await page.locator('#tasks-next').isDisabled()) break;
        const previous=await page.locator('#tasks-page').textContent();
        await page.locator('#tasks-next').click();
        await expect(page.locator('#tasks-page')).not.toHaveText(previous);
      }
      if(!found) throw new Error('Recorded refund task was not found.');
      const task=page.locator('.task-card').filter({hasText:'Refund inside the window'}).first();
      await task.locator(':scope > summary').click();
      await expect(task.locator('.task-steps > li').first()).toContainText('Classify request');
      await expect(task.locator('.task-steps > li').nth(1)).toContainText('Draft decision and reply');
      await task.evaluate(el=>el.scrollIntoView({block:'start'}));
    }
    if(scene.id==='sources') {
      await expect(page.locator('#sources')).toContainText('Recorded');
    }
    if(scene.id==='results') {
      await page.getByRole('button',{name:'Inspect results',exact:true}).first().click();
      await expect(page.getByRole('cell',{name:'20/24',exact:true})).toBeVisible();
      await expect(page.getByRole('cell',{name:'18/24',exact:true})).toBeVisible();
      await expect(page.getByRole('cell',{name:'14/24',exact:true})).toBeVisible();
      await page.locator('#evaluation-result').evaluate(el=>el.scrollIntoView({block:'start'}));
    }
    if(scene.id==='review') {
      await page.getByRole('button',{name:'Save routing review',exact:true}).click();
      await expect(page.getByRole('heading',{name:'No model qualifies'})).toBeVisible();
      await page.locator('#proposals').evaluate(el=>el.scrollIntoView({block:'start'}));
    }
  }
  await decorate(page,scene);
  const focus={
    usage:'#usage-guide',task:'.task-card[open]',sources:'#page-sources .screen-guide',
    evaluate:'#page-evaluations > article',results:'#evaluation-result',
    review:'#proposals',operations:'#operations-metrics',
  }[scene.id];
  if(focus) await page.locator(focus).evaluate(el=>{
    el.scrollIntoView({block:'start'});
    const content=el.closest('.content');
    const header=content?.querySelector('.topbar');
    const overlap=(header?.getBoundingClientRect().bottom||0)+12-el.getBoundingClientRect().top;
    if(overlap>0) content?.scrollBy(0,-overlap);
  });
  await page.mouse.move(1580,870);
}

try {
  let live=false;
  for(let i=0;i<100;i++) {
    try {if((await fetch(origin+'/health/live')).ok) {live=true;break;}} catch {}
    if(server.exitCode!==null) throw new Error('Isolated recording server did not start.');
    await sleep(250);
  }
  if(!live) throw new Error('Recording server readiness timed out.');
  browser=await chromium.launch({headless:true});
  context=await browser.newContext({viewport:{width:1600,height:900},
    ...(checkOnly?{}:{recordVideo:{dir:resolve(build,'raw-video'),size:{width:1600,height:900}}})});
  await context.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.origin!==origin) {audit.unexpected_requests.push(url.origin);return route.abort();}
    if(url.pathname==='/__recording/title') return route.fulfill({contentType:'text/html',body:introHtml});
    return route.continue();
  });
  const login=await context.request.post(origin+'/api/auth/login',{
    headers:{Origin:origin},data:{username:'admin',password},
  });
  if(!login.ok()) throw new Error('Isolated recording sign-in failed.');
  for(const scene of script.scenes) {
    const clip=narration['scene-'+scene.id];
    const hold=Math.ceil((clip.duration+0.85)*30)/30;
    const marks=speechMarks[scene.id];
    if(!Array.isArray(marks)||!marks.length) throw new Error('Missing authored sentence timings: '+scene.id);
    const page=await context.newPage();
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await ready(page,scene);
    if(scene.id==='usage') await expect(page.locator('#usage-guide')).toContainText('72 runs');
    const started=Date.now();
    await page.evaluate(marks=>{
      document.body.dataset.recordingReady='true';
      document.querySelector('#film-caption').textContent=marks[0]?.value||'';
      for(const mark of marks) setTimeout(()=>{
        const caption=document.querySelector('#film-caption');
        if(caption) caption.textContent=mark.value.replace(/<[^>]*>/g,'');
      },mark.time);
    },marks);
    if(['architecture','aws'].includes(scene.id)) await page.getByRole('button',{name:'Play flow',exact:true}).click();
    if(scene.id==='evaluate') await page.getByRole('button',{name:'Run evaluation',exact:true}).click();
    await page.waitForTimeout(checkOnly?250:3500);
    await page.screenshot({path:resolve(build,scene.id+'.png')});
    if(scene.id==='clean') {
      // The clean state was captured. Load the real bundled recording through the UI.
      if(!checkOnly) await page.waitForTimeout(5000);
      await navigate(page,'Model evaluations');
      await page.getByRole('button',{name:'Load recorded example',exact:true}).click();
      await expect(page.locator('#recording-select option')).toHaveCount(1);
    }
    if(scene.id==='evaluate') {
      await page.getByRole('button',{name:'Inspect results',exact:true}).first().waitFor({timeout:30000});
    }
    if(checkOnly) {
      if(errors.length) throw new Error('Browser errors in '+scene.id+': '+errors.join('; '));
      await page.close();
      console.log('Verified scene: '+scene.id);
      continue;
    }
    const remaining=hold*1000-(Date.now()-started);
    if(remaining<0) throw new Error('Scene preparation exceeded its narration: '+scene.id);
    await page.waitForTimeout(remaining+120);
    const video=page.video();
    await page.close();
    const path=await video.path();
    if(errors.length) throw new Error('Browser errors in '+scene.id+': '+errors.join('; '));
    audit.scenes.push({id:scene.id,title:scene.title,narration_duration:clip.duration,
      duration:hold,raw_video:path,marks});
    await writeFile(resolve(build,'capture.json'),JSON.stringify(audit,null,2));
    console.log(`Recorded ${scene.id}: ${hold.toFixed(1)}s`);
  }
  if(audit.unexpected_requests.length) throw new Error('Capture attempted an unexpected remote request.');
  if(!checkOnly) await writeFile(resolve(build,'capture.json'),JSON.stringify(audit,null,2));
  console.log(checkOnly?'All scene interactions verified.':'All scenes recorded from actual local UI. Encoding can begin.');
} finally {
  await context?.close();
  await browser?.close();
  const stop=signal=>{
    try { process.kill(-server.pid,signal); } catch(error) { if(error.code!=='ESRCH') throw error; }
  };
  const closed=new Promise(resolve=>server.once('close',resolve));
  stop('SIGTERM');
  let timeout;
  await Promise.race([closed,new Promise(resolve=>{timeout=setTimeout(resolve,8000);})]);
  clearTimeout(timeout);
  // The group belongs only to this recording host and its worker.
  stop('SIGKILL');
  server.stderr.destroy();
}
