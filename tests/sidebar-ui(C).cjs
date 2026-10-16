// (C) Isolated local UI regression test; never reads the user's task store.
const { chromium } = require('playwright');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
const assert = require('node:assert/strict');
require('node:fs').mkdirSync('build/ui-fixtures', {recursive:true});
(async () => {
 const browser = await chromium.launch({headless:true});
 const page = await browser.newPage({viewport:{width:520,height:600}});
 const errors=[]; page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(() => {
   const lists = ['Today','Learning','Home','A long list name that should remain readable'].map((name,i)=>({id:'l'+i,name,color:null,islandId:i===1||i===2?'g':null,items:[{_id:'t'+i,text:'Task '+i,type:'task',done:false}]}));
   localStorage.setItem('todo.widget.v3',JSON.stringify({lists,active:'l0',islands:[{id:'g',name:'Personal',collapsed:false}],settings:{retention:'never',trashRetention:'never',vibrancy:false},trash:[],tombstones:[]}));
   window.pywebview={api:{set_vibrancy:async()=>true, save_backup:async()=>true,load_backup:async()=>null}};
 });
 await page.goto(pathToFileURL(path.resolve('todo.html')).href);
 await page.waitForSelector('.tab[data-list-id="l0"]');
 const side = page.locator('#sidebar');
 assert.equal(await side.count(),1,'a sidebar must exist');
 const a=await page.locator('[data-list-id="l1"]').boundingBox(), b=await page.locator('[data-list-id="l2"]').boundingBox();
 assert.ok(b.y>=a.y+a.height,'list rows must stack vertically');
 await page.locator('[data-list-id="l1"]').click();
 assert.equal(await page.locator('#viewTitle').textContent(),'Learning');
 await page.locator('#settingsBtn').click();
 await page.locator('[data-list-id="l0"]').click();
 assert.equal(await page.locator('#viewTitle').textContent(),'Today');
 assert.ok(await page.locator('#form').isVisible());
 await page.locator('#sidebarToggle').click();
 assert.ok(!(await side.isVisible()));
 await page.locator('#sidebarToggle').click();
 await page.locator('.island-label').click();
 assert.ok(await page.locator('.island-pill').isVisible());
 await page.locator('.island-pill').click();
 // Drop at the upper edge: must reorder, not group based on horizontal position.
 await page.evaluate(()=>{
   const source=document.querySelector('[data-list-id="l3"]'), target=document.querySelector('[data-list-id="l0"]');
   const dt=new DataTransfer(), r=target.getBoundingClientRect();
   source.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));
   target.dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:dt,clientX:r.x+r.width/2,clientY:r.y+2}));
   source.dispatchEvent(new DragEvent('dragend',{bubbles:true,dataTransfer:dt}));
 });
 assert.equal(await page.locator('#tabs > .tab').first().getAttribute('data-list-id'),'l3');
 await page.locator('#settingsBtn').click();
 await page.getByText('Glass background',{exact:true}).click();
 await page.waitForFunction(()=>document.body.classList.contains('vibrancy'));
 await page.evaluate(()=>window.pywebview.api.set_vibrancy=async()=>false);
 await page.getByText('Glass background',{exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#vibrancyToggle').disabled);
 assert.ok(await page.locator('#appearanceStatus').isVisible());
 assert.ok(await page.locator('#vibrancyToggle').isChecked(),'failure must keep the previous setting');
 await page.evaluate(()=>window.pywebview.api.set_vibrancy=async()=>true);
 await page.getByText('Glass background',{exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#vibrancyToggle').disabled);
 await page.waitForFunction(()=>!document.body.classList.contains('vibrancy'));
 for(const width of [360,390,520,760]) {
   await page.setViewportSize({width,height:600});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`no page overflow at ${width}`);
   if(width<480){
     await page.locator('#sidebarToggle').click();
     await page.locator('[data-list-id="l0"]').click();
     assert.ok(!(await side.isVisible()),'drawer closes on selection');
   }
 }
 await page.setViewportSize({width:520,height:600});
 await page.locator('[data-list-id="l0"]').click();
 await page.locator('.tab-add').click();
 await page.locator('.tab-name-input').fill('New sidebar list');
 await page.locator('.tab-name-input').press('Enter');
 assert.equal(await page.locator('#viewTitle').textContent(),'New sidebar list');
 await page.locator('#input').fill('Fresh task');
 await page.locator('#input').press('Enter');
 assert.ok(await page.getByText('Fresh task',{exact:true}).isVisible());
 await page.locator('#calendarBtn').click();
 assert.equal(await page.locator('#viewTitle').textContent(),'Calendar');
 assert.ok(await page.locator('#calStyleBtn').isVisible());
 await page.locator('#archiveBtn').click();
 assert.equal(await page.locator('#viewTitle').textContent(),'Completed');
 await page.locator('#trashBtn').click();
 assert.equal(await page.locator('#viewTitle').textContent(),'Trash');
 await page.locator('[data-list-id="l0"]').click();
 await page.screenshot({path:'build/ui-fixtures/sidebar-preview(C).png'});
 assert.deepEqual(errors,[]);
 console.log('PASS: sidebar navigation, groups, vertical drop, glass success/failure, responsive layout');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
