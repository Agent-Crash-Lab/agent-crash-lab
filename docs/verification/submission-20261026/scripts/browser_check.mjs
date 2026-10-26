import { chromium } from 'playwright';
import fs from 'node:fs/promises';
const out = process.env.ACL_UI_OUT || 'artifacts/submission-replay/ui';
const base = process.env.ACL_UI_URL || 'http://127.0.0.1:18293';
await fs.mkdir(out,{recursive:true});
const browser = await chromium.launch({headless:true});
const page = await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
page.setDefaultTimeout(15000);
const errors=[];
page.on('pageerror',e=>errors.push(e.message));
await page.goto(base+'/#execution?run=RUN-003');
await page.locator('[data-live-login] [name=user_id]').fill('requester-01');
await page.locator('[data-live-login] [name=password]').fill(process.env.ACL_TEST_PASSWORD);
await page.locator('[data-live-login] button[type=submit]').click();
await page.locator('#tutorial-invitation[open]').waitFor();
await page.locator('#tutorial-invitation [data-action=dismiss-tutorial]').first().click();
await page.waitForFunction(()=>document.body.innerText.includes('RUN-003'));
await fs.writeFile(out+'/inspection-before.json',JSON.stringify({url:page.url(),body:await page.locator('body').innerText()}));
await page.getByText('추가 조사 기록',{exact:true}).click();
await page.getByText('조회된 발주는 2건입니다.',{exact:false}).first().waitFor();
const body=await page.locator('body').innerText();
await fs.writeFile(out+'/RUN-003-visible.txt',body);
await page.screenshot({path:out+'/RUN-003-analysis.png',fullPage:true});
await page.goto(base+'/#runs');
await page.locator('[data-live-run-search] input').fill('RUN-004');
await page.locator('[data-live-run-search] button').click();
await page.locator('[data-live-run-list] [data-live-run="RUN-004"]').waitFor();
await page.waitForFunction(()=>{const s=document.querySelector('[data-live-run-list]')?.innerText||'';return s.includes('RUN-004')&&!s.includes('RUN-003')});
const list=await page.locator('[data-live-run-list]').innerText();
if(list.includes('RUN-003'))throw new Error('Search mixed another run');
await page.locator('[data-live-run-list] [data-live-run="RUN-004"]').click();
await page.waitForFunction(()=>location.hash.includes('RUN-004') && document.body.innerText.includes('RUN-004'));
await page.screenshot({path:out+'/RUN-004-analysis.png',fullPage:true});
const result={mode:'headless Chromium; actual frontend and API, no API stubs',
  checks:[{id:'UI-01',expected:'stored RUN-003, database count 2 shown in investigation',actual:body.includes('조회된 발주는 2건'),pass:body.includes('조회된 발주는 2건')},
          {id:'UI-02',expected:'search RUN-004 excludes RUN-003',actual:list,pass:!list.includes('RUN-003')},
          {id:'UI-03',expected:'selected saved run opens its analysis route',actual:page.url(),pass:page.url().includes('RUN-004')}],
  page_errors:errors};
await fs.writeFile(out+'/results.json',JSON.stringify(result,null,2));
await browser.close();
console.log(JSON.stringify({checks:result.checks.map(x=>({id:x.id,pass:x.pass})),page_errors:errors}));
