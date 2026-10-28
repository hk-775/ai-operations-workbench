import {chromium} from 'playwright';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const option=process.argv.indexOf('--state-dir');
const root=option < 0 ? '.pilot/hosted' : process.argv[option+1];
if(!root) throw new Error('Provide a private state directory');
let credentials;
try {credentials=JSON.parse(fs.readFileSync(root+'/logins.json','utf8'));}
catch {throw new Error('Unable to read the private logins.json configuration');}
const show=process.argv.includes('--show');
const ux=process.argv.includes('--ux');
const capture=async(target,path)=>{
 if(!process.argv.includes('--no-screenshots')) await target.screenshot({path});
};
const browser=await chromium.launch({headless:!show});
const reports={};
let phase='start';
try {
 for(const label of ['demo','clean']) {
  phase=label+' login';
  const login=credentials[label];
  const context=await browser.newContext(show?{viewport:null}:{viewport:{width:1440,height:900}});
  const page=await context.newPage();
  await page.bringToFront();
  await page.goto(login.url,{waitUntil:'domcontentloaded'});
  await page.locator('#company-login').click();
  await page.locator('input[name="username"]:visible').fill(login.username);
  await page.locator('input[name="password"]:visible').fill(login.password);
  await page.locator('input[name="signInSubmitButton"]:visible').click();
  await page.waitForURL(url=>url.origin===login.url,{timeout:45000,waitUntil:'domcontentloaded'});
  await page.locator('#team-view').waitFor({state:'visible',timeout:30000});
  const get=async path=>{const r=await context.request.get(login.url+path);assert.equal(r.status(),200,path);return r.json();};
  const session=await get('/api/auth/session');
  assert.equal(session.user.role,'admin');
  assert.equal(session.deployment,'hosted_test');
  assert.deepEqual(session.login_methods,{local:false,company:true});
  phase=label+' content';
  const usage=await get('/api/pilot/usage');
  const jobs=(await get('/api/pilot/evaluations')).evaluations;
  const reviews=(await get('/api/pilot/proposals')).proposals;
  const recordings=(await get('/api/pilot/recordings')).recordings;
  if(label==='demo') {
   assert.equal(usage.events,144);assert.equal(usage.task_count,72);
   assert.equal(usage.api_estimate_usd,'0.088074750');
   assert.deepEqual(usage.evidence_counts,{recorded:144});
   assert.equal(jobs.length,1);assert.equal(reviews.length,1);assert.equal(recordings.length,1);
   const result=await get('/api/pilot/evaluations/'+jobs[0].id);
   assert.equal(result.status,'complete');
   assert.deepEqual(result.analysis.models.map(m=>m.passed),[20,18,14]);
   assert.equal(reviews[0].status,'no_eligible_model');
   const other=await context.request.get(credentials.clean.url+'/api/auth/session');
   assert.equal((await other.json()).user,null);
  } else {
   assert.equal(usage.events,0);assert.equal(usage.task_count,0);
   assert.deepEqual(jobs,[]);assert.deepEqual(reviews,[]);assert.deepEqual(recordings,[]);
   assert.deepEqual((await get('/api/pilot/sources')).sources,[]);
  }
  const operations=await get('/api/pilot/operations');
  assert.equal(operations.status,'healthy');
  phase=label+' navigation';
  const pages=['usage','billing','tasks','evaluations','proposals','sources','operations','team'];
  const scrolling=[];
  for (const name of pages) {
   phase=label+' navigation '+name;
   const endpoints={proposals:['/api/pilot/proposals'],team:['/api/pilot/users','/api/pilot/audit'],operations:['/api/pilot/operations']}[name] || [];
   const pending=endpoints.map(path=>page.waitForResponse(r=>r.url()===login.url+path && r.status()===200));
   await page.locator('button[data-page="'+name+'"]').click();
   for(const response of await Promise.all(pending)) await response.finished();
   await page.locator('#page-'+name).waitFor({state:'visible'});
   if(name==='billing') await page.locator('#billing-report > *').first().waitFor({state:'visible'});
   if(name==='proposals') await page.locator('#proposals > *').first().waitFor({state:'visible'});
   if(name==='team') await page.locator('#audit table').waitFor({state:'visible'});
   if(name==='operations') await page.locator('#operations-metrics .metric').first().waitFor({state:'visible'});
   if(ux) {
    fs.mkdirSync(root+'/screenshots/ux',{recursive:true});
    if(name==='usage') {
     await page.locator('#metrics .metric').first().waitFor({state:'visible'});
     const color=await page.locator('nav [data-page="usage"]').evaluate(e=>getComputedStyle(e).backgroundColor);
     for(const card of await page.locator('#page-usage .metric, #page-usage .panel').all())
      assert.equal(await card.evaluate(e=>getComputedStyle(e).backgroundColor),color);
    }
    if(name==='tasks' && label==='demo') {
     const task=page.locator('.task-card').filter({hasText:'Refund inside the window'}).first();
     await task.locator(':scope > summary').click();
     assert.match(await task.locator('.task-request').innerText(),/Please refund my unused subscription/);
     assert.match(await task.locator('.task-steps > li').first().innerText(),/Classify request/);
     assert.match(await task.locator('.task-steps > li').nth(1).innerText(),/Draft decision and reply/);
     await capture(task,root+'/screenshots/ux/demo-expanded-task.png');
     await task.locator(':scope > summary').click();
    }
    if(name==='evaluations') {
     assert.equal(await page.locator('#evaluate-form button').isDisabled(),label==='clean');
     if(label==='demo') {
      await page.locator('button[data-result]').first().click();
      await page.getByRole('heading',{name:'How the models performed'}).waitFor({state:'visible'});
      await capture(page.locator('#evaluation-result'),root+'/screenshots/ux/demo-results.png');
     }
    }
    if(name==='proposals') assert.equal(await page.locator('#proposal-form button').isDisabled(),label==='clean');
    await page.locator('.content').focus();
    await page.keyboard.press('Home');
    await page.waitForFunction(()=>document.querySelector('.content').scrollTop<=1);
    await capture(page,root+'/screenshots/ux/'+label+'-'+name+'.png');
   }
   const content=page.locator('.content');
   await content.focus();
   if(show) {
    await page.bringToFront();
    await content.hover();
    await page.mouse.wheel(0,100000);
   } else await page.keyboard.press('End');
   try {
    await page.waitForFunction(()=>{const e=document.querySelector('.content');return e.scrollTop+e.clientHeight>=e.scrollHeight-3;},{},{timeout:5000});
   } catch(error) {
    console.error(JSON.stringify(await content.evaluate(e=>({page:document.querySelector('section[id^="page-"]:not([hidden])')?.id,scrollTop:e.scrollTop,clientHeight:e.clientHeight,scrollHeight:e.scrollHeight,innerWidth:innerWidth,innerHeight:innerHeight,focused:document.activeElement===e,documentScrollTop:document.scrollingElement.scrollTop}))));
    fs.mkdirSync(root+'/screenshots',{recursive:true});
    await capture(page,root+'/screenshots/'+label+'-'+name+'-failure.png');
    throw error;
   }
   const result=await content.evaluate(e=>({bottom:e.scrollTop+e.clientHeight>=e.scrollHeight-3,overflow:e.scrollHeight>e.clientHeight+3}));
   assert.ok(result.bottom,label+' '+name+' scroll');
   scrolling.push({page:name,...result});
  }
  await page.locator('button[data-page="usage"]').click();
  fs.mkdirSync(root+'/screenshots',{recursive:true});
  await capture(page,root+'/screenshots/'+label+'-hosted.png');
  reports[label]={sso:'real Cognito browser flow passed',mfa:'disabled as requested',events:usage.events,tasks:usage.task_count,api_estimate_usd:usage.api_estimate_usd,operations:operations.status,usability:ux?'task context, overview colors, evaluation guidance, and empty actions passed':'not requested',scrolling};
  if(!show) {
   phase=label+' logout';
   const signedOut=page.waitForResponse(r=>r.url()===login.url+'/api/auth/logout' && r.request().method()==='POST');
   await page.locator('#logout').click();
   await (await signedOut).finished();
   await page.locator('#login-view').waitFor({state:'visible'});
   assert.equal((await get('/api/auth/session')).user,null);
   await context.close();
  }
 }
 fs.writeFileSync(root+'/browser-report.json',JSON.stringify({checked_at:new Date().toISOString(),mode:show?'interactive native viewport':'headless 1440x900',reports},null,2),{mode:0o600});
 fs.rmSync(root+'/browser-failure.txt',{force:true});
 console.log(JSON.stringify(reports,null,2));
 if(show) await new Promise(resolve=>browser.once('disconnected',resolve));
} catch(error) {
 console.error('Hosted browser verification failed during '+phase+': '+error.name);
 fs.writeFileSync(root+'/browser-failure.txt',phase+'\n'+error.message,{mode:0o600});
 process.exitCode=1;
} finally {if(!show || process.exitCode) await browser.close();}
