import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../dist/live.js',import.meta.url),'utf8');
const logic=source.slice(source.indexOf('function startDesignProgress('),source.indexOf('function click(event)'));
function request() {
  let tick,cleared=0,resolve,reject;
  const pending=new Promise((yes,no)=>{resolve=yes;reject=no;});
  const ring={setAttribute(key,value){this[key]=value;}};
  const percent={textContent:''};
  const progress={hidden:true,isConnected:true,querySelector:s=>s==='.design-progress-value'?ring:percent};
  const button={disabled:false};
  const form={closest:()=>({querySelector:()=>progress}),querySelectorAll:()=>[button],
    matches:s=>s==='[data-live-design]',setAttribute(key,value){this[key]=value;},removeAttribute(key){delete this[key];}};
  const context={setInterval:fn=>{tick=fn;return 1;},clearInterval:()=>cleared++,
    FormData:class { *[Symbol.iterator](){yield ['target_type','PURCHASE'];yield ['generation_mode','llm'];} },
    generation:1,host:{},state:{session:{access_token:'test'},registration:null,targetType:'PURCHASE',trialData:{enabled:false}},
    api:()=>pending,notify(){},failure(){},renderDesign(){},renderBatch(){},renderRegistrations(){},account(){}};
  const {submit}=vm.runInNewContext(logic+';({submit})',context);
  return {run:()=>submit({preventDefault(){},target:form}),tick:()=>tick(),resolve,reject,progress,percent,ring,button,form,cleared:()=>cleared};
}

test('proposal progress appears immediately, caps below completion and clears on success',async()=>{
  const ui=request(),done=ui.run();
  assert.equal(ui.progress.hidden,false);assert.equal(ui.button.disabled,true);assert.equal(ui.percent.textContent,'8%');
  ui.tick();assert.equal(ui.percent.textContent,'17%');
  for(let i=0;i<200;i++)ui.tick();
  assert.equal(ui.percent.textContent,'94%');assert.equal(ui.ring['stroke-dashoffset'],'6');
  ui.resolve({});await done;
  assert.equal(ui.progress.hidden,true);assert.equal(ui.button.disabled,false);assert.equal(ui.form['aria-busy'],undefined);assert.equal(ui.cleared(),1);
});

test('failed requests hide the ring and allow another attempt',async()=>{
  const ui=request(),done=ui.run();ui.reject(new Error('network unavailable'));await done;
  assert.equal(ui.progress.hidden,true);assert.equal(ui.button.disabled,false);assert.equal(ui.cleared(),1);
});
