import {test, expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';

// Authored billing text; no downloaded customer records or provider calls.
function csv(cost='0.0001475') {
  return [
    'identity/LineItemId,lineItem/ProductCode,lineItem/UsageAccountId,bill/BillingPeriodStartDate,bill/BillingPeriodEndDate,lineItem/CurrencyCode,lineItem/LineItemType,lineItem/UsageStartDate,lineItem/UsageEndDate,lineItem/UsageType,lineItem/UnblendedCost,product/regionCode,pricing/unit,lineItem/UsageAmount',
    `ui-fiction,AmazonBedrock,000000000000,2026-10-01T00:00:00Z,2026-11-01T00:00:00Z,USD,Usage,2026-10-27T00:00:00Z,2026-10-28T00:00:00Z,Authored test usage,${cost},us-east-1,Request,1`,
    '',
  ].join('\n');
}

async function login(page,username='admin') {
  await page.goto('/');
  await page.locator('#login-form').getByLabel('Username',{exact:true}).fill(username);
  await page.locator('#login-form').getByLabel('Password',{exact:true}).fill(process.env.WORKBENCH_BROWSER_PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('button',{name:'Billing reconciliation',exact:true}).click();
}

test('billing import, declared scope, immutable refresh, export and private UI',async({page})=>{
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await login(page);
  await expect(page.getByText('No billing report is connected yet.',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Load fictional billing example',exact:true}).click();
  const report=page.locator('#billing-report'), comparisons=page.locator('#billing-comparisons');
  await expect(report.getByText('FICTIONAL BILLING EXAMPLE',{exact:true})).toBeVisible();
  await expect(comparisons).toContainText('2 captured calls across 1 task runs');
  await expect(comparisons).toContainText('USD 0.000018');
  await expect(report.locator('.billing-metrics')).toContainText('USD 0.0121475');
  await expect(report.locator('.billing-metrics')).toContainText('adjustments USD -0.002');
  const colors=await page.evaluate(()=>({
    card:getComputedStyle(document.querySelector('.billing-metrics .metric')).backgroundColor,
    nav:getComputedStyle(document.querySelector('[data-page="billing"]')).backgroundColor,
  }));
  expect(colors.card).toBe(colors.nav);
  await page.screenshot({path:'artifacts/screenshots/billing-desktop.png',fullPage:false});
  const downloadEvent=page.waitForEvent('download');
  await report.getByRole('button',{name:'Export reconciliation',exact:true}).click();
  const download=await downloadEvent;
  const evidence=JSON.parse(await readFile(await download.path(),'utf8'));
  expect(evidence.evidence).toBe('fixture');
  expect(evidence.billing_snapshot.rows).toHaveLength(5);
  expect(evidence.comparisons[0].difference_usd).toBe('0.000018');
  const source=evidence.comparisons[0].source_ids[0];
  await comparisons.getByRole('button',{name:/Inspect .* tasks/}).click();
  await expect(page.locator('#page-tasks')).toBeVisible();
  await expect(page.locator('.task-card')).toHaveCount(1);
  await page.locator('.task-card>summary').click();
  await expect(page.locator('.task-card[open]')).toContainText('2 captured model calls');
  await page.getByRole('button',{name:'Billing reconciliation',exact:true}).click();
  await page.getByRole('button',{name:'Load fictional billing example',exact:true}).click();
  await expect(page.locator('#billing-report-select option')).toHaveCount(1);

  const form=page.locator('#billing-import-form'), preview=page.locator('#billing-preview');
  const untrusted='<img src=x onerror=alert(1)>';
  await form.getByLabel('Report name',{exact:true}).fill(untrusted);
  await form.getByLabel('AWS usage account ID').fill('000000000000');
  await form.getByLabel('Billing month').fill('2026-10');
  await page.locator('#billing-files').setInputFiles({name:'authored.csv',mimeType:'text/csv',buffer:Buffer.from(csv())});
  await form.locator('[name="complete_snapshot"]').check();
  await form.getByRole('button',{name:'Preview charges',exact:true}).click();
  await expect(preview).toContainText('USD 0.0001475');
  await expect(preview).toContainText('1 rows have no invoice identifier');
  await preview.getByRole('button',{name:'Import snapshot',exact:true}).click();
  await expect(report.getByRole('heading',{name:untrusted,exact:true})).toBeVisible();
  expect(await report.locator('img').count()).toBe(0);
  await expect(report.locator('.billing-metrics')).toContainText('Unassigned net charges');
  await expect(report.locator('.billing-metrics')).toContainText('USD 0.0001475');
  await page.getByText('Link billing groups to a captured model scope',{exact:true}).click();
  const mapping=page.locator('#billing-mapping-form');
  await mapping.getByRole('checkbox',{name:'Select Authored test usage',exact:true}).check();
  await mapping.getByLabel('Comparison name',{exact:true}).fill('Declared test scope');
  await mapping.getByLabel('Captured Bedrock sources').selectOption(source);
  await mapping.getByLabel('Exact captured model ID').fill('amazon.nova-micro-v1:0');
  await mapping.getByLabel('Region code',{exact:true}).fill('us-east-1');
  await mapping.locator('[name="account_binding_confirmed"]').check();
  await mapping.getByRole('button',{name:'Save declared scope',exact:true}).click();
  await expect(comparisons).toContainText('Comparison incomplete');
  await expect(comparisons).toContainText('No captured calls match this declared scope.');
  await expect(comparisons).toContainText('Unavailable');
  const revision1=await page.locator('#billing-report-select').inputValue();

  // Upload a replacement and inspect both old and new snapshots.
  await page.locator('#billing-files').setInputFiles({name:'refresh.csv',mimeType:'text/csv',buffer:Buffer.from(csv('0.000000000000000123'))});
  await form.getByRole('button',{name:'Preview charges',exact:true}).click();
  await expect(preview).toContainText('Current revision 1');
  await preview.getByRole('button',{name:'Import snapshot',exact:true}).click();
  await expect(report).toContainText('Revision 2');
  await expect(report.locator('.billing-metrics')).toContainText('USD 0.000000000000000123');
  await expect(comparisons).toContainText('carried forward from revision 1');
  const revision2=await page.locator('#billing-report-select').inputValue();
  await page.locator('#billing-report-select').selectOption(revision1);
  await expect(report.getByText('Historical snapshot',{exact:true})).toBeVisible();
  await expect(comparisons.getByRole('button',{name:'Unlink these groups',exact:true})).toHaveCount(0);
  await expect(report.locator('.billing-metrics')).toContainText('USD 0.0001475');
  await page.locator('#billing-report-select').selectOption(revision2);
  await comparisons.getByRole('button',{name:'Unlink these groups',exact:true}).click();
  await expect(comparisons).toContainText('No comparison is configured yet.');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const workspace=page.getByRole('region',{name:'Workspace content'});
  await workspace.focus(); await page.keyboard.press('End');
  await expect(page.locator('.page-footer')).toBeInViewport();
  await page.screenshot({path:'artifacts/screenshots/billing-mobile.png',fullPage:false});
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(report).toBeEmpty();
  await expect(page.locator('#billing-report-select')).toBeEmpty();
  expect(errors).toEqual([]);

  await page.setViewportSize({width:1440,height:1050});
  await login(page,'viewer');
  await expect(report).toContainText('Revision 2');
  await expect(page.getByRole('button',{name:'Load fictional billing example',exact:true})).toBeHidden();
  await expect(form).toBeHidden();
  await expect(page.locator('#billing-mapping-form')).toHaveCount(0);
  await expect(report.getByRole('button',{name:'Export reconciliation',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
});

test('billing refresh recovers when retention removes the selected snapshot',async({page})=>{
  await login(page);
  await page.getByRole('button',{name:'Load fictional billing example',exact:true}).click();
  const report=page.locator('#billing-report');
  await expect(report.getByText('FICTIONAL BILLING EXAMPLE',{exact:true})).toBeVisible();
  const expired=await page.locator('#billing-report-select').inputValue();
  const session=await (await page.request.get('/api/auth/session')).json();
  const imported=await page.request.post('/api/pilot/billing/imports',{
    headers:{'X-Workbench-CSRF':session.csrf},
    data:{format:'legacy-cur',account_id:'000000000001',month:'2026-10',currency:'USD',
      name:'Retention test · authored billing',complete_snapshot:true,expected_revision:0,
      files:[csv('0.25').replaceAll('000000000000','000000000001')]},
  });
  expect(imported.status()).toBe(200);
  const retained=(await imported.json()).id;
  let removedAll=false;
  // Deterministically reproduce retention between selecting a report and
  // refreshing it, without altering the shared test server's other evidence.
  await page.route(/\/api\/pilot\/billing\/reports(?:\?.*)?$/,async route=>{
    const response=await route.fetch(), body=await response.json();
    await route.fulfill({response,json:{...body,page:0,has_more:false,
      reports:removedAll?[]:body.reports.filter(row=>row.id===retained)}});
  });
  await page.route(`**/api/pilot/billing/reports/${expired}`,route=>
    route.fulfill({status:404,json:{detail:'Record not found'}}));
  await page.route(`**/api/pilot/billing/reports/${retained}`,route=>removedAll?
    route.fulfill({status:404,json:{detail:'Record not found'}}):route.continue());
  await page.getByRole('button',{name:'Refresh billing view',exact:true}).click();
  await expect(report.getByRole('heading',{name:'Retention test · authored billing',exact:true})).toBeVisible();
  await expect(report.locator('.billing-metrics')).toContainText('USD 0.25');
  removedAll=true;
  await page.getByRole('button',{name:'Refresh billing view',exact:true}).click();
  await expect(report.getByRole('heading',{name:'No billing report is connected yet.',exact:true})).toBeVisible();
  await expect(report.locator('.billing-metrics')).toHaveCount(0);
  await expect(report.getByRole('button',{name:'Export reconciliation',exact:true})).toHaveCount(0);
  await expect(page.locator('#billing-report-select')).toHaveValue('');
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
});
