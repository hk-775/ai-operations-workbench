import {test,expect} from '@playwright/test';

async function login(page,username='admin') {
  await page.goto('/');
  await page.locator('#login-form').getByLabel('Username',{exact:true}).fill(username);
  await page.locator('#login-form').getByLabel('Password',{exact:true}).fill(process.env.WORKBENCH_BROWSER_PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Know what your tasks cost.'})).toBeVisible();
}

test('task pages preserve the full usage subtotal and reach every recorded task',async({page})=>{
  await login(page);
  await page.getByRole('button',{name:'Model evaluations',exact:true}).click();
  await page.getByRole('button',{name:'Load recorded example'}).click();
  await expect(page.getByRole('status')).toContainText('Loaded the saved comparison');
  await page.getByRole('button',{name:'Task explorer',exact:true}).click();
  await expect(page.locator('.task-card')).toHaveCount(50);
  await page.getByRole('button',{name:'Next tasks',exact:true}).click();
  await expect(page.locator('.task-card')).toHaveCount(22);
  await expect(page.locator('#tasks-page')).toContainText('Page 2');
  await expect(page.getByRole('button',{name:'Next tasks',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Usage overview',exact:true}).click();
  await expect(page.getByText('$0.088074750',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Task explorer',exact:true}).click();
  await page.getByRole('button',{name:'Previous tasks',exact:true}).click();
  await expect(page.locator('.task-card')).toHaveCount(50);
});

test('operations are available to administrators and fit a mobile viewport',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await login(page);
  await page.getByRole('button',{name:'Operations',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Check that Workbench is running properly.'})).toBeVisible();
  await expect(page.locator('#operations-metrics .metric')).toHaveCount(4);
  await expect(page.locator('#operations-retention')).toContainText('not enabled');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:'artifacts/screenshots/operations-mobile.png',fullPage:true});
});

test('viewers cannot access the operations dashboard',async({page})=>{
  await login(page,'viewer');
  await expect(page.getByRole('button',{name:'Operations',exact:true})).toBeHidden();
  expect((await page.request.get('/api/pilot/operations')).status()).toBe(403);
});

test('call pages retain their snapshot while new and backdated usage arrives',async({page})=>{
  await login(page);
  const session=await (await page.request.get('/api/auth/session')).json();
  const headers={'X-Workbench-CSRF':session.csrf};
  const created=await page.request.post('/api/pilot/sources',{
    headers,data:{name:'Cursor pagination regression',kind:'axonllm'}});
  expect(created.status()).toBe(200);
  const source=(await created.json()).id;
  const token=(await (await page.request.post(`/api/pilot/sources/${source}/token`,{headers,data:{}})).json()).token;
  const event=(id,time='2026-10-23T00:00:00Z')=>({
    schema_version:'axon.usage.v1',event_id:id,task_id:'long-task',project:'call-snapshot-regression',
    stage:id,provider:'openai',model:'gpt-4.1-2025-04-14',occurred_at:time,status:'success',
    latency_ms:100,usage_basis:'provider_reported',attempt_coverage:'single_attempt',
    usage:{prompt_tokens:1000,completion_tokens:100,cached_tokens:200},evidence:'fixture'
  });
  const ingest=async events=>{
    for(let offset=0;offset<events.length;offset+=100) {
      expect((await page.request.post('/api/pilot/ingest',{
        headers:{Authorization:'Bearer '+token},data:{events:events.slice(offset,offset+100)}})).status()).toBe(200);
    }
  };
  await ingest(Array.from({length:205},(_,i)=>event('call-'+String(i).padStart(3,'0'))));
  await page.locator('#filters [name="project"]').fill('call-snapshot-regression');
  await page.locator('[name="include_fixtures"]').check();
  await page.getByRole('button',{name:'Apply filters',exact:true}).click();
  await page.getByRole('button',{name:'Task explorer',exact:true}).click();
  await expect(page.locator('.task-card')).toHaveCount(1);
  await page.locator('.task-card > summary').click();
  await expect(page.locator('.task-steps > li')).toHaveCount(100);
  await ingest([event('new','2026-10-24T00:00:00Z'),event('late','2026-10-20T00:00:00Z'),
    event('call-100-tied-arrival')]);
  await page.getByRole('button',{name:'Load more calls',exact:true}).click();
  await expect(page.locator('.task-steps > li')).toHaveCount(200);
  await page.getByRole('button',{name:'Load more calls',exact:true}).click();
  await expect(page.locator('.task-steps > li')).toHaveCount(205);
  expect(new Set(await page.locator('.task-steps > li strong').allTextContents()).size).toBe(205);
  await expect(page.getByRole('button',{name:'Load more calls',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Refresh tasks and calls',exact:true}).click();
  await expect(page.locator('.task-card > summary')).toContainText('208 model calls');
});
