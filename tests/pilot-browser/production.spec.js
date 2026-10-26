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
