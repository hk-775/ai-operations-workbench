import {test,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';

async function login(page,username='admin') {
  await page.goto('/');
  await page.locator('#login-form').getByLabel('Username',{exact:true}).fill(username);
  await page.locator('#login-form').getByLabel('Password',{exact:true}).fill(process.env.WORKBENCH_BROWSER_PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
}

test('coding evidence is explanatory, tunable, exportable and cleared on logout',async({page})=>{
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await login(page,'viewer');
  await page.getByRole('button',{name:'Coding evaluations',exact:true}).click();
  await expect(page.getByRole('heading',{name:'What does an accepted patch cost?'})).toBeVisible();
  await page.getByRole('button',{name:'Load coding demonstration',exact:true}).click();
  const result=page.locator('#coding-result');
  await expect(result).toContainText('AUTHORED MODEL EXAMPLE');
  await expect(result).toContainText('Fixture evidence cannot justify a real model recommendation');
  await expect(result.locator('tbody tr')).toHaveCount(3);
  await expect(result.locator('tbody tr').filter({hasText:'example-fast'})).toContainText('$0.006');
  await expect(result.locator('tbody tr').filter({hasText:'example-repair'})).toContainText('12');
  await page.locator('#coding-threshold').selectOption('50');
  await expect(page.locator('#coding-gates')).toContainText('Excluded by acceptance');
  await result.getByText('Attempt 1 · final patch · failed · completed',{exact:true}).first().click();
  await expect(result.locator('details[open]')).toContainText('Source SHA-256');
  await page.screenshot({path:'artifacts/screenshots/coding-desktop.png',fullPage:false});
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'Download this result',exact:true}).click();
  const download=await downloadPromise;
  const file=await download.path();
  const evidence=JSON.parse(await readFile(file,'utf8'));
  expect(evidence.runtime.verifier_api_calls).toBe(0);
  expect(evidence.tasks).toHaveLength(18);
  await page.getByRole('button',{name:'Clear preview',exact:true}).click();
  await page.locator('#coding-upload').setInputFiles(file);
  await expect(result).toContainText('AUTHORED MODEL EXAMPLE');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const workspace=page.getByRole('region',{name:'Workspace content'});
  await workspace.focus();await page.keyboard.press('End');
  await expect(page.locator('.page-footer')).toBeInViewport();
  await page.screenshot({path:'artifacts/screenshots/coding-mobile.png',fullPage:false});
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(result).not.toContainText('AUTHORED MODEL EXAMPLE');
  await expect(result).not.toContainText(evidence.sha256);
  expect(errors).toEqual([]);
});

test('sample export download and stopped billing collector explanation',async({page})=>{
  await login(page);
  await page.route('**/api/pilot/billing/collection',route=>route.fulfill({json:{
    collectors:[{name:'Authored stopped collector',status:'failed',last_attempt_at:1,
      last_success_at:1,interval_seconds:3600,stale:true,error:'Collection failed.'}]
  }}));
  await page.getByRole('button',{name:'Billing reconciliation',exact:true}).click();
  await expect(page.locator('#billing-collection')).toContainText('Stopped reporting');
  await expect(page.locator('#billing-collection')).toContainText('last accepted snapshot is preserved');
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('link',{name:'Download sample CSVs and usage'}).click();
  const download=await downloadPromise;
  expect(download.suggestedFilename()).toBe('bedrock-billing-sample.zip');
  expect((await readFile(await download.path())).subarray(0,2).toString()).toBe('PK');
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(page.locator('#billing-collection')).toBeEmpty();
});
