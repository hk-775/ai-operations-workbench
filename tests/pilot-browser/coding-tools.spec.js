import {test,expect} from '@playwright/test';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';

test('native tool fixtures use source-scoped CLI delivery and separate honest amounts',async({page,baseURL})=>{
  test.setTimeout(90000);
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/');
  await page.locator('#login-form').getByLabel('Username',{exact:true}).fill('admin');
  await page.locator('#login-form').getByLabel('Password',{exact:true}).fill(process.env.WORKBENCH_BROWSER_PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  const directory=await mkdtemp(join(tmpdir(),'workbench-native-tools-'));
  try {
    for(const [kind,label,args] of [
      ['codex','Codex',['codex','--input','data/coding-tools/codex.jsonl','--capture-id','browser-fixture',
        '--started-at','2026-10-28T12:00:00Z','--model','configured-codex-model']],
      ['claude_code','Claude Code',['claude-import','--input','data/coding-tools/claude-otel.json']],
      ['cursor','Cursor',['cursor-import','--input','data/coding-tools/cursor-usage.json',
        '--start','2026-10-28T00:00:00Z','--before','2026-10-29T00:00:00Z']],
    ]) {
      await page.getByRole('button',{name:'Usage sources',exact:true}).click();
      await page.getByLabel('Source name').fill(label+' native fixture');
      await page.getByRole('combobox',{name:'Connector',exact:true}).selectOption(kind);
      await page.getByRole('button',{name:`Create ${label} source`,exact:true}).click();
      const source=page.locator('.source-row').filter({
        has:page.getByRole('heading',{name:label+' native fixture',exact:true})});
      await source.getByRole('button',{name:'Issue token',exact:true}).click();
      await expect(page.getByLabel('Ingestion token',{exact:true})).toHaveValue(/^wb_ing_/);
      const token=await page.getByLabel('Ingestion token',{exact:true}).inputValue();
      await page.getByRole('button',{name:'I have saved the token'}).click();
      const tokenFile=join(directory,kind+'.token'),outbox=join(directory,kind+'.db');
      await writeFile(tokenFile,token,{mode:0o600});
      const env={...process.env,WORKBENCH_INGEST_URL:baseURL+'/api/pilot/ingest',
        WORKBENCH_INGEST_TOKEN_FILE:tokenFile};
      const python=arguments_=>{
        const run=spawnSync('uv',['run','--locked','python',...arguments_],{env,encoding:'utf8'});
        expect(run.status,`Metadata connector subprocess failed: ${run.stderr}`).toBe(0);
        return JSON.parse(run.stdout);
      };
      const capture=['-m','workbench.coding_tools','--fixture','--project','native-browser',
        '--outbox',outbox,...args];
      expect(python(capture).model_calls_made).toBe(0);
      expect(python(['-m','workbench.connector','--outbox',outbox,'deliver']).acknowledged)
        .toBe(kind==='cursor'?2:1);
      expect(python(capture).added).toBe(0);
      expect(python(['-m','workbench.connector','--outbox',outbox,'deliver']).acknowledged).toBe(0);
      await page.getByRole('button',{name:'Refresh connection health',exact:true}).click();
      await expect(source.getByText('Connected',{exact:true})).toBeVisible();
    }
    await page.getByRole('button',{name:'Usage overview',exact:true}).click();
    await page.locator('[name="project"]').fill('native-browser');
    await page.getByRole('button',{name:'Apply filters',exact:true}).click();
    await expect(page.locator('#usage-guide')).toContainText('No usage matches');
    await page.locator('[name="include_fixtures"]').check();
    await page.getByRole('button',{name:'Apply filters',exact:true}).click();
    await expect(page.locator('#metrics')).toContainText('$0.526324200');
    await expect(page.locator('#metrics')).toContainText('$0.213623200');
    await expect(page.locator('#metrics .metric').first()).toContainText('Unknown');
    await expect(page.locator('#evidence-counts')).toContainText('4 records');
    await page.screenshot({path:'artifacts/screenshots/native-tool-amounts.png',fullPage:false});
    await page.getByRole('button',{name:'Task explorer',exact:true}).click();
    const tasks=page.locator('.task-card');
    for(const task of await tasks.all()) await task.locator(':scope > summary').click();
    await expect(page.locator('#task-list')).toContainText('configured label');
    await expect(page.locator('#task-list')).toContainText('Usage reported');
    await expect(page.locator('#task-list')).toContainText('Different cost bases');
    await expect(page.locator('#task-list')).not.toContainText('PRIVATE_PROMPT_RESPONSE_EMAIL_SENTINEL');
    await expect(page.locator('#task-list')).not.toContainText('undefined');
    const content=page.getByRole('region',{name:'Workspace content'});
    await content.focus(); await page.keyboard.press('End');
    await expect(page.locator('.page-footer')).toBeInViewport();
    await page.setViewportSize({width:390,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.getByRole('button',{name:'Sign out',exact:true}).click();
    await expect(page.locator('#task-list')).toBeEmpty();
    await expect(page.locator('#metrics')).toBeEmpty();
    expect(errors).toEqual([]);
  } finally {
    await rm(directory,{recursive:true,force:true});
  }
});
