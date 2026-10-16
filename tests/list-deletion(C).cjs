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
  page.on('dialog', dialog => dialog.accept());
  await page.locator('.tab[data-list-id="c"] .tab-x').click();
  await page.waitForFunction(() => JSON.parse(localStorage.getItem('todo.widget.v3')).listTombstones?.some(t=>t.id==='c'));
  await page.waitForTimeout(3500);
  assert.ok(!shared.lists.some(l=>l.id==='c'),'shared save must preserve deletion');
  await page.reload();
  await page.waitForTimeout(3500);
  assert.equal(await page.locator('.tab[data-list-id="c"]').count(),0,'deleted list must stay gone after reload and polling');
  assert.equal(shared.lists.length,2,'other lists remain');
  assert.ok(shared.trash.some(e=>e.kind==='list' && e.listId==='c'),'deleted list remains recoverable');
  console.log('PASS: deleting an empty list survives shared merge, polling and reload');
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
