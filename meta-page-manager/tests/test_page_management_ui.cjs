// Synthetic local Page management, without touching real Pages or Meta.
const {chromium}=require('../../chrome-manager/frontend/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const frontend=path.resolve(__dirname,'../frontend'),origin='http://127.0.0.1:8000';
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{for(const base of ['', '/pages']){
  const context=await browser.newContext({offline:true,serviceWorkers:'block',viewport:{width:1540,height:1050}});
  const page=await context.newPage(),writes=[],reads=[],errors=[],outside=[];
  page.setDefaultTimeout(8000);
  const connection={id:1,label:'Fixture source',status:'working',connected:true,has_token:true};
  const pages=Array.from({length:11},(_,index)=>({id:String(90000001+index),name:'Managed '+String(index+1).padStart(3,'0'),category:'Fixture',status:'active',information_status:index===1?'updated':'not_updated',information_status_override:null,management_revision:1,removed_at:null,can_publish:index===1,connections:[connection],details:{}}));
  const historic=new Set(['90000002']);let conflict=false,unknown=false;
  await page.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.origin===origin&&url.pathname==='/auth/api/me')return route.fulfill({json:{user:{id:1,role:'admin'},csrf_token:'fixture-via-csrf'}});
   if(url.origin!==origin||!url.pathname.startsWith(base+'/')){outside.push(request.url());return route.abort()}
   const raw=url.pathname.slice(base.length),p=raw.replace('/api/v1/','/api/');
   if(p.startsWith('/api/')){
    if(request.method()!=='GET'){
     assert.equal(request.headers()['x-via-csrf'],'fixture-via-csrf');
     assert.equal(request.headers()['x-mpm-csrf'],'fixture-page-csrf');
     if(base)assert.ok(raw.startsWith('/api/v1/'),'Mounted UI uses the advertised v1 API for writes');
     const body=request.postDataJSON(),match=p.match(/^\/api\/pages\/(\d+)(\/restore)?$/),entry=pages.find(value=>value.id===match?.[1]);
     writes.push({p,method:request.method(),body,query:Object.fromEntries(url.searchParams)});
     assert.ok(entry,'Only the selected synthetic Page can be changed');
     const revision=request.method()==='DELETE'?Number(url.searchParams.get('revision')):body.revision;
     if(conflict){conflict=false;entry.management_revision++}
     if(revision!==entry.management_revision)return route.fulfill({status:409,json:{code:'page_revision_changed',detail:'Page đã thay đổi ở phiên khác.'}});
     entry.management_revision++;
     if(request.method()==='PATCH'){
      entry.information_status_override=body.information_status==='automatic'?null:body.information_status;
      entry.information_status=entry.information_status_override||(historic.has(entry.id)?'updated':'not_updated');
     }else if(request.method()==='DELETE')entry.removed_at='2030-11-01T00:00:00Z';
     else{assert.equal(match[2],'/restore');entry.removed_at=null}
     entry.can_publish=!entry.removed_at&&entry.information_status==='updated';
     if(unknown){unknown=false;return route.abort('failed')}
     return route.fulfill({json:{ok:true,page_id:entry.id,revision:entry.management_revision}});
    }
    reads.push({p,query:Object.fromEntries(url.searchParams)});
    if(p==='/api/session')return route.fulfill({json:{csrf_token:'fixture-page-csrf',app:{timezone:'America/Los_Angeles',page_management:true,rest_api_version:base?1:0}}});
    if(p==='/api/connections/options')return route.fulfill({json:{items:[connection],total:1,limit:100,offset:0}});
    if(p==='/api/pages'){
     let rows=pages.filter(entry=>Boolean(entry.removed_at)===(url.searchParams.get('removed')==='true'));
     const information=url.searchParams.get('information_status');if(information)rows=rows.filter(entry=>entry.information_status===information);
     const limit=Number(url.searchParams.get('limit')||10),offset=Number(url.searchParams.get('offset')||0);
     return route.fulfill({json:{items:rows.slice(offset,offset+limit),total:rows.length,limit,offset}});
    }
    const entry=pages.find(value=>p==='/api/pages/'+value.id);
    if(entry)return route.fulfill({json:{page:entry,posts:[],posts_total:0}});
    return route.fulfill({status:404,json:{detail:'Unexpected fixture endpoint'}});
   }
   if(p==='/')return route.fulfill({path:path.join(frontend,'index.html'),contentType:'text/html'});
   if(p.startsWith('/static/')){
    const file=path.resolve(frontend,p.slice(8));if(!file.startsWith(frontend+path.sep)||!fs.existsSync(file))return route.abort();
    return route.fulfill({path:file,contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.woff2')?'font/woff2':'text/css'});
   }
   return route.abort();
  });
  page.on('pageerror',error=>errors.push(error.message));
  const row=name=>page.getByRole('button',{name:'Xem chi tiết Page '+name,exact:true}).locator('xpath=ancestor::tr');
  const status=name=>row(name).locator('td').nth(2);
  const dialog=()=>page.locator('#confirm-dialog');
  const filter=()=>page.getByRole('combobox',{name:'Lọc thông tin Page',exact:true});
  const list=()=>page.getByRole('combobox',{name:'Danh sách Page',exact:true});
  const rows=()=>page.locator('.pages-table tbody>tr');
  const pager=()=>page.getByRole('navigation',{name:'Phân trang Pages',exact:true});
  await page.goto(origin+base+'/');await row('Managed 001').waitFor();
  await page.getByRole('button',{name:'Chỉnh tình trạng Page Managed 001',exact:true}).click();
  await dialog().getByRole('combobox',{name:'Tình trạng Page',exact:true}).selectOption('updated');
  await dialog().getByRole('button',{name:'Lưu tình trạng',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('#confirm-dialog').open);
  await page.waitForFunction(()=>document.querySelector('.pages-table tbody tr td:nth-child(3)').textContent.includes('Đã đổi thông tin'));
  await filter().selectOption('updated');await row('Managed 002').waitFor();assert.equal(await rows().count(),2);
  await page.getByRole('button',{name:'Chỉnh tình trạng Page Managed 002',exact:true}).click();
  await dialog().getByRole('combobox',{name:'Tình trạng Page',exact:true}).selectOption('not_updated');
  await dialog().getByRole('button',{name:'Lưu tình trạng',exact:true}).click();
  await row('Managed 002').waitFor({state:'detached'});assert.equal(await rows().count(),1);
  await filter().selectOption('');await row('Managed 002').waitFor();
  await page.getByRole('button',{name:'Chỉnh tình trạng Page Managed 002',exact:true}).click();
  await dialog().getByRole('combobox',{name:'Tình trạng Page',exact:true}).selectOption('automatic');
  await dialog().getByRole('button',{name:'Lưu tình trạng',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('#confirm-dialog').open);
  assert.match(await status('Managed 002').innerText(),/Đã đổi thông tin/);
  // A stale dialog cannot overwrite a newer decision and must read before another write.
  conflict=true;
  await page.getByRole('button',{name:'Chỉnh tình trạng Page Managed 001',exact:true}).click();
  await dialog().getByRole('button',{name:'Lưu tình trạng',exact:true}).click();
  await dialog().getByRole('button',{name:'Đóng và đọc lại danh sách',exact:true}).waitFor();
  assert.ok(await dialog().getByRole('button',{name:'Lưu tình trạng',exact:true}).isDisabled());
  await dialog().getByRole('button',{name:'Đóng và đọc lại danh sách',exact:true}).click();await row('Managed 001').waitFor();
  const before=writes.length;
  await page.getByRole('button',{name:'Xóa Page Managed 001',exact:true}).click();
  await dialog().getByRole('button',{name:'Hủy',exact:true}).click();assert.equal(writes.length,before);
  // A lost response after deletion is reconciled by reading, without replaying the write.
  unknown=true;
  await page.getByRole('button',{name:'Xóa Page Managed 001',exact:true}).click();
  await dialog().getByRole('button',{name:'Xóa khỏi danh sách',exact:true}).click();
  await dialog().getByRole('button',{name:'Đóng và đọc lại danh sách',exact:true}).waitFor();
  assert.ok(await dialog().getByRole('button',{name:'Xóa khỏi danh sách',exact:true}).isDisabled());
  assert.equal(writes.length,before+1);
  await dialog().getByRole('button',{name:'Đóng và đọc lại danh sách',exact:true}).click();
  await row('Managed 001').waitFor({state:'detached'});assert.equal(await rows().count(),10);
  await list().selectOption('removed');await row('Managed 001').waitFor();assert.equal(await rows().count(),1);
  await page.reload();await row('Managed 002').waitFor();assert.equal(await row('Managed 001').count(),0);
  await list().selectOption('removed');await row('Managed 001').waitFor();
  await page.getByRole('button',{name:'Khôi phục Page Managed 001',exact:true}).click();
  await dialog().getByRole('button',{name:'Khôi phục Page',exact:true}).click();await row('Managed 001').waitFor({state:'detached'});
  await list().selectOption('active');await row('Managed 001').waitFor();
  // Deleting the only row on the last page clamps the offset and redraws the previous page.
  await pager().getByRole('button',{name:'Trang cuối · Pages',exact:true}).click();await row('Managed 011').waitFor();
  await page.getByRole('button',{name:'Xóa Page Managed 011',exact:true}).click();
  await dialog().getByRole('button',{name:'Xóa khỏi danh sách',exact:true}).click();await row('Managed 001').waitFor();
  assert.equal(await rows().count(),10);assert.match(await pager().innerText(),/1–10 \/ 10 Pages/);
  await page.getByRole('button',{name:'Chi tiết Page Managed 001',exact:true}).click();
  const detail=page.locator('#page-dialog');await detail.getByRole('button',{name:'Chỉnh tình trạng Page Managed 001',exact:true}).waitFor();
  await detail.getByRole('button',{name:'Chỉnh tình trạng Page Managed 001',exact:true}).click();
  await dialog().getByRole('combobox',{name:'Tình trạng Page',exact:true}).selectOption('not_updated');
  await dialog().getByRole('button',{name:'Lưu tình trạng',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#page-dialog .page-information-control')?.textContent.includes('Chưa đổi thông tin'));
  await detail.getByRole('button',{name:'Đóng chi tiết Page',exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.getByRole('button',{name:'Xóa Page Managed 001',exact:true}).isVisible());
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Management controls fit a narrow viewport');
  if(process.env.VIA_UI_SCREENSHOT){await page.setViewportSize({width:1540,height:1050});await page.screenshot({path:process.env.VIA_UI_SCREENSHOT,fullPage:true})}
  assert.deepEqual(errors,[]);assert.deepEqual(outside,[]);
  assert.ok(reads.some(value=>value.query.removed==='true'));
  assert.equal(await page.evaluate(()=>localStorage.length+sessionStorage.length),0);
  await context.close();
 }}finally{await browser.close()}
 console.log('PASS: standalone and mounted v1 Page status edits, automatic history, conflicts, deletion confirmation, lost-response reconciliation, persistent removed list, restore, pagination, detail refresh and mobile layout.');
})().catch(error=>{console.error(error);process.exitCode=1});
