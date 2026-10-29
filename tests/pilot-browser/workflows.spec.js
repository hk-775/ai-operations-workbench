import {test, expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';

async function login(page,username='admin') {
  await page.goto('/');
  await page.locator('#login-form').getByLabel('Username',{exact:true}).fill(username);
  await page.locator('#login-form').getByLabel('Password',{exact:true}).fill(process.env.WORKBENCH_BROWSER_PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.locator('#workspace-main')).toBeVisible();
}
async function downloaded(page,button) {
  const pending=page.waitForEvent('download');
  await button.click();
  return JSON.parse(await readFile(await (await pending).path(),'utf8'));
}
async function footer(page) {
  const workspace=page.getByRole('region',{name:'Workspace content'});
  await workspace.focus();await page.keyboard.press('End');
  await expect(page.locator('.page-footer')).toBeInViewport();
}
test('cost pools conserve money, revise and void; budgets show the selected basis',async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await login(page);
  await page.getByRole('button',{name:'Spend planning',exact:true}).click();
  await expect(page.locator('#budget-list')).toContainText('No budgets');
  await page.locator('#allocation-editor>summary').click();
  const pool=page.locator('#allocation-form');
  await pool.getByLabel('Cost pool name',{exact:true}).fill('Browser shared plan');
  await pool.getByLabel('Stable cost pool reference').fill('browser-shared-plan');
  await pool.getByLabel('Total cost pool (USD)').fill('0.01');
  await pool.getByLabel('Reason for the rule or correction').fill('Authored test: equal seats.');
  await page.locator('.share-project').fill('engineering');
  for(const project of ['support','research']){
    await page.getByRole('button',{name:'Add project share',exact:true}).click();
    await page.locator('.share-project').last().fill(project);
  }
  await page.getByRole('button',{name:'Preview allocation',exact:true}).click();
  await expect(page.locator('#allocation-preview-result')).toContainText('$0.003333334');
  await pool.getByLabel('Reason for the rule or correction').fill('Authored test: updated allocation explanation.');
  await expect(page.locator('#allocation-preview-result')).toBeEmpty();
  await page.getByRole('button',{name:'Save cost pool',exact:true}).click();
  const pools=page.locator('#allocation-list');
  await expect(pools).toContainText('Browser shared plan');
  await expect(page.locator('#allocation-summary')).toContainText('$0.01 allocated');
  const evidence=await downloaded(page,pools.getByRole('button',{name:'Download allocation',exact:true}));
  expect(evidence.result.allocated_total_usd).toBe('0.010000000');
  expect(evidence.result.invoice_authenticated).toBe(false);
  await pools.getByRole('button',{name:'Edit cost pool',exact:true}).click();
  await pool.getByLabel('Total cost pool (USD)').fill('30.00');
  await pool.getByLabel('Reason for the rule or correction').fill('Authored correction.');
  await page.getByRole('button',{name:'Save cost pool',exact:true}).click();
  await expect(pools).toContainText('revision 2');
  await expect(page.locator('#allocation-summary')).toContainText('$30.00 allocated');
  await page.locator('#budget-editor>summary').click();
  const budget=page.locator('#budget-form');
  await budget.getByLabel('Budget name',{exact:true}).fill('Engineering allocated budget');
  await budget.getByLabel('Stable reference').fill('engineering-allocated');
  await budget.getByLabel('Monthly limit (USD)').fill('10.00');
  await budget.getByRole('combobox',{name:'Cost basis',exact:true}).selectOption('allocated_usd');
  await budget.getByLabel('Project (optional)').fill('engineering');
  await budget.locator('[name="coverage_confirmed"]').check();
  await page.getByRole('button',{name:'Save budget',exact:true}).click();
  await expect(page.locator('#budget-list')).toContainText('At or above limit');
  await expect(page.locator('#budget-list')).toContainText('$10.00');
  await page.getByRole('button',{name:'Operations',exact:true}).click();
  await expect(page.locator('#page-operations')).toContainText('Tracked spending has reached a budget limit');
  await page.getByRole('button',{name:'Spend planning',exact:true}).click();
  await page.screenshot({path:'artifacts/screenshots/spend-planning.png',fullPage:false});
  page.once('dialog',dialog=>dialog.accept());
  await pools.getByRole('button',{name:'Void cost pool',exact:true}).click();
  await expect(pools).toContainText('Voided');
  await expect(page.locator('#budget-list')).toContainText('Incomplete evidence');
  await expect(page.locator('#allocation-summary')).toContainText('total remains unknown');
  await pools.getByRole('button',{name:'View revisions',exact:true}).click();
  const original=await downloaded(page,page.locator('#spend-history').getByRole('button',{name:'Download revision 1',exact:true}));
  expect(original.result.allocated_total_usd).toBe('0.010000000');
  await footer(page);
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(page.locator('#allocation-list')).toBeEmpty();
  await expect(page.locator('#budget-list')).toBeEmpty();
  expect(errors).toEqual([]);
});

test('custom suites evaluate saved answers, retain missing cases and compare critical regressions',async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await login(page);
  await page.getByRole('button',{name:'Custom evaluations',exact:true}).click();
  await page.getByRole('button',{name:'Try fictional cases',exact:true}).click();
  for(const input of await page.locator('#page-custom input[pattern]').all())
    expect(await input.evaluate(el=>{new RegExp(el.pattern,'v');return true;})).toBe(true);
  await page.locator('#custom-suite-form [name="name"]').fill('Browser routing checks');
  await page.locator('#custom-suite-form [name="reference"]').fill('browser-routing-checks');
  await page.getByRole('button',{name:'Save suite',exact:true}).click();
  await expect(page.locator('#custom-suites')).toContainText('Browser routing checks');
  const template=await downloaded(page,page.getByRole('button',{name:'Download answer template',exact:true}));
  expect(template.evidence).toBe('fixture');
  template.name='Baseline saved answers';
  template.models=['candidate','missing-model'];
  template.cost_basis='api_estimate_usd';
  template.responses[0].output='{"action":"escalate"}';
  template.responses[0].cost_usd='0.01';
  template.responses[1].output='{"reply":"safe"}';
  template.responses[1].cost_usd='0.02';
  await page.locator('#custom-run-upload').setInputFiles({name:'saved.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(template))});
  const result=page.locator('#custom-result');
  await expect(result.getByRole('heading',{name:'Baseline saved answers',exact:true})).toBeVisible();
  await expect(result).toContainText('missing-model');
  await expect(result).toContainText('2/2');
  const baseline=await downloaded(page,result.getByRole('button',{name:'Download custom evaluation evidence',exact:true}));
  expect(baseline.summaries[1].missing_cases).toBe(2);
  expect(baseline.summaries[1].critical_failures).toBe(1);
  expect(baseline.summaries[1].known_cost_usd).toBeNull();
  template.name='Candidate regression';
  template.responses[0].output='{"action":"allow"}';
  await page.locator('#custom-run-upload').setInputFiles({name:'after.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(template))});
  await expect(result.getByRole('heading',{name:'Candidate regression',exact:true})).toBeVisible();
  await page.locator('#custom-baseline').selectOption(baseline.id);
  await result.getByRole('button',{name:'Compare saved runs',exact:true}).click();
  await expect(page.locator('#custom-comparison')).toContainText('1 critical regressions');
  await result.locator('details').first().click();
  await expect(result).toContainText('FAILED');
  await page.screenshot({path:'artifacts/screenshots/custom-evaluations.png',fullPage:false});
  await page.reload();
  await page.getByRole('button',{name:'Custom evaluations',exact:true}).click();
  await expect(page.locator('#custom-runs')).toContainText('Candidate regression');
  await page.locator('#custom-fixtures').check();
  const definition=await downloaded(page,page.getByRole('button',{name:'Download suite',exact:true}));
  const bad=JSON.stringify(definition.value).replace('"reference":','"reference":"wrong","reference":');
  await page.locator('#custom-editor>summary').click();
  await page.locator('#custom-suite-upload').setInputFiles({name:'ambiguous.json',mimeType:'application/json',buffer:Buffer.from(bad)});
  await expect(page.getByRole('status')).toContainText('Invalid JSON');
  await footer(page);
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(result).toBeEmpty();
  await expect(page.locator('#custom-runs')).toBeEmpty();
  expect(errors).toEqual([]);
});

test('source setup guides expose commands without secrets and distinguish heartbeat from received usage',async({page})=>{
  await login(page);
  const session=await (await page.request.get('/api/auth/session')).json();
  const source=await (await page.request.post('/api/pilot/sources',{headers:{'X-Workbench-CSRF':session.csrf},
    data:{name:'Guided Codex source',kind:'codex'}})).json();
  await page.getByRole('button',{name:'Usage sources',exact:true}).click();
  const card=page.locator('#sources .panel').filter({has:page.getByRole('heading',{name:'Guided Codex source',exact:true})});
  await card.getByRole('button',{name:'Open setup guide',exact:true}).click();
  await expect(page.locator('#onboarding-steps')).toContainText('Needed');
  await expect(page.locator('#onboarding-steps')).toContainText('0 observed records');
  const tokenResponse=await page.request.post(`/api/pilot/sources/${source.id}/token`,{
    headers:{'X-Workbench-CSRF':session.csrf},data:{}});
  expect(tokenResponse.status()).toBe(200);
  const issued=await tokenResponse.json();
  const health=await page.request.post('/api/pilot/ingest/health',{headers:{Authorization:`Bearer ${issued.token}`},
    data:{collector_id:'b'.repeat(32),pending_events:0,inflight_calls:0,retrying_events:0,oldest_pending_at:null}});
  expect(health.status()).toBe(200);
  await page.getByRole('button',{name:'Refresh setup checks',exact:true}).click();
  await expect(page.locator('#onboarding-steps')).toContainText('Heartbeat current');
  await expect(page.locator('#onboarding-steps')).toContainText('0 observed records');
  const hostile='<img src=x onerror=alert(1)>';
  await page.locator('#onboarding-project').fill(hostile);
  await page.locator('#onboarding-project').press('Tab');
  await expect(page.locator('#onboarding-commands')).toContainText(hostile);
  expect(await page.locator('#onboarding-commands img').count()).toBe(0);
  const guide=await downloaded(page,page.getByRole('button',{name:'Download setup instructions',exact:true}));
  expect(JSON.stringify(guide)).not.toContain(issued.token);
  expect(guide.observed_records).toBe(0);
  await page.screenshot({path:'artifacts/screenshots/connector-setup.png',fullPage:false});
  await footer(page);
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(page.locator('#onboarding-commands')).toBeEmpty();
});

test('new workflows honor viewer role and keep mobile scrolling usable',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await login(page,'viewer');
  for(const title of ['Spend planning','Custom evaluations','Usage sources']){
    await page.locator('nav').getByRole('button',{name:title,exact:true}).click();
    if(title==='Spend planning')await expect(page.locator('#page-spend')).toHaveAttribute('aria-busy','false');
    if(title==='Custom evaluations')await expect(page.locator('#page-custom')).toHaveAttribute('aria-busy','false');
    if(title==='Usage sources')await expect(page.locator('#sources')).not.toBeEmpty();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await footer(page);
  }
  await expect(page.locator('#budget-editor')).toBeHidden();
  await expect(page.locator('#allocation-editor')).toBeHidden();
  await expect(page.locator('#custom-editor')).toBeHidden();
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
});
