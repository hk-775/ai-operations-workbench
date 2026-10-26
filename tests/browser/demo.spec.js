import {test,expect} from '@playwright/test';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

test('video, audio, captions, chapter seeking, and mobile layout work without API calls',async({page,baseURL})=>{
  const errors=[],failed=[],requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>requests.push(request.url()));
  page.on('response',response=>{if(response.status()>=400) failed.push(response.url());});
  await page.goto('/static/demo.html');
  await expect(page.getByRole('heading',{level:1})).toHaveText('Follow the cost.Prove the model choice.');
  await expect(page.locator('#chapters button')).toHaveCount(12);
  const video=page.locator('video'),audio=page.locator('audio');
  await expect.poll(()=>video.evaluate(el=>el.readyState)).toBeGreaterThanOrEqual(1);
  expect(await video.evaluate(el=>el.paused)).toBe(true);
  expect(await audio.evaluate(el=>el.paused)).toBe(true);
  const duration=await video.evaluate(el=>el.duration);
  expect(duration).toBeGreaterThan(230);
  expect(duration).toBeLessThan(250);
  await page.locator('#chapters button').nth(7).click();
  await expect.poll(()=>video.evaluate(el=>el.currentTime)).toBeGreaterThan(135);
  await expect(page.locator('#chapters button').nth(7)).toHaveAttribute('aria-current','true');
  expect(await video.evaluate(el=>el.paused)).toBe(false);
  // Programmatic play follows an established user gesture; verify audio/video exclusivity.
  await audio.evaluate(el=>el.play());
  await expect.poll(()=>video.evaluate(el=>el.paused)).toBe(true);
  await expect.poll(()=>audio.evaluate(el=>el.currentTime)).toBeGreaterThan(.1);
  await page.locator('#chapters button').first().click();
  await expect.poll(()=>audio.evaluate(el=>el.paused)).toBe(true);
  await video.evaluate(el=>el.pause());
  await video.evaluate(el=>{el.textTracks[0].mode='hidden';});
  await expect.poll(()=>video.evaluate(el=>el.textTracks[0].cues?.length||0)).toBeGreaterThan(40);
  await page.screenshot({path:'artifacts/screenshots/narrated-demo-desktop.png',fullPage:true});
  await page.getByText('Read the full transcript',{exact:true}).click();
  await expect(page.locator('#transcript')).toContainText('no model qualifies');
  await page.getByText('Read the full transcript',{exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.locator('footer').scrollIntoViewIfNeeded();
  await expect(page.locator('footer')).toBeVisible();
  await page.screenshot({path:'artifacts/screenshots/narrated-demo-mobile.png',fullPage:true});
  for(const link of await page.locator('a[download]').all()) {
    const response=await page.request.get(new URL(await link.getAttribute('href'),baseURL+'/static/demo.html').href);
    expect(response.ok()).toBe(true);
  }
  expect(requests.every(url=>url.startsWith(baseURL+'/static/'))).toBe(true);
  expect(failed).toEqual([]);
  expect(errors).toEqual([]);
});

test('demo opens as local files and under a static-site prefix',async({page})=>{
  await page.goto(pathToFileURL(resolve('web/demo.html')).href);
  await expect(page.locator('#chapters button')).toHaveCount(12);
  await page.locator('#chapters button').first().click();
  await expect.poll(()=>page.locator('video').evaluate(el=>el.currentTime)).toBeGreaterThan(.1);
  await page.locator('video').evaluate(el=>el.pause());
  const unexpected=[];
  const files=new Set(['demo.html','demo.css','demo.js','demo-manifest.js']);
  await page.route('**/*',async route=>{
    const path=new URL(route.request().url()).pathname;
    const relative=path.replace('/nested/workbench/','');
    if(!path.startsWith('/nested/workbench/')||
       !(files.has(relative)||/^media\/workbench-demo[\w.-]*$/.test(relative))) {
      unexpected.push(path);return route.abort();
    }
    // Preserve the real static server's range responses, which media seeking needs.
    return route.fulfill({response:await route.fetch({
      url:new URL('/static/'+relative,route.request().url()).href,
    })});
  });
  await page.goto('/nested/workbench/demo.html');
  await page.locator('#chapters button').nth(8).click();
  await expect.poll(()=>page.locator('video').evaluate(el=>el.currentTime)).toBeGreaterThan(158);
  await page.locator('video').evaluate(el=>el.pause());
  expect(unexpected).toEqual([]);
});
