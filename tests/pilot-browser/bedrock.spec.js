import {test, expect} from '@playwright/test';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';

test('Bedrock setup, real delivery process, task costs and collector warnings',async({page,baseURL})=>{
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/');
  await page.locator('#login-form').getByLabel('Username',{exact:true}).fill('admin');
  await page.locator('#login-form').getByLabel('Password',{exact:true}).fill(process.env.WORKBENCH_BROWSER_PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('button',{name:'Usage sources',exact:true}).click();
  await page.getByText('Amazon Bedrock setup and coverage',{exact:true}).click();
  await expect(page.getByText(/Captures instrumented Converse and ConverseStream calls only/)).toBeVisible();
  await page.getByLabel('Source name').fill('Bedrock browser fixture');
  await page.getByRole('combobox',{name:'Connector',exact:true}).selectOption('bedrock');
  await page.getByRole('button',{name:'Create Amazon Bedrock source'}).click();
  const source=page.locator('.source-row').filter({has:page.getByRole('heading',{name:'Bedrock browser fixture',exact:true})});
  await expect(source.getByText('Active token required',{exact:true})).toBeVisible();
  await source.getByRole('button',{name:'Issue token',exact:true}).click();
  await expect(page.getByLabel('Ingestion token',{exact:true})).toHaveValue(/^wb_ing_/);
  const token=await page.getByLabel('Ingestion token',{exact:true}).inputValue();
  await page.getByRole('button',{name:'I have saved the token'}).click();
  await expect(source.getByText('Health not reported',{exact:true})).toBeVisible();
  const directory=await mkdtemp(join(tmpdir(),'workbench-bedrock-browser-'));
  try {
    const outbox=join(directory,'usage.db'), tokenFile=join(directory,'token');
    await writeFile(tokenFile,token,{mode:0o600});
    const env={...process.env,WORKBENCH_INGEST_URL:baseURL+'/api/pilot/ingest',WORKBENCH_INGEST_TOKEN_FILE:tokenFile};
    function python(args) {
      const result=spawnSync('uv',['run','--locked','python',...args],{env,encoding:'utf8'});
      expect(result.status,`Connector subprocess failed: ${result.stderr}`).toBe(0);
      return JSON.parse(result.stdout);
    }
    expect(python(['scripts/bedrock_example.py','--outbox',outbox]).model_calls).toBe(0);
    expect(python(['-m','workbench.connector','--outbox',outbox,'deliver']).acknowledged).toBe(2);
    expect(python(['-m','workbench.connector','--outbox',outbox,'deliver']).acknowledged).toBe(0);
    const health=python(['-m','workbench.connector','--outbox',outbox,'status']);
    await page.getByRole('button',{name:'Refresh connection health',exact:true}).click();
    await expect(source.getByText('Connected',{exact:true})).toBeVisible();
    await expect(source).toContainText('2 captured calls');
    const sources=await (await page.request.get('/api/pilot/sources')).json();
    const identity=sources.sources.find(s=>s.name==='Bedrock browser fixture').id;
    await page.screenshot({path:'artifacts/screenshots/bedrock-connected.png',fullPage:true});
    await page.getByRole('button',{name:'Usage overview',exact:true}).click();
    await page.getByRole('combobox',{name:'Source',exact:true}).selectOption(identity);
    await page.getByRole('button',{name:'Apply filters',exact:true}).click();
    await expect(page.locator('#evidence-counts')).not.toContainText('2 synthetic');
    await page.locator('[name="include_fixtures"]').check();
    await page.getByRole('button',{name:'Apply filters',exact:true}).click();
    await expect(page.locator('#metrics')).toContainText('$0.000129500');
    await page.getByRole('button',{name:'Task explorer',exact:true}).click();
    await page.locator('.task-card > summary').click();
    const task=page.locator('.task-card[open]');
    await expect(task).toContainText('2 captured model calls');
    await task.getByText('Tokens, timings, and capture details',{exact:true}).click();
    await expect(task).toContainText('AWS categories');
    await expect(task).toContainText('us-east-1');
    await expect(task).not.toContainText('undefined');
    await page.screenshot({path:'artifacts/screenshots/bedrock-task.png',fullPage:false});
    // Simulate a collector's real health report while its delivery queue is blocked.
    expect((await page.request.post('/api/pilot/ingest/health',{
      headers:{Authorization:`Bearer ${token}`},
      data:{...health,pending_events:3,retrying_events:1,oldest_pending_at:'2026-10-27T00:00:00Z'},
    })).status()).toBe(200);
    await page.getByRole('button',{name:'Usage sources',exact:true}).click();
    await page.getByRole('button',{name:'Refresh connection health',exact:true}).click();
    await expect(source.getByText('Delivery backlog',{exact:true})).toBeVisible();
    await expect(source).toContainText('3 waiting · 1 retrying');
    await page.getByRole('button',{name:'Operations',exact:true}).click();
    await expect(page.locator('#operations-alerts')).toContainText('undelivered events');
    // A stale-state rendering check is separate from database/clock tests in test_bedrock.py.
    await page.route('**/api/pilot/sources',async route=>{
      const response=await route.fetch(), body=await response.json();
      const record=body.sources.find(s=>s.id===identity);
      record.collection.status='stale'; record.collection.stale_collectors=1;
      for(const report of record.collection.reports) report.stale=true;
      await route.fulfill({response,json:body});
    });
    await page.getByRole('button',{name:'Usage sources',exact:true}).click();
    await page.getByRole('button',{name:'Refresh connection health',exact:true}).click();
    await expect(source.getByText('Collector stopped reporting',{exact:true})).toBeVisible();
    await page.setViewportSize({width:390,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({path:'artifacts/screenshots/bedrock-mobile-health.png',fullPage:true});
    const workspace=page.getByRole('region',{name:'Workspace content'});
    await workspace.focus(); await page.keyboard.press('End');
    await expect(page.locator('.page-footer')).toBeInViewport();
    await page.unroute('**/api/pilot/sources');
    // Restore a truthful empty-queue heartbeat and filters for other shared-server tests.
    python(['-m','workbench.connector','--outbox',outbox,'deliver']);
    await page.getByRole('button',{name:'Sign out',exact:true}).click();
    expect(errors).toEqual([]);
  } finally {
    await rm(directory,{recursive:true,force:true});
  }
});
