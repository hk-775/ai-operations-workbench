import {test,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';

async function login(page, username='admin') {
  await page.goto('/');
  await page.locator('#login-form').getByLabel('Username',{exact:true}).fill(username);
  await page.locator('#login-form').getByLabel('Password',{exact:true}).fill(process.env.WORKBENCH_BROWSER_PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Know what your tasks cost.'})).toBeVisible();
}
async function recorded(page) {
  await page.getByRole('button',{name:'Model evaluations',exact:true}).click();
  await page.getByRole('button',{name:'Load recorded example'}).click();
  await expect(page.locator('#recording-select option')).toHaveCount(1);
}
test('authenticated team journey persists evidence and exports a read-only proposal',async({page,baseURL})=>{
  const errors=[], external=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(!request.url().startsWith(baseURL+'/'))external.push(request.url());});
  await login(page);
  await page.getByRole('button',{name:'Usage sources',exact:true}).click();
  await page.getByLabel('Source name').fill('Application connector');
  await page.getByRole('button',{name:'Create AxonLLM source'}).click();
  await expect(page.getByRole('heading',{name:'Application connector'})).toBeVisible();
  await page.getByRole('button',{name:'Issue token',exact:true}).click();
  await expect(page.getByLabel('Ingestion token',{exact:true})).toHaveValue(/^wb_ing_/);
  await page.getByRole('button',{name:'I have saved the token'}).click();
  await recorded(page);
  await page.getByRole('button',{name:'Usage overview',exact:true}).click();
  await expect(page.getByText('$0.088074750',{exact:true})).toBeVisible();
  await page.screenshot({path:'artifacts/screenshots/pilot-overview.png',fullPage:true});
  await page.getByRole('button',{name:'Task explorer',exact:true}).click();
  await page.locator('.task-card summary').first().click();
  await expect(page.getByRole('cell',{name:/provider_reported/}).first()).toBeVisible();
  await page.screenshot({path:'artifacts/screenshots/pilot-task.png',fullPage:false});
  await page.getByRole('button',{name:'Model evaluations',exact:true}).click();
  await page.getByRole('button',{name:'Queue offline evaluation'}).click();
  // The worker continues while this browser is away.
  await page.getByRole('button',{name:'Usage overview',exact:true}).click();
  await page.reload();
  await page.getByRole('button',{name:'Model evaluations',exact:true}).click();
  await page.getByRole('button',{name:'Inspect results',exact:true}).first().click();
  await expect(page.getByRole('cell',{name:'20/24',exact:true})).toBeVisible();
  await expect(page.getByRole('cell',{name:'18/24',exact:true})).toBeVisible();
  await expect(page.getByRole('cell',{name:'14/24',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Review routing criteria'}).click();
  await page.getByRole('button',{name:'Save routing review'}).click();
  await expect(page.getByRole('heading',{name:'No model qualifies'})).toBeVisible();
  await page.screenshot({path:'artifacts/screenshots/pilot-review.png',fullPage:true});
  const downloaded=page.waitForEvent('download');
  await page.getByRole('button',{name:'Export routing review'}).first().click();
  const content=JSON.parse(await readFile(await (await downloaded).path(),'utf8'));
  expect(content.status).toBe('no_eligible_model');
  expect(content.deployment).toBe('Not applied');
  expect(content.evaluation_revision).toMatch(/^[a-f0-9]{64}$/);
  await page.getByRole('button',{name:'Sign out'}).click();
  await expect(page.getByRole('button',{name:'Sign in',exact:true})).toBeVisible();
  await expect(page.locator('#task-list')).toBeEmpty();
  await expect(page.locator('#proposals')).toBeEmpty();
  expect(errors).toEqual([]); expect(external).toEqual([]);
});
test('viewer can inspect evidence but cannot administer or queue work',async({page})=>{
  await login(page,'viewer');
  await expect(page.getByRole('button',{name:'Team & audit'})).toBeHidden();
  await page.getByRole('button',{name:'Model evaluations',exact:true}).click();
  await expect(page.getByRole('button',{name:'Queue offline evaluation'})).toBeHidden();
  await expect(page.getByRole('button',{name:'Load recorded example'})).toBeHidden();
  await page.getByRole('button',{name:'Usage sources',exact:true}).click();
  await expect(page.getByRole('button',{name:'Create AxonLLM source'})).toBeHidden();
});

test('desktop task list has a visible scrollbar and supports keyboard scrolling',async({page})=>{
  await page.setViewportSize({width:1280,height:650});
  await login(page);
  await recorded(page);
  await page.getByRole('button',{name:'Task explorer',exact:true}).click();
  await expect(page.locator('.task-card').first()).toBeVisible();
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
  await page.getByRole('button',{name:'Usage overview',exact:true}).click();
  await expect.poll(()=>workspace.evaluate(el=>el.scrollTop)).toBe(0);
  await expect(page.getByRole('button',{name:'Sign out',exact:true})).toBeInViewport();
});

test('solid workflow circles move, pause, and respect reduced motion',async({page})=>{
  await login(page);
  const marker=page.locator('.connector>span').first();
  const before=await marker.boundingBox();
  await page.waitForTimeout(250);
  expect(Math.abs((await marker.boundingBox()).x-before.x)).toBeGreaterThan(1);
  await page.getByRole('button',{name:'Pause motion'}).click();
  const paused=await marker.boundingBox();
  await page.waitForTimeout(250);
  expect(Math.abs((await marker.boundingBox()).x-paused.x)).toBeLessThan(1);
  await page.emulateMedia({reducedMotion:'reduce'});
  expect(await marker.evaluate(el=>getComputedStyle(el).animationName)).toBe('none');
});
test('mobile pilot preserves yellow task inspection and fits all pages',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await login(page);
  await recorded(page);
  for(const title of ['Usage overview','Task explorer','Model evaluations','Routing review','Usage sources','Team & audit']){
    await page.locator('nav').getByRole('button',{name:title,exact:true}).click();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    if(title==='Task explorer'){
      await page.locator('.task-card summary').first().click();
      expect(await page.locator('#page-tasks').evaluate(el=>getComputedStyle(el).getPropertyValue('--accent').trim())).toBe('#facc15');
      expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
      await page.screenshot({path:'artifacts/screenshots/pilot-mobile-task.png',fullPage:false});
    }
  }
});
test('untrusted source labels render as text and invalid uploads keep existing evidence',async({page})=>{
  await login(page);
  await page.getByRole('button',{name:'Usage sources',exact:true}).click();
  const payload='<img src=x onerror=alert(1)>';
  await page.getByLabel('Source name').fill(payload);
  await page.getByRole('button',{name:'Create AxonLLM source'}).click();
  await expect(page.getByRole('heading',{name:payload,exact:true})).toBeVisible();
  expect(await page.locator('#sources img').count()).toBe(0);
  await recorded(page);
  await page.locator('#recording-upload').setInputFiles({name:'bad.json',mimeType:'application/json',buffer:Buffer.from('{"schema":"invalid"}')});
  await expect(page.getByRole('status')).toContainText('Recording does not satisfy');
  await page.getByRole('button',{name:'Usage overview',exact:true}).click();
  await expect(page.getByText('$0.088074750',{exact:true})).toBeVisible();
});
