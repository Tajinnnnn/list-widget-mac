// (C) Exercise the real shared-backup merge and the widget's polling/reload paths.
const {chromium} = require('playwright');
const {execFileSync} = require('node:child_process');
const {pathToFileURL} = require('node:url');
const path = require('node:path');
const assert = require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  const page=await browser.newPage({viewport:{width:520,height:600}});
  let shared={lists:[{id:'a',name:'One',islandId:'g',items:[{_id:'t',text:'Existing task',done:false,updatedAt:'2026-09-01T00:00:00Z'}]},{id:'b',name:'Two',islandId:'g',items:[]},{id:'c',name:'Outside folder',items:[]}],islands:[{id:'g',name:'Folder',collapsed:false}],active:'a',settings:{retention:'never',trashRetention:'never',vibrancy:false},trash:[],tombstones:[]};
  let loads=0;
  await page.exposeFunction('__loadShared',()=>{loads++;return JSON.stringify(shared)});
  await page.exposeFunction('__saveShared',raw=>{
   shared=JSON.parse(execFileSync(path.resolve('.venv/bin/python'),['-c','import json,sys; from vault_sync import merge_docs; a,b=json.load(sys.stdin); print(json.dumps(merge_docs(a,b)))'],{input:JSON.stringify([JSON.parse(raw),shared]),encoding:'utf8'}));
   return true;
  });
  await page.addInitScript(seed=>{
   if(!localStorage.getItem('todo.widget.v3'))localStorage.setItem('todo.widget.v3',JSON.stringify(seed));
   window.pywebview={api:{set_vibrancy:async()=>true,load_backup:()=>window.__loadShared(),save_backup:raw=>window.__saveShared(raw)}};
  },shared);
  await page.goto(pathToFileURL(path.resolve('todo.html')).href);
  await page.locator('.island-label').click();
  assert.equal(await page.locator('.island-pill').count(),1);
  // Selecting another list saves shared state without reopening folders.
  await page.getByText('Outside folder',{exact:true}).click();
  assert.equal(await page.locator('.island-pill').count(),1,'opening a list must keep folders collapsed');
  await page.locator('.island-pill').click();
  await page.getByText('One',{exact:true}).click();
  await page.locator('.island-label').click();
  // Incoming task edit must appear, while its old folder-open flag is ignored.
  shared.lists[0].items[0].text='Edited from another app';
  shared.lists[0].items[0].updatedAt='2026-09-27T23:00:00Z';
  await page.getByText('Edited from another app',{exact:true}).waitFor({timeout:10000});
  assert.equal(await page.locator('.island-pill').count(),1,'shared sync must not reopen a collapsed folder');
  await page.reload();
  await page.locator('.island-pill').waitFor();
  assert.equal(await page.locator('.island-pill').count(),1,'collapsed preference survives relaunch');
  // The reverse direction also matters: explicit expand must beat a collapsed backup.
  await page.locator('.island-pill').click();
  shared.islands[0].collapsed=true;
  shared.lists[0].items[0].text='Second external edit';
  await page.getByText('Second external edit',{exact:true}).waitFor({timeout:10000});
  assert.equal(await page.locator('.island-label').count(),1,'sync must not close an expanded folder');
  // Force startup recovery (more items in backup) without sacrificing expansion.
  shared.lists[0].items.push({_id:'new',text:'Recovered task',done:false});
  await page.reload();
  await page.getByText('Recovered task',{exact:true}).waitFor();
  assert.equal(await page.locator('.island-label').count(),1,'backup recovery preserves expansion');
  await page.evaluate(doc=>window.__applySyncedState(JSON.stringify(doc)),shared);
  assert.equal(await page.locator('.island-label').count(),1,'vault sync must preserve the local folder preference');
  assert.ok(loads>=3);
  console.log('PASS: collapse and expand survive real shared merge, polling, reload and backup recovery; external task edits still arrive');
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
