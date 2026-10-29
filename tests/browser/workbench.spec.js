import {test, expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';

test.beforeEach(async ({request},testInfo)=>{
  if(testInfo.title.startsWith('complete customer journey')) return;
  const connected=await request.post('/api/connect',{data:{}});
  expect(connected.ok()).toBeTruthy();
  if(testInfo.title.startsWith('mobile pages')){
    const {job_id}=await (await request.post('/api/evaluate',{data:{}})).json();
    await expect.poll(async()=>(
      await (await request.get('/api/jobs/'+job_id)).json()
    ).status,{timeout:15000}).toBe('complete');
  }
});

test('complete customer journey uses actual saved evidence and exports a justified proposal', async ({page,baseURL})=>{
  const external=[];
  const sockets=[];
  const errors=[];
  page.on('request',request=>{if(!request.url().startsWith(baseURL+'/'))external.push(request.url());});
  page.on('websocket',socket=>sockets.push(socket.url()));
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'Your next optimization starts with one task.'})).toBeVisible();
  await page.getByRole('button',{name:'Connect recorded usage'}).click();
  await page.getByRole('button',{name:'Connect recorded run'}).click();
  await expect(page.getByText('144 model-stage records · all candidates',{exact:true})).toBeVisible();
  await page.screenshot({path:'artifacts/screenshots/overview.png',fullPage:true});
  await page.getByRole('button',{name:'Inspect this task'}).click();
  await expect(page.getByRole('heading',{name:'Inside an expensive task'})).toBeVisible();
  await page.screenshot({path:'artifacts/screenshots/task.png',fullPage:true});
  await page.getByRole('button',{name:'Evaluate alternatives'}).click();
  await expect(page.getByRole('heading',{name:'Same workload. Visible tradeoffs.'})).toBeVisible();
  await expect(page.getByRole('cell',{name:'20/24 83.3%',exact:true})).toBeVisible();
  await expect(page.getByRole('cell',{name:'18/24 75.0%',exact:true})).toBeVisible();
  await expect(page.getByRole('cell',{name:'14/24 58.3%',exact:true})).toBeVisible();
  await page.screenshot({path:'artifacts/screenshots/comparison.png',fullPage:true});
  await page.getByRole('button',{name:'Inspect cases'}).first().click();
  await page.getByRole('button',{name:'Inspect Stolen account',exact:true}).click();
  await expect(page.getByText('Expected decision',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Close case details'}).click();
  await page.getByRole('button',{name:'Review routing proposal'}).click();
  await expect(page.getByRole('heading',{name:'Keep the current route under review.'})).toBeVisible();
  await expect(page.getByText('NO MODEL MEETS THESE CRITERIA',{exact:true})).toBeVisible();
  await page.screenshot({path:'artifacts/screenshots/proposal.png',fullPage:true});
  const downloaded=page.waitForEvent('download');
  await page.getByRole('button',{name:'Export evidence and proposal'}).click();
  const download=await downloaded;
  const output=JSON.parse(await readFile(await download.path(),'utf8'));
  expect(output.proposal.status).toBe('no_eligible_model');
  expect(output.proposal.deployment).toBe('Not applied');
  expect(output.model_summaries).toHaveLength(3);
  expect(output.recording.samples).toHaveLength(72);
  expect(output.assessments).toHaveLength(72);
  expect(output.evaluation_revision.sha256).toMatch(/^[a-f0-9]{64}$/);
  await page.getByLabel('Minimum case pass rate (%)').fill('0');
  await page.getByRole('button',{name:'Update proposal'}).click();
  await expect(page.getByText('Contract pass rate below threshold',{exact:false})).toHaveCount(0);
  await expect(page.getByText('Critical decision checks failed',{exact:true})).toHaveCount(3);
  await expect(page.getByText('NO MODEL MEETS THESE CRITERIA',{exact:true})).toBeVisible();
  expect(external).toEqual([]);
  expect(sockets).toEqual([]);
  expect(errors).toEqual([]);
});

test('reconnecting the same source does not add duplicate charges',async({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'Connect usage',exact:false}).first().click();
  await page.getByRole('button',{name:'Connect recorded run'}).click();
  await expect(page.getByText('No duplicate charges were added.',{exact:false})).toBeVisible();
  await expect(page.getByText('$0.0881',{exact:true})).toBeVisible();
});

test('desktop workspace scrolls independently and task navigation starts at the top',async({page})=>{
  await page.setViewportSize({width:1280,height:650});
  await page.goto('/');
  await expect(page.locator('.metric').first()).toBeVisible();
  const workspace=page.getByRole('region',{name:'Workspace content'});
  const sidebarTop=(await page.locator('.sidebar').boundingBox()).y;
  expect(await workspace.evaluate(el=>el.offsetWidth-el.clientWidth)).toBeGreaterThan(0);
  await page.mouse.move(1000,450);
  await page.mouse.wheel(0,450);
  await expect.poll(()=>workspace.evaluate(el=>el.scrollTop)).toBeGreaterThan(0);
  expect(await page.evaluate(()=>window.scrollY)).toBe(0);
  expect((await page.locator('.sidebar').boundingBox()).y).toBe(sidebarTop);
  await workspace.focus();
  await page.keyboard.press('End');
  await expect(page.locator('.page-footer')).toBeInViewport();
  await page.getByRole('button',{name:'Inspect this task'}).click();
  await expect(page.getByRole('heading',{name:'Inside an expensive task'})).toBeVisible();
  await expect.poll(()=>workspace.evaluate(el=>el.scrollTop)).toBe(0);
});

test('small solid workflow markers move, pause, and respect reduced motion',async({page,browser,baseURL})=>{
  await page.goto('/');
  const marker=page.locator('.connector > span').first();
  const before=await marker.boundingBox();
  await page.waitForTimeout(250);
  const after=await marker.boundingBox();
  expect(Math.abs(after.x-before.x)).toBeGreaterThan(1);
  await page.getByRole('button',{name:'Pause workflow animation'}).click();
  const paused=await marker.boundingBox();
  await page.waitForTimeout(200);
  expect(Math.abs((await marker.boundingBox()).x-paused.x)).toBeLessThan(1);
  const context=await browser.newContext({reducedMotion:'reduce'});
  const reduced=await context.newPage();
  await reduced.goto(baseURL);
  expect(await reduced.locator('.connector > span').first().evaluate(el=>getComputedStyle(el).animationName)).toBe('none');
  await context.close();
});

test('mobile pages fit the viewport and retain the comparison workflow',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto('/');
  for(const name of ['Overview','Task explorer','Model comparison','Routing proposal']){
    await page.locator('nav').getByRole('button',{name,exact:false}).click();
    await expect(page.locator('#view')).not.toBeEmpty();
    if(name==='Model comparison') await expect(page.getByRole('cell',{name:'20/24 83.3%',exact:true})).toBeVisible();
    if(name==='Routing proposal') await expect(page.getByText('NO MODEL MEETS THESE CRITERIA',{exact:true})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({path:`artifacts/screenshots/mobile-${name.replaceAll(' ','-')}.png`,fullPage:true});
  }
});

test('invalid source uploads report failure without changing the connected run',async({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'Connect usage',exact:false}).first().click();
  await page.locator('#upload').setInputFiles({name:'bad.json',mimeType:'application/json',buffer:Buffer.from('{"schema":"unknown"}')});
  await expect(page.getByText('unsupported recording schema or evidence type')).toBeVisible();
  await expect(page.getByText('$0.0881',{exact:true})).toBeVisible();
});

test('fixture and incomplete evidence remain explicitly labeled',async({page})=>{
  const recording=JSON.parse(await readFile('data/model-comparison.json','utf8'));
  recording.mode='fixture';
  const sample=recording.samples.find(s=>s.model==='gpt-4.1-2025-04-14');
  sample.stages=[{...sample.stages[0],status:'error',usage:null,output:'',
    estimated_cost_usd:null,provider_response_id:'fixture-unknown-request'}];
  await page.goto('/');
  await page.getByRole('button',{name:'Connect usage',exact:false}).first().click();
  await page.locator('#upload').setInputFiles({name:'fixture.json',mimeType:'application/json',
    buffer:Buffer.from(JSON.stringify(recording))});
  await expect(page.getByText('Fixture evidence: responses, token usage, latency, and costs are synthetic.',{exact:false})).toBeVisible();
  await expect(page.getByText('1 request costs are unknown.',{exact:false})).toBeVisible();
  await expect(page.getByText('Known API subtotal',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Inspect this task'}).click();
  await page.getByRole('button',{name:'Evaluate alternatives'}).click();
  await expect(page.getByRole('heading',{name:'Same workload. Visible tradeoffs.'})).toBeVisible();
  const row=page.getByRole('row').filter({hasText:'Current baseline'});
  await expect(row.getByText('Unmeasured',{exact:true})).toHaveCount(2);
  await page.getByRole('button',{name:'Review routing proposal',exact:false}).click();
  await expect(page.getByText('FIXTURE EVIDENCE ONLY',{exact:true})).toBeVisible();
  await expect(page.getByText('Collect recorded model evidence.',{exact:true})).toBeVisible();
  await expect(page.locator('.recommendation .amount')).toHaveCount(0);
});
