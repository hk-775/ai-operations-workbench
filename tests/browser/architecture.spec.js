import {test,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const position = page => page.locator('.marker').first().evaluate(el=>[el.getAttribute('cx'),el.getAttribute('cy')]);

test('architecture explains both views and supports keyboard, motion controls, and mobile scrolling',async({page,baseURL})=>{
  const errors=[],requests=[],failed=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>requests.push(request.url()));
  page.on('response',response=>{if(response.status()>=400) failed.push(response.url());});
  await page.goto('/static/architecture.html');
  await expect(page.getByRole('heading',{name:'Follow the evidence.'})).toBeVisible();
  await expect(page.locator('#detail-title')).toHaveText('Application + AxonLLM');
  const start=await position(page);
  await expect.poll(()=>position(page)).not.toEqual(start);
  await page.getByRole('button',{name:'Pause motion',exact:true}).click();
  const paused=await position(page);
  await page.waitForTimeout(150);
  expect(await position(page)).toEqual(paused);
  await page.getByRole('button',{name:'Evaluate answers',exact:true}).click();
  await expect(page.locator('#detail-title')).toHaveText('Saved support answers');
  await page.getByRole('button',{name:'Next step',exact:true}).click();
  await expect(page.locator('#detail-title')).toHaveText('PostgreSQL ledger');
  await page.getByRole('button',{name:'Contract + Ostiari Guard',exact:true}).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#detail-proof')).toContainText('critical-case failures');
  await page.getByRole('button',{name:'Resume motion',exact:true}).click();
  const resumed=await position(page);
  await expect.poll(()=>position(page)).not.toEqual(resumed);
  await page.screenshot({path:'artifacts/screenshots/architecture-product.png',fullPage:true});

  await page.getByRole('button',{name:'AWS hosted test',exact:true}).click();
  await page.getByRole('button',{name:'Back up data',exact:true}).click();
  await page.getByRole('button',{name:'Next step',exact:true}).click();
  await expect(page.locator('#detail-title')).toHaveText('Host timers');
  await page.getByRole('button',{name:'Amazon S3 backups',exact:true}).focus();
  await page.keyboard.press('Space');
  await expect(page.locator('#detail-boundary')).toContainText('30 days');
  await expect(page.locator('#limit-copy')).toContainText('MFA is disabled only');
  await expect(page.locator('#limit-copy')).toContainText('private queue');
  await page.screenshot({path:'artifacts/screenshots/architecture-aws.png',fullPage:true});
  await page.emulateMedia({reducedMotion:'reduce'});
  await expect(page.getByRole('button',{name:'Reduced motion enabled'})).toBeDisabled();
  const reduced=await position(page);
  await page.waitForTimeout(150);
  expect(await position(page)).toEqual(reduced);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const scroller=page.locator('.diagram-scroll');
  expect(await scroller.evaluate(el=>el.scrollWidth>el.clientWidth)).toBe(true);
  await scroller.focus();
  await page.keyboard.press('ArrowRight');
  await expect.poll(()=>scroller.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
  await page.locator('footer').scrollIntoViewIfNeeded();
  await expect(page.locator('footer')).toBeVisible();
  await page.screenshot({path:'artifacts/screenshots/architecture-mobile.png',fullPage:true});
  expect(errors).toEqual([]);
  expect(failed).toEqual([]);
  expect(requests.every(url=>url.startsWith(baseURL+'/static/architecture.'))).toBe(true);
});

test('architecture works offline and from a prefixed static path without API calls',async({page})=>{
  const errors=[],unexpected=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(pathToFileURL(resolve('web/architecture.html')).href);
  await page.getByRole('button',{name:'AWS hosted test',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Two workspaces. One test host.'})).toBeVisible();
  await page.getByRole('button',{name:'Detect an outage',exact:true}).click();
  await page.getByRole('button',{name:'Amazon SNS → SQS',exact:true}).click();
  await expect(page.locator('#detail-boundary')).toContainText('No person receives');

  const files=new Set(['architecture.html','architecture.css','architecture.js']);
  await page.route('**/*',async route=>{
    const path=new URL(route.request().url()).pathname;
    const filename=path.split('/').at(-1);
    if(!path.startsWith('/nested/workbench/')||!files.has(filename)) {
      unexpected.push(path);return route.abort();
    }
    return route.fulfill({body:await readFile(resolve('web',filename)),
      contentType:filename.endsWith('.html')?'text/html':filename.endsWith('.css')?'text/css':'application/javascript'});
  });
  await page.goto('/nested/workbench/architecture.html');
  await page.getByRole('button',{name:'Review model choice',exact:true}).click();
  await page.getByRole('button',{name:'Next step',exact:true}).click();
  await expect(page.locator('#detail-title')).toHaveText('Routing review');
  await expect(page.locator('#detail-boundary')).toContainText('not guaranteed savings');
  expect(await page.locator('body').evaluate(el=>getComputedStyle(el).margin)).toBe('0px');
  expect(unexpected).toEqual([]);
  expect(errors).toEqual([]);
});
