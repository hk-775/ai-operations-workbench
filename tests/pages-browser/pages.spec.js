import {test, expect} from '@playwright/test';

function inspectNetwork(page, baseURL) {
  const failures=[], errors=[], sockets=[];
  page.on('pageerror', e=>errors.push(e.message));
  page.on('response', r=>{if(r.status()>=400) failures.push(r.url());});
  page.on('websocket', socket=>sockets.push(socket.url()));
  page.on('request', request=>{
    if(!request.url().startsWith(baseURL)) failures.push(request.url());
    if(/\/api\/|\/auth\/|\/metrics(?:\?|$)/.test(request.url())) failures.push(request.url());
  });
  return ()=>{expect(errors).toEqual([]);expect(failures).toEqual([]);expect(sockets).toEqual([]);};
}

test('public entry plays bundled media, seeks chapters, loads captions, and links to the release',async({page,baseURL})=>{
  const check=inspectNetwork(page,baseURL);
  await page.goto('./');
  await expect(page.getByRole('heading',{level:1})).toHaveText('Follow the cost.Prove the model choice.');
  await expect(page.locator('.disclosure')).toContainText('Fictional support cases');
  await expect(page.locator('#chapters button')).toHaveCount(12);
  await expect(page.getByRole('link',{name:'Download Workbench v0.9.0'})).toHaveAttribute(
    'href','https://github.com/hk-775/ai-operations-workbench/releases/tag/v0.9.0');
  const video=page.locator('video'),audio=page.locator('audio');
  await page.locator('#chapters button').first().click();
  await expect.poll(()=>video.evaluate(el=>el.currentTime)).toBeGreaterThan(.15);
  await page.locator('#chapters button').nth(8).click();
  await expect.poll(()=>video.evaluate(el=>el.currentTime)).toBeGreaterThan(158);
  await audio.evaluate(el=>el.play());
  await expect.poll(()=>audio.evaluate(el=>el.currentTime)).toBeGreaterThan(.15);
  expect(await video.evaluate(el=>el.paused)).toBe(true);
  await expect(page.locator('#player-status')).toBeEmpty();
  await audio.evaluate(el=>el.pause());
  await video.evaluate(el=>{el.textTracks[0].mode='hidden';});
  await expect.poll(()=>video.evaluate(el=>el.textTracks[0].cues?.length||0)).toBeGreaterThan(40);
  await page.screenshot({path:'artifacts/screenshots/pages-demo-desktop.png',fullPage:true});
  for(const link of await page.locator('a[download]').all()) {
    const response=await page.request.get(new URL(await link.getAttribute('href'),baseURL).href);
    expect(response.ok()).toBe(true);
  }
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.locator('footer').scrollIntoViewIfNeeded();
  await expect(page.locator('footer')).toBeVisible();
  await page.screenshot({path:'artifacts/screenshots/pages-demo-mobile.png',fullPage:true});
  check();
});

test('published architecture narrates, animates, pauses, supports keyboard and serves editable downloads',async({page,baseURL})=>{
  const check=inspectNetwork(page,baseURL);
  await page.addInitScript(()=>{
    const NativeAudio=window.Audio;
    window.__tourAudio=[];
    window.Audio=function(...args){const audio=new NativeAudio(...args);window.__tourAudio.push(audio);return audio;};
  });
  await page.goto('architecture.html');
  const position=()=>page.locator('.marker').first().evaluate(el=>[el.getAttribute('cx'),el.getAttribute('cy')]);
  const start=await position();
  await expect.poll(position).not.toEqual(start);
  await page.getByRole('button',{name:'Pause motion',exact:true}).click();
  const stopped=await position();
  await page.waitForTimeout(150);
  expect(await position()).toEqual(stopped);
  await page.getByRole('button',{name:'Resume motion',exact:true}).click();
  await expect.poll(position).not.toEqual(stopped);
  await page.getByRole('button',{name:'Play flow',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>window.__tourAudio.at(-1)?.currentTime||0)).toBeGreaterThan(.15);
  await page.getByRole('button',{name:'Pause flow',exact:true}).click();
  const paused=await page.evaluate(()=>window.__tourAudio.at(-1).currentTime);
  await page.waitForTimeout(150);
  expect(await page.evaluate(()=>window.__tourAudio.at(-1).currentTime)).toBe(paused);
  await page.getByRole('button',{name:'Resume flow',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>window.__tourAudio.at(-1).currentTime)).toBeGreaterThan(paused);
  await page.getByRole('button',{name:'Restart',exact:true}).click();
  expect(await page.evaluate(()=>window.__tourAudio.every(audio=>audio.paused))).toBe(true);
  await page.getByRole('button',{name:'AWS hosted test',exact:true}).click();
  await page.getByRole('button',{name:'Back up data',exact:true}).click();
  await page.getByRole('button',{name:'Amazon S3 backups',exact:true}).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#detail-title')).toHaveText('Amazon S3 backups');
  await page.screenshot({path:'artifacts/screenshots/pages-architecture-desktop.png',fullPage:true});
  for(const link of await page.locator('a[download]').all()) {
    const response=await page.request.get(new URL(await link.getAttribute('href'),baseURL).href);
    expect(response.ok()).toBe(true);
    const body=await response.body();
    if((await link.getAttribute('href')).endsWith('.png')) expect([...body.subarray(0,4)]).toEqual([137,80,78,71]);
    if((await link.getAttribute('href')).endsWith('.drawio')) expect(body.toString()).toContain('<mxfile');
  }
  await page.emulateMedia({reducedMotion:'reduce'});
  await expect(page.getByRole('button',{name:'Reduced motion enabled'})).toBeDisabled();
  const reduced=await position();
  await page.waitForTimeout(150);
  expect(await position()).toEqual(reduced);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const scroller=page.locator('.diagram-scroll');
  await scroller.focus();await page.keyboard.press('ArrowRight');
  await expect.poll(()=>scroller.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
  await page.locator('footer').scrollIntoViewIfNeeded();
  await expect(page.locator('footer')).toBeVisible();
  await page.screenshot({path:'artifacts/screenshots/pages-architecture-mobile.png',fullPage:true});
  check();
});

test('every public asset is available and browser policy blocks API and WebSocket connections',async({page,baseURL})=>{
  const manifestResponse=await page.request.get(new URL('site-manifest.json',baseURL).href);
  expect(manifestResponse.ok()).toBe(true);
  const manifest=await manifestResponse.json();
  expect(manifest.version).toBe('0.9.0');
  for(const file of Object.keys(manifest.files)) {
    // GitHub consumes this build marker and intentionally does not serve it.
    // Keep checking every actual page, media file, diagram, and metadata asset.
    if(file==='.nojekyll') continue;
    const response=await page.request.head(new URL(file,baseURL).href);
    expect(response.ok(),file).toBe(true);
  }
  await page.goto('demo.html');
  const blocked=await page.evaluate(async()=>{
    const violations=[];
    document.addEventListener('securitypolicyviolation',e=>violations.push(e.violatedDirective));
    let apiBlocked=false;
    try{await fetch('./api/should-never-connect');}catch{apiBlocked=true;}
    let socketBlocked=false;
    await new Promise(resolve=>{
      const url=new URL('./socket-should-never-connect',location.href);
      url.protocol=location.protocol==='https:'?'wss:':'ws:';
      try{const socket=new WebSocket(url);socket.onerror=()=>{socketBlocked=true;resolve();};socket.onopen=()=>{socket.close();resolve();};}
      catch{socketBlocked=true;resolve();}
    });
    return {apiBlocked,socketBlocked,violations};
  });
  expect(blocked.apiBlocked).toBe(true);
  expect(blocked.socketBlocked).toBe(true);
  expect(blocked.violations.filter(v=>v==='connect-src').length).toBeGreaterThanOrEqual(2);
});
