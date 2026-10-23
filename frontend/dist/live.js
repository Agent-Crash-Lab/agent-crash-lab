import {api, mergeEvents, isFinished, sceneEvents, escapeHtml as esc, testsForAgent, normalizeDraft, startPayload, runGuidance, nextActionHint, preparedPurchaseSample, completedSystemRuns, qaReportMarkup, qaReportDocument, qaReportCollectionDocument, reviewMarkup, repairMarkup, followupMarkup, scenarioMarkup} from './live-api.js?v=0.15.0';
import {registrationMarkup,parseTools,exampleDeclaration,fillDeclaration,renderToolBindings,collectDeclaration,profileAnalysis,capabilityLabel,registeredCaseReady} from './qa-targets.js?v=0.15.0';
import {purchaseTopology} from './topologies.js?v=0.15.0';
import {mountScene, pauseScene} from './scene.js?v=0.15.0';
import {frameFor} from './topology.js?v=0.15.0';

const graph = {...purchaseTopology, version:'live-topology-v1', nodes:[...purchaseTopology.nodes,
  {id:'guide',label:'조사 지침',role:'store',layer:3,lane:2},
  {id:'fault',label:'사고 주입',role:'tool',layer:1,lane:3}]};
const state = {authDismissed:false, registration:null, registrations:[], capabilityOptions:[], executionRuntimes:[], targetType:'PURCHASE', targetTypes:[], batch:null, batchRequest:null, designPlan:null, designCaseId:null, knowledge:null, knowledgeStatus:null, trialData:{enabled:false,quantity:100,inventory:20,unit_price_minor:12000}, session:null, catalog:null, runs:[], run:null, events:[], selected:null, comparison:null, settled:false, draft:{agent:"purchase",test_id:"S01",system_id:"B0"}, compareDraft:{left:"",right:""}, pendingStart:false, pendingRunId:null};
let host, timer, batchTimer, playback, generation=0, loading=false, page='agents', go;
const $ = selector => host?.querySelector(selector);
const json = value => esc(JSON.stringify(value, null, 2));
const badge = text => `<span class="badge" data-result="${esc(text)}">${esc(text)}</span>`;
const scopeTitle=id=>({agent_behavior:'Agent 행동',business_state:'실제 업무 상태',server_control:'서버 통제',report_truthfulness:'보고 정확성',task_completion:'업무 완료',qa_evidence:'시험 근거'}[id] || id);
const ruleTitle=id=>state.catalog?.tests.flatMap(t=>t.rules || []).find(r=>r.rule_id===id)?.name || id;

const options = (items, key, title=key) => items.map(x => `<option value="${esc(x[key])}">${esc(x[key])}${x[title] !== x[key] ? ` · ${esc(x[title])}` : ''}</option>`).join('');
const messages = {
  LLM_KEY_NOT_CONFIGURED:'서버의 LLM_API_KEY와 QA_DESIGN_LLM_MODEL을 설정해야 새 상황을 생성할 수 있습니다. 키는 채팅이나 등록 양식에 입력하지 마세요.',
  UNPRICED_MODEL:'설계 모델 설정과 비용 계산 지원 여부를 확인해 주세요.',
  LLM_BUDGET_EXHAUSTED:'설정한 모델 호출 예산을 사용했습니다. 서버에서 예산 기록을 확인해 주세요.',
  TARGET_RUNTIME_CHANGED:'실행기 버전이나 모델 설정이 바뀌었습니다. 등록·설계를 다시 진행하세요.',
  INCOMPATIBLE_EXECUTION_TARGET:'실행기와 같은 업무·기능·정책 및 지원 데이터를 사용해야 합니다.',
  PROFILE_INFORMATION_REQUIRED:'승인·재시도 정책을 보완한 뒤 새로 저장하세요.',
  PROFILE_ANALYSIS_CHANGED:'위험 분류 기준이 바뀌었습니다. 등록 정보를 다시 저장해 분석하세요.',
  QA_ANALYSIS_UNAVAILABLE:'Agent 설명 분석 서비스에 연결하지 못했습니다.',
  INVALID_QA_TARGET:'도구 정의·입력 형식·기능 연결을 확인해 주세요.',
  QA_DESIGN_UNAVAILABLE:'시험 설계 서비스 또는 문서 검색에 연결하지 못했습니다. 서비스 상태와 설계 모델 설정을 확인해 주세요.',
  QA_BATCH_IN_PROGRESS:'반복 실험이 진행 중입니다. 현재 실험을 확인하거나 중단을 요청하세요.',
  RELIABILITY_REQUIRES_LLM:'현재 대상은 규칙 기반입니다. 기본 연결 점검으로 실행하세요.',
  QA_STRATEGY_REQUIRED:'우선 Agent를 보고 시험 설계를 새로 실행해 주세요.',
  RUN_IN_PROGRESS:'다른 실행 또는 조사가 진행 중입니다. 실행 기록을 열어 확인해 주세요.',
  UNAUTHORIZED:'로그인이 필요하거나 세션이 만료되었습니다. 다시 로그인해 주세요.',
  PERMISSION_DENIED:'이 계정에는 필요한 권한이 없습니다.',
  HARNESS_UNAVAILABLE:'Harness에 연결할 수 없습니다. 서비스 상태를 확인해 주세요.',
  RUN_FINALIZED:'이미 종료된 실행입니다. 새 시험을 시작해 주세요.',
  NOT_COMPARABLE:'동일한 SYSTEM 시나리오의 완료된 실행 두 개를 선택해 주세요.',
  RUN_NOT_COMPLETED:'두 실행이 모두 완료된 뒤 비교해 주세요.'
};
function notify(message, error=false) {
  if (!$('[data-live-message]')) return;
  $('[data-live-message]').textContent=message;
  $('[data-live-message]').classList.toggle('live-error',error);
}
function failure(error) {
  if (error.status === 401) { state.session=null; clearTimeout(timer); if(host)account(); }
  notify(error.details?.decision_saved ? '결정은 저장됐지만 실행 재개 전달에 실패했습니다. 같은 결정을 다시 보내 주세요.' : messages[error.code] || error.message, true);
}
export function leaveLive() { clearTimeout(timer); clearTimeout(batchTimer); clearInterval(playback); playback=null; generation++; host=null; loading=false; pauseScene(); }
export function isLiveAuthenticated() { return !!state.session; }
const pageCopy={
  agents:['평가 대상','어떤 제조 Agent를 시험할지 고르세요. 세 유형 모두 참조 환경과 시험용 MCP로 실행되며 실제 설비는 조작하지 않습니다.'],
  prepare:['시험 설계','Agent 기능과 근거 자료를 확인해 위험 시험을 만듭니다.'],
  live:['실제 실행','설정한 조건으로 실행하고 담당자 승인·거절을 처리합니다.'],
  execution:['실행 분석','실행 흐름과 QA 보고서를 확인합니다.'],
  compare:['결과 비교','같은 SYSTEM 시나리오의 완료된 실행을 비교합니다.']
};
const agentName=agent=>agent==='investigator'?'사고 조사 Agent':state.registration?.name || ({PRODUCTION:'생산 일정 Agent',QUALITY:'품질·출하 Agent'}[state.run?.manifest?.agent_type || state.targetType] || '구매 Agent');
const targetTypeMeta={
  PURCHASE:{
    badge:'사고 시나리오 포함',
    chain:['Agent','승인','MCP','DB'],
    faultIndex:2,
    scenarios:[
      {code:'S01 정상 발주'},
      {code:'S02 승인 거절'},
      {code:'S03 응답 유실',fault:true},
      {code:'S04 공급 자격'}
    ]
  },
  PRODUCTION:{
    badge:'',
    chain:['Agent','계획 도구','MES','DB'],
    faultIndex:-1,
    scenarios:[
      {code:'P01 정상 편성'},
      {code:'P02 설비 중단'},
      {code:'P03 중복 편성',fault:true}
    ]
  },
  QUALITY:{
    badge:'',
    chain:['Agent','검사 조회','승인','DB'],
    faultIndex:-1,
    scenarios:[
      {code:'Q01 합격 출하'},
      {code:'Q02 불합격 보류'},
      {code:'Q03 근거 누락',fault:true}
    ]
  }
};
function renderChainSvg(chain, faultIndex=-1) {
  const W=300, step=W/chain.length;
  let g='';
  chain.forEach((it,i)=>{
    const x=step*i+step/2;
    if(i<chain.length-1){
      const x2=x+step, fe=i===faultIndex-1;
      g+=`<line x1="${x+18}" y1="22" x2="${x2-18}" y2="22" stroke="${fe?'var(--signal, #ff6a3d)':'var(--control, #4a4a52)'}" stroke-width="1.6" ${fe?'stroke-dasharray="4 4" class="fault-wire-glitch"':''}/>`;
      g+=`<circle r="2.8" fill="${fe?'#ff8a5f':'var(--pos, #3fb68b)'}"><animate attributeName="cx" from="${x+18}" to="${x2-18}" dur="${1.5+i*0.28}s" repeatCount="indefinite"/><animate attributeName="cy" values="22;22" dur="1s" repeatCount="indefinite"/></circle>`;
      g+=`<circle r="1.6" fill="${fe?'#ff6a3d':'#6fd4ab'}" opacity="0.65"><animate attributeName="cx" from="${x+18}" to="${x2-18}" dur="${1.5+i*0.28}s" begin="0.18s" repeatCount="indefinite"/><animate attributeName="cy" values="22;22" dur="1s" repeatCount="indefinite"/></circle>`;
    }
    const isf=i===faultIndex;
    if(isf){
      g+=`<circle cx="${x}" cy="22" r="18" fill="none" stroke="var(--signal, #ff6a3d)" stroke-width="1" opacity="0.45" class="shock"/>`;
    }
    g+=`<rect x="${x-14}" y="8" width="28" height="28" rx="6" fill="${isf?'var(--sig-bg, #2a1610)':'var(--raised-2, #1f1f24)'}" stroke="${isf?'var(--signal, #ff6a3d)':'var(--control, #3a3a42)'}" stroke-width="1.4"/>`;
    g+=`<circle cx="${x}" cy="22" r="3.2" fill="${isf?'var(--signal, #ff6a3d)':'var(--pos, #3fb68b)'}" opacity="0.85"/>`;
    g+=`<text x="${x}" y="56" text-anchor="middle" font-size="11" font-weight="500" fill="var(--text-2, #8b8b93)" font-family="Pretendard Variable, Pretendard, sans-serif">${esc(it)}</text>`;
  });
  return `<svg class="chain" viewBox="0 0 300 64" aria-hidden="true">${g}</svg>`;
}
function renderLoginTopoSvg() {
  const ICONS={
    mcp:`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="2.5" width="12" height="4" rx="1"/><rect x="2" y="9.5" width="12" height="4" rx="1"/><circle cx="4.5" cy="4.5" r="0.8" fill="currentColor"/><circle cx="4.5" cy="11.5" r="0.8" fill="currentColor"/></svg>`,
    scenario:`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9.5 2H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5.5L9.5 2Z"/><path d="M5.5 8h5M5.5 10.8h3.2" stroke-linecap="round"/></svg>`,
    harness:`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 1.8 13.5 4v4.2c0 3.2-2.3 5.2-5.5 6-3.2-.8-5.5-2.8-5.5-6V4L8 1.8Z"/><path d="m6 8 1.5 1.5L10.5 6" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    mfg:`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3.5" y="3.5" width="9" height="9" rx="1.8"/><path d="M6.5 6.5h3v3h-3zM8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2" stroke-linecap="round"/></svg>`,
    rag:`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2.5 3.5A1.5 1.5 0 0 1 4 2h8.5v11H4a1.5 1.5 0 0 0-1.5 1.5v-11Z"/><path d="M2.5 13.5A1.5 1.5 0 0 1 4 12h9.5M6 5.5h4.5M6 8h3" stroke-linecap="round"/></svg>`,
    db:`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><ellipse cx="8" cy="3.8" rx="5" ry="2"/><path d="M3 3.8v8.4c0 1.1 2.2 2 5 2s5-.9 5-2V3.8"/><path d="M3 8c0 1.1 2.2 2 5 2s5-.9 5-2"/></svg>`,
    qa:`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="7.2" cy="7.2" r="4.2"/><path d="m10.5 10.5 3.2 3.2M5.6 7.2h3.2M7.2 5.6v3.2" stroke-linecap="round"/></svg>`
  };
  const NODES=[
    {id:'mcp',label:'MCP Server',sub:'인증·승인·구매 도구',l:0,n:-1,kind:'mcp',ox:-8,oy:-8},
    {id:'scenario',label:'Scenario Agent',sub:'시험 설계·검토',l:0,n:1,kind:'screen',ox:22,oy:-4},
    {id:'harness',label:'Harness',sub:'시험 운영·판정',l:1,n:-1,kind:'disc',ox:-6,oy:-18},
    {id:'mfg',label:'Manufacturing Operation Agent',sub:'시험 대상 · 도구 호출',l:1,n:1,kind:'screen',fault:true,ox:18,oy:6},
    {id:'rag',label:'Knowledge / RAG',sub:'자료 검색 · 문헌 색인',l:2,n:-1,kind:'rag',ox:-32,oy:6},
    {id:'db',label:'PostgreSQL',sub:'업무 상태·시험 증거',l:2,n:1,kind:'cyl',ox:-10,oy:4},
    {id:'qa',label:'QA 조사 · 보고서',sub:'필요시 조사 · QA 보고서',l:3,n:0,kind:'screen',ox:-24,oy:12}
  ];
  const EDGES=[
    ['mcp','harness','done'],
    ['harness','scenario','done'],
    ['scenario','rag','done'],
    ['harness','mfg','done'],
    ['mfg','mcp','fault'],
    ['mfg','db','done'],
    ['mfg','qa','done']
  ];
  const W=760, H=440, S=86, cx=W*0.5, cy=H*0.54;
  const P=(x,y,z=0)=>[+(cx+(x-y)*0.866*S).toFixed(1),+(cy+(x+y)*0.5*S-z*S).toFixed(1)];
  const pos={}; NODES.forEach(nd=>pos[nd.id]=[nd.n*1.15, nd.l*1.15-1.7]);
  const poly=(pts,fill,stroke='none',sw=1,extra='')=>`<polygon points="${pts.map(p=>p.join(',')).join(' ')}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" ${extra}/>`;
  let g=`<defs>
    <linearGradient id="lg-plat-a" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="var(--iso-plat-grad-hi-1, #1e1e24)"/>
      <stop offset="100%" stop-color="var(--iso-plat-grad-hi-2, #141418)"/>
    </linearGradient>
    <linearGradient id="lg-plat-b" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="var(--iso-plat-grad-1, #1a1a20)"/>
      <stop offset="100%" stop-color="var(--iso-plat-grad-2, #101014)"/>
    </linearGradient>
    <filter id="lg-glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>`;
  // Ambient Isometric Telemetry Sweep & Floating Data Dust
  const radarCenter=P(0,0.05,-0.08);
  g+=`<g class="ambient-backdrop" opacity="0.55">
    <ellipse cx="${radarCenter[0]}" cy="${radarCenter[1]}" rx="250" ry="138" fill="none" stroke="var(--iso-plat-rim, #343444)" stroke-width="1" stroke-dasharray="14 10" class="radar-sweep"/>
    <ellipse cx="${radarCenter[0]}" cy="${radarCenter[1]}" rx="185" ry="102" fill="none" stroke="var(--signal, #ff6a3d)" stroke-width="0.9" stroke-dasharray="6 18" class="radar-sweep" opacity="0.45"/>
  </g>`;
  [[-2.1,-1.6,0.4],[-1.6,1.5,0.6],[2.0,-1.1,0.5],[1.9,1.3,0.7],[-0.9,-1.9,0.4],[1.1,-1.7,0.7]].forEach(([sx,sy,sz],idx)=>{
    const sp=P(sx,sy,sz);
    const col=idx%2===0?'var(--signal, #ff6a3d)':'var(--pos, #3fb68b)';
    g+=`<circle cx="${sp[0]}" cy="${sp[1]}" r="${idx%3===0?2.1:1.4}" fill="${col}" opacity="0.55"><animate attributeName="cy" values="${sp[1]};${(sp[1]-9).toFixed(1)};${sp[1]}" dur="${2.6+idx*0.35}s" repeatCount="indefinite"/><animate attributeName="opacity" values="0.2;0.75;0.2" dur="${2.2+idx*0.3}s" repeatCount="indefinite"/></circle>`;
  });
  // Terraced 3D Platforms with Bevels & Coordinate Markers
  [0,1,2,3].forEach(l=>{
    const y0=l*1.15-1.7, a=P(-1.85,y0-0.45), b=P(1.85,y0-0.45), c=P(1.85,y0+0.45), d=P(-1.85,y0+0.45), t=0.14;
    const ad=[a[0],a[1]+t*S], bd=[b[0],b[1]+t*S], cd=[c[0],c[1]+t*S], dd=[d[0],d[1]+t*S];
    const fillTop=l%2?'url(#lg-plat-a)':'url(#lg-plat-b)';
    g+=poly([d,c,cd,dd],'var(--iso-plat-front, #0a0a0d)','var(--iso-plat-edge, #141419)',1)+poly([b,c,cd,bd],'var(--iso-plat-side, #060608)','var(--iso-plat-edge, #141419)',1)+poly([a,b,c,d],fillTop,'var(--iso-plat-top-edge, #272732)',1);
    g+=`<line x1="${d[0]}" y1="${d[1]}" x2="${c[0]}" y2="${c[1]}" stroke="var(--iso-plat-rim, #343444)" stroke-width="1.6"/>`;
    g+=`<line x1="${c[0]}" y1="${c[1]}" x2="${b[0]}" y2="${b[1]}" stroke="var(--iso-plat-rim-side, #282836)" stroke-width="1.4"/>`;
    const mA=P(-1.62,y0+0.36), mB=P(1.62,y0-0.36);
    g+=`<circle cx="${mA[0]}" cy="${mA[1]}" r="1.8" fill="var(--iso-coord-dot, #3a3a4c)"/><circle cx="${mB[0]}" cy="${mB[1]}" r="1.8" fill="var(--iso-coord-dot, #3a3a4c)"/>`;
  });
  // Optical Conduits & Energy Packet Trains
  EDGES.forEach(([s,t,st],i)=>{
    const [x1,y1]=pos[s],[x2,y2]=pos[t], off=st==='fault'?0.18:0;
    const pts=[P(x1+off,y1,0.02),P(x1+off,y2,0.02),P(x2+off,y2,0.02)];
    const d=`M${pts[0]} L${pts[1]} L${pts[2]}`;
    const groove=st==='fault'?'var(--iso-wire-groove-fault, #4a1e14)':st==='done'?'var(--iso-wire-groove-seen, #2a3a34)':'var(--iso-wire-groove-idle, #1e1e28)';
    const col=st==='done'?'var(--iso-wire-seen, #50dfb0)':st==='fault'?'#ff6a3d':'var(--iso-wire-idle, #30303e)';
    g+=`<path d="${d}" fill="none" stroke="var(--iso-track-under, #101015)" stroke-width="4.8" stroke-linecap="round"/>`;
    g+=`<path d="${d}" fill="none" stroke="${groove}" stroke-width="2.4" stroke-linecap="round"/>`;
    g+=`<path id="lg-e${i}" d="${d}" fill="none" stroke="${col}" stroke-width="${st==='fault'?2.2:1.8}" ${st==='fault'?'stroke-dasharray="7 5" class="fault-wire-glitch"':''} opacity="${st==='idle'?0.7:0.95}"/>`;
    if(st==='done'){
      const dur=`${1.9+i*0.32}s`;
      g+=`<circle r="3.4" fill="#50dfb0" filter="url(#lg-glow)"><animateMotion dur="${dur}" repeatCount="indefinite" path="${d}"/></circle>`;
      g+=`<circle r="2.2" fill="#34b38a" opacity="0.75"><animateMotion dur="${dur}" repeatCount="indefinite" path="${d}" begin="0.12s"/></circle>`;
      g+=`<circle r="1.3" fill="#6fd4ab" opacity="0.45"><animateMotion dur="${dur}" repeatCount="indefinite" path="${d}" begin="0.24s"/></circle>`;
    } else if(st==='fault'){
      const m=P(x1+off,(y1+y2)/2,0.02);
      const half=`M${pts[0]} L${m}`;
      g+=`<circle r="4" fill="#ff8a5f" filter="url(#lg-glow)"><animateMotion dur="1.35s" repeatCount="indefinite" path="${half}"/></circle>`;
      g+=`<circle r="2.2" fill="#ff3e14" opacity="0.75"><animateMotion dur="1.35s" repeatCount="indefinite" path="${half}" begin="0.12s"/></circle>`;
      g+=`<g transform="translate(${m[0]}, ${m[1]})"><g class="hazard-node"><circle r="12" fill="var(--iso-hazard-bg, #200d07)" stroke="#ff6a3d" stroke-width="1.8"/><path d="M-4 -4 4 4M4 -4 -4 4" stroke="#ff6a3d" stroke-width="2" stroke-linecap="round"/><circle r="16" fill="none" stroke="#ff6a3d" stroke-width="1.1" stroke-dasharray="3 3"><animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="4s" repeatCount="indefinite"/></circle></g></g>`;
    }
  });
  let labelsHtml='';
  const order=[...NODES].sort((a,b)=>(pos[a.id][0]+pos[a.id][1])-(pos[b.id][0]+pos[b.id][1]));
  order.forEach(nd=>{
    const [x,y]=pos[nd.id], w=0.28, h=nd.kind==='disc'?0.09:nd.kind==='cyl'?0.44:0.35;
    const top=nd.fault?'var(--iso-fault-top, #3d2014)':nd.dim?'var(--iso-node-dim-top, #222227)':'var(--iso-node-default-top, #2b2b34)';
    const left=nd.fault?'var(--iso-fault-left, #2c150c)':nd.dim?'var(--iso-node-dim-left, #17171b)':'var(--iso-node-default-left, #1e1e24)';
    const right=nd.fault?'var(--iso-fault-right, #200e07)':nd.dim?'var(--iso-node-dim-right, #111114)':'var(--iso-node-default-right, #17171c)';
    const st=nd.fault?'#ff6a3d':nd.dim?'var(--iso-node-dim-stroke, #2a2a32)':'var(--iso-node-default-stroke, #3e3e4a)';
    if(nd.fault){
      const c=P(x,y,0);
      g+=`<ellipse class="shock s1" cx="${c[0]}" cy="${c[1]}" rx="${(0.92*S).toFixed(1)}" ry="${(0.53*S).toFixed(1)}" fill="none" stroke="#ff6a3d" stroke-width="1.8"/>`;
      g+=`<ellipse class="shock s2" cx="${c[0]}" cy="${c[1]}" rx="${(0.92*S).toFixed(1)}" ry="${(0.53*S).toFixed(1)}" fill="none" stroke="#ff3e14" stroke-width="1.2"/>`;
      g+=`<ellipse class="shock s3" cx="${c[0]}" cy="${c[1]}" rx="${(0.92*S).toFixed(1)}" ry="${(0.53*S).toFixed(1)}" fill="none" stroke="#ff8a5f" stroke-width="0.9"/>`;
    }
    g+=`<g class="iso-node-group ${nd.fault?'is-fault iso-float':!nd.dim?'iso-float-delayed':''}">`;
    if(nd.kind==='cyl'){
      const c0=P(x,y,0), c1=P(x,y,h), rx=+(w*1.22*S).toFixed(1), ry=+(w*0.7*S).toFixed(1);
      g+=`<ellipse cx="${c0[0]}" cy="${c0[1]}" rx="${rx+3}" ry="${ry+2}" fill="var(--iso-shadow, #08080b)" opacity="0.35"/>`;
      g+=`<path d="M${c0[0]-rx},${c1[1]} L${c0[0]-rx},${c0[1]} A${rx},${ry} 0 0 0 ${c0[0]+rx},${c0[1]} L${c0[0]+rx},${c1[1]} Z" fill="${left}" stroke="${st}" stroke-width="1.2"/>`;
      const rib1=(c0[1]*0.65+c1[1]*0.35).toFixed(1), rib2=(c0[1]*0.35+c1[1]*0.65).toFixed(1);
      g+=`<path d="M${c0[0]-rx},${rib1} A${rx},${ry} 0 0 0 ${c0[0]+rx},${rib1}" fill="none" stroke="${st}" stroke-width="1.3"/>`;
      g+=`<path d="M${c0[0]-rx},${rib2} A${rx},${ry} 0 0 0 ${c0[0]+rx},${rib2}" fill="none" stroke="${st}" stroke-width="1.3"/>`;
      g+=`<ellipse cx="${c1[0]}" cy="${c1[1]}" rx="${rx}" ry="${ry}" fill="var(--iso-db-lid, #27333d)" stroke="#34b38a" stroke-width="1.5"/>`;
      g+=`<ellipse class="dbfill" cx="${c1[0]}" cy="${c1[1]}" rx="${(rx*0.76).toFixed(1)}" ry="${(ry*0.76).toFixed(1)}" fill="#50dfb0" opacity=".42" filter="url(#lg-glow)"><animate attributeName="opacity" values="0.28;0.6;0.28" dur="2.2s" repeatCount="indefinite"/></ellipse>`;
      g+=`<circle cx="${c1[0]}" cy="${c1[1]}" r="2.8" fill="#50dfb0"/>`;
    } else {
      const A=P(x-w,y-w,h), B=P(x+w,y-w,h), C=P(x+w,y+w,h), D=P(x-w,y+w,h), Bd=P(x+w,y-w,0), Cd=P(x+w,y+w,0), Dd=P(x-w,y+w,0);
      const ShA=P(x-w-0.04,y-w,0), ShB=P(x+w+0.04,y-w,0), ShC=P(x+w+0.04,y+w+0.04,0), ShD=P(x-w-0.04,y+w+0.04,0);
      g+=poly([ShA,ShB,ShC,ShD],'var(--iso-shadow, #08080b)','none',0,'opacity="0.35"');
      g+=poly([D,C,Cd,Dd],left,st,1.2)+poly([B,C,Cd,Bd],right,st,1.2)+poly([A,B,C,D],top,st,1.4);
      if(nd.kind==='mcp'){
        // Server rack blades & gateway port on top
        [0.12, 0.23].forEach(zOff=>{
          const rL=P(x-w*0.7,y+w,zOff), rR=P(x+w*0.7,y+w,zOff);
          g+=`<line x1="${rL[0]}" y1="${rL[1]}" x2="${rR[0]}" y2="${rR[1]}" stroke="#50dfb0" stroke-width="1.6" opacity="0.8"/>`;
        });
        const topC=P(x,y,h+0.02);
        g+=`<ellipse cx="${topC[0]}" cy="${topC[1]}" rx="10" ry="5.5" fill="none" stroke="#50dfb0" stroke-width="1.3"/>`;
        g+=`<circle cx="${topC[0]}" cy="${topC[1]}" r="2.4" fill="#50dfb0"/>`;
      }
      if(nd.kind==='rag'){
        // Stacked Knowledge / RAG index plates on top of pedestal
        [0.06, 0.13].forEach((zOff, idx)=>{
          const pA=P(x-w*0.68,y-w*0.68,h+zOff), pB=P(x+w*0.68,y-w*0.68,h+zOff), pC=P(x+w*0.68,y+w*0.68,h+zOff), pD=P(x-w*0.68,y+w*0.68,h+zOff);
          g+=poly([pA,pB,pC,pD],'var(--iso-disc-bg, #16221c)',idx===1?'#50dfb0':'#34b38a',1.3);
        });
        const k1=P(x-w*0.4,y,h+0.15), k2=P(x+w*0.4,y,h+0.15);
        g+=`<line x1="${k1[0]}" y1="${k1[1]}" x2="${k2[0]}" y2="${k2[1]}" stroke="#6fd4ab" stroke-width="1.6" stroke-linecap="round"/>`;
      }
      if(nd.kind==='screen'){
        const s1=P(x-w*0.58,y-w*0.12,h), s2=P(x+w*0.12,y-w*0.12,h), s3=P(x+w*0.12,y-w*0.12,h+0.4), s4=P(x-w*0.58,y-w*0.12,h+0.4);
        const scrStroke=nd.fault?'#ff6a3d':nd.dim?'var(--iso-node-dim-stroke, #282832)':'var(--iso-terminal-stroke, #4e5464)';
        g+=poly([s1,s2,s3,s4],'var(--iso-terminal-bg, #0e1014)',scrStroke,1.4);
        const l1=P(x-w*0.48,y-w*0.12,h+0.29), l2=P(x+w*0.02,y-w*0.12,h+0.29), l3=P(x-w*0.48,y-w*0.12,h+0.19), l4=P(x-w*0.14,y-w*0.12,h+0.19), l5=P(x-w*0.48,y-w*0.12,h+0.10), l6=P(x-w*0.04,y-w*0.12,h+0.10);
        const c1=nd.fault?'#ff8a5f':'#6fd4ab', c2=nd.fault?'#ff6a3d':'#34b38a', c3=nd.fault?'#cc4420':'#227a5d';
        g+=`<g filter="url(#lg-glow)"><path d="M${l1}L${l2}" stroke="${c1}" stroke-width="1.8" class="blink"/><path d="M${l3}L${l4}" stroke="${c2}" stroke-width="1.5"/><path d="M${l5}L${l6}" stroke="${c3}" stroke-width="1.5"/></g>`;
        const haloPos=P(x,y,h+0.55);
        g+=`<ellipse cx="${haloPos[0]}" cy="${haloPos[1]}" rx="${(w*0.88*S).toFixed(1)}" ry="${(w*0.5*S).toFixed(1)}" fill="none" stroke="${nd.fault?'#ff6a3d':'#50dfb0'}" stroke-width="1.2" stroke-dasharray="9 5" class="halo-orbit" opacity="0.85"/>`;
      }
      if(nd.kind==='disc'){
        const c=P(x,y,h+0.03), rxD=+(w*0.82*S).toFixed(1), ryD=+(w*0.46*S).toFixed(1);
        g+=`<ellipse cx="${c[0]}" cy="${c[1]}" rx="${rxD}" ry="${ryD}" fill="var(--iso-disc-bg, #16221c)" stroke="#34b38a" stroke-width="1.6"/>`;
        g+=`<ellipse cx="${c[0]}" cy="${c[1]}" rx="${(rxD*0.64).toFixed(1)}" ry="${(ryD*0.64).toFixed(1)}" fill="none" stroke="#6fd4ab" stroke-width="1.3" stroke-dasharray="7 4" class="halo-orbit-rev"/>`;
        g+=`<circle cx="${c[0]}" cy="${c[1]}" r="3" fill="#50dfb0" filter="url(#lg-glow)"/>`;
      }
      if(nd.fault){
        const b0=P(x,y,h), b1=P(x,y,h+0.58);
        g+=`<line x1="${b0[0]}" y1="${b0[1]}" x2="${b1[0]}" y2="${b1[1]}" stroke="#ff6a3d" stroke-width="1.8" stroke-dasharray="4 4" class="uplink-beam"/>`;
      }
    }
    g+=`</g>`;
    const L=P(x,y,h+(nd.kind==='screen'?0.64:0.48));
    const lx=L[0]+(nd.ox||0), ly=L[1]+(nd.oy||0);
    labelsHtml+=`<div class="nlabel ${nd.fault?'fault':''} ${nd.dim?'dim':''}" style="left:${(lx/W*100).toFixed(1)}%;top:${(ly/H*100).toFixed(1)}%"><span class="nlabel-ico">${ICONS[nd.id]||''}</span><span class="nlabel-body">${esc(nd.label)}<small>${esc(nd.sub)}</small></span></div>`;
  });
  return `<div class="login-art"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${g}</svg><div class="login-labels">${labelsHtml}</div></div>`;
}
function syncShellChrome() {
  const authed=!!state.session;
  const scopeEl=document.getElementById('header-scope');
  const pageEl=document.getElementById('header-page-label');
  const waitEl=document.getElementById('header-approval-pill');
  const userEl=document.getElementById('header-user');
  const modeEl=document.getElementById('header-mode-label');
  const stepNav=document.querySelector('.step-nav');
  const railNav=document.querySelector('.rail-nav');
  if(stepNav) stepNav.hidden=!authed;
  if(railNav) railNav.hidden=!authed;
  document.querySelectorAll('.header-crumb .crumb-sep, #header-scope, #header-page-label').forEach(el=>{el.hidden=!authed;});
  if(scopeEl) scopeEl.textContent=state.registration?.name || ({PURCHASE:'자재 구매 · 발주',PRODUCTION:'생산 일정',QUALITY:'품질 · 출하'}[state.targetType] || '자재 구매 · 발주');
  if(pageEl) pageEl.textContent=state.run && ['live','execution'].includes(page) ? state.run.run_id : (pageCopy[page]?.[0] || '평가 대상');
  if(waitEl) waitEl.hidden=!authed || !(state.run?.status==='WAITING_APPROVAL');
  if(modeEl) modeEl.textContent='API 정상 연결';
  const modeBadge=document.getElementById('header-mode-badge');
  if(modeBadge){
    const dot=modeBadge.querySelector('.pulse-dot');
    if(dot) dot.className='pulse-dot';
  }
  const demoBtn=document.querySelector('.header-end .demo-entry');
  if(demoBtn){
    demoBtn.hidden=!authed;
    demoBtn.textContent='데모 둘러보기';
  }
  if(userEl){
    if(state.session){
      userEl.hidden=false;
      userEl.innerHTML=`<span class="user-chip"><span class="mono">${esc(state.session.user_id)}</span><button type="button" class="chip-logout" data-live-shell-logout>로그아웃</button></span>`;
      const btn=userEl.querySelector('[data-live-shell-logout]');
      if(btn) btn.onclick=()=>{host?.querySelector('[data-live-logout]')?.click();};
    } else {
      userEl.hidden=true;
    }
  }
  const order=['agents','prepare','live','execution','compare'];
  const idx=order.indexOf(page);
  document.querySelectorAll('.step-nav [data-tab]').forEach((btn,i)=>{
    const done = state.session && i < idx;
    btn.classList.toggle('done', done);
    const k=btn.querySelector('.step-k');
    if(k) k.textContent = done ? '✓' : String(i+1);
  });
}
export function mountLive(element, selectedPage='agents', navigate) {
  host=element; page=state.session?selectedPage:'agents'; go=navigate; generation++; loading=false;
  const [title,description]=pageCopy[page];
  const showAuthSplit = !state.session;
  host.innerHTML=`
    <section class="login-split" data-live-auth-split ${showAuthSplit?'':'hidden'}>
      <div class="login-stage">
        <div class="login-copy">
          <div class="login-brand">
            <svg width="26" height="28" viewBox="0 0 26 28" fill="none" aria-hidden="true">
              <path d="M13 1.5 24.5 8v12L13 26.5 1.5 20V8Z" stroke="currentColor" stroke-width="1.8"/>
              <path d="M1.5 8 13 14.5 24.5 8M13 14.5v12" stroke="currentColor" stroke-width="1.6"/>
              <path d="m15.5 4 -3 5 3.2 1.4-2.6 4.6" stroke="#ff6a3d" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span>Crash Lab</span>
          </div>
          <h2 class="login-headline rise">QA 워크스페이스</h2>
          <p class="login-lead rise d1">제조 Agent 장애 주입 및 신뢰성 검증 환경</p>
        </div>
        ${renderLoginTopoSvg()}
        <div class="login-ticker rise d2">
          <div><b>구매 · 생산 · 품질</b><span>Manufacturing Operation Agent (시험 대상)</span></div>
          <div><b>Scenario + RAG</b><span>문헌 검색 기반 시험 설계 · 검토</span></div>
          <div><b>Harness + QA 조사</b><span>장애 주입 · DB 증거 판정 · QA 보고서</span></div>
        </div>
      </div>
      <div class="login-pane">
        <div class="login-pane-head rise d1">
          <h2>워크스페이스 로그인</h2>
          <p class="login-sub">안전한 세션을 위해 브라우저를 새로고침하면 다시 로그인합니다.</p>
        </div>
        <div class="role-presets rise d2" role="group" aria-label="개발 계정 빠른 선택">
          <button type="button" class="role-preset on" data-role-preset="requester-01"><strong>요청자</strong><span class="num">requester-01</span></button>
          <button type="button" class="role-preset" data-role-preset="approver-01"><strong>승인자</strong><span class="num">approver-01</span></button>
        </div>
        <div data-live-account class="rise d3"></div>
      </div>
    </section>

    <div class="workspace-canvas" data-live-workspace ${showAuthSplit?'hidden':''}>
      <div class="page-heading title-row rise">
        <div>
          <span class="eyebrow">CONNECTED WORKSPACE</span>
          <h1>${title}</h1>
          <p class="finding">${description}</p>
        </div>
        <div class="heading-actions">
          ${page==='agents'?'<button type="button" class="secondary" data-live-open-register>+ Agent 등록</button>':''}
          ${badge('실제 API')}
        </div>
      </div>
      <p class="live-message" data-live-message role="status" aria-live="polite"></p>
      <section class="live-guidance" data-live-guidance aria-label="현재 단계와 다음 행동"></section>

      <div class="live-layout" data-page="${page}">
        <section class="live-content">
          <div class="targets-split" ${page==='agents'?'':'hidden'}>
            <section data-live-target class="card targets-card rise d1">
              <div class="card-h"><h2>제조 업무 유형</h2><span class="meta">3개 · 참조 Agent</span></div>
              <div data-live-targets class="live-targets"><p class="empty-inline">로그인하면 서버의 시험 목록을 불러옵니다.</p></div>
            </section>
            <aside class="card targets-side rise d2">
              <div class="card-h">
                <h2>최근 실행</h2>
                <div class="card-h-end">
                  <span class="meta num" data-live-user-tag>requester-01</span>
                  <button type="button" class="ghost-sm" data-live-refresh>새로고침</button>
                </div>
              </div>
              <div data-live-history class="live-history"></div>
              <div class="targets-next">
                <p data-live-selected-summary><b class="text-strong">자재 구매 · 발주</b>를 선택했습니다. 다음 단계에서 기능 · 근거 · 제안 시험을 확인합니다.</p>
                <div class="live-flow-actions"><button class="primary full-cta" data-live-go="prepare" data-live-next disabled><span>시험 설계로</span><span>→</span></button></div>
              </div>
            </aside>
          </div>

          <div data-qa-registration-area class="rise d3" ${page==='agents'?'':'hidden'}>${registrationMarkup()}</div>

          <div class="prepare-work-grid" data-page-mode="${page}" ${['prepare','live','execution'].includes(page)?'':'hidden'}>
            <div class="prepare-main-col">
              <section data-live-design-area class="card section-pad rise d1" ${page==='prepare'?'':'hidden'}>
                <div class="card-head-inline">
                  <div>
                    <span class="step-eyebrow">01 / SCENARIO DESIGN</span>
                    <h2>Agent를 보고 시험 설계</h2>
                  </div>
                  <span class="pill sig">분석 → 근거 → 시험</span>
                </div>
                <p class="live-hint">기능과 근거를 확인해 위험 상황을 만들고, 실행 가능한지 검사합니다.</p>
                <div data-qa-selected></div>
                <form data-live-design class="design-form-grid">
                  <label>설계할 예시 Agent
                    <select name="target_type" data-live-design-type>
                      <option value="PURCHASE">자재 구매·발주</option>
                      <option value="PRODUCTION">생산 일정</option>
                      <option value="QUALITY">품질·출하</option>
                    </select>
                  </label>
                  <label>시험 생성 방식
                    <select name="generation_mode">
                      <option value="llm">LLM으로 새로운 상황 생성</option>
                      <option value="offline">기존 시험 예시 사용</option>
                    </select>
                  </label>
                  <button type="submit" class="primary">Agent 분석·시험 설계 →</button>
                </form>
                <div data-live-design-results></div>
              </section>

              <div data-live-approval class="rise d1" ${page==='live'?'':'hidden'}></div>

              <div data-live-summary class="card section-pad rise d2" ${['live','execution'].includes(page)?'':'hidden'}>
                <div class="empty-stage-box">
                  <span class="empty-kicker">READY TO INSPECT</span>
                  <h2>실행을 선택하거나 새 시험을 시작해 주세요</h2>
                  <p class="live-hint">저장된 실행 기록을 선택해 3D 실행 흐름과 Agent–DB 상태 대조표를 확인하거나, 새 시험을 시작합니다.</p>
                  <div class="live-flow-actions">
                    <button class="primary" data-live-go="prepare">시험 설계로 이동 →</button>
                    <button class="secondary" type="button" data-live-open-3d-demo>◈ S03 응답 유실 3D 데모 바로 보기</button>
                  </div>
                </div>
              </div>

              <details class="card knowledge-drawer rise d2" ${page==='prepare'?'':'hidden'}>
                <summary class="drawer-summary">
                  <span>03 / 근거 자료 직접 검색 (Parent–Child · BGE)</span>
                  <span class="pill neu">RAG Vector Search</span>
                </summary>
                <section data-live-knowledge-area class="section-pad" ${page==='prepare'?'':'hidden'}>
                  <div class="live-row"><h2>제조업 근거 찾기</h2><span class="badge">Parent–Child · BGE</span></div>
                  <p class="live-hint">영어로 검색하세요. 작은 문단을 검색하고 해당 페이지의 큰 문맥을 함께 보여줍니다. 검색 근거는 시험 설계의 참고 자료이며 판정 정답은 아닙니다.</p>
                  <form data-live-knowledge class="knowledge-form-grid">
                    <label class="span-2">검색 질문<input name="query" value="${esc(state.knowledge?.query || 'duplicate purchase orders after timeout and retry')}" minlength="2" maxlength="1000" required></label>
                    <label>업무<select name="target_type"><option value="PURCHASE">자재 구매·발주</option><option value="PRODUCTION">생산</option><option value="QUALITY">품질</option><option value="COMMON">전체</option></select></label>
                    <button class="secondary" type="submit">전문자료 검색</button>
                  </form>
                  <p data-live-knowledge-status class="live-hint"></p>
                  <div data-live-knowledge-results></div>
                </section>
              </details>

              <details data-live-manual class="card manual-drawer rise d3" ${['prepare','live'].includes(page)?'':'hidden'} ${page==='live'?'open':''}>
                <summary class="drawer-summary" ${page==='prepare'?'':'hidden'}>
                  <span>직접 시나리오 설정 (개발용)</span>
                  <span class="mono dim">S01–S04 · B0/B1</span>
                </summary>
                <section data-live-setup class="section-pad" ${['prepare','live'].includes(page)?'':'hidden'}>
                  <div class="live-row">
                    <div>
                      <span class="step-eyebrow">${page==='prepare'?'MANUAL OVERRIDE':'01 / SINGLE TRIAL EXECUTION'}</span>
                      <h2>${page==='prepare'?'시험 조건 설정':'선택한 시험 실행'}</h2>
                    </div>
                    <button class="secondary" data-live-go="agents">평가 대상 변경</button>
                  </div>
                  <p data-live-draft-agent class="draft-agent-tag"></p>
                  <div data-live-design-selected></div>
                  <form data-live-start>
                    <div class="form-row-2">
                      <label>시험 시나리오<select name="test_id" required><option>로그인 후 불러옵니다</option></select></label>
                      <label>서버 정책<select name="system_id"><option value="B0">B0</option><option value="B1">B1</option></select></label>
                    </div>
                    <p class="live-hint" data-live-kind></p>
                    <fieldset data-live-data hidden>
                      <legend>시험 데이터</legend>
                      <label class="checkbox-row"><span><input type="checkbox" name="custom_data" ${state.trialData.enabled?'checked':''}> 수량·재고·가격 변경</span></label>
                      <div data-live-data-fields class="form-row-3" ${state.trialData.enabled?'':'hidden'}>
                        <label>구매 수량<input name="quantity" type="number" min="1" max="2147483647" step="1" value="${state.trialData.quantity}" required></label>
                        <label>초기 재고<input name="inventory" type="number" min="0" max="2147483647" step="1" value="${state.trialData.inventory}" required></label>
                        <label>개당 가격 (원)<input name="unit_price_minor" type="number" min="0" max="2147483647" step="1" value="${state.trialData.unit_price_minor}" required></label>
                        <p class="live-hint span-3">저장한 QA 계획의 데이터로 실행합니다. 현재는 재고가 부족한 구매 요청을 지원합니다.</p>
                      </div>
                    </fieldset>
                    <button class="primary full-cta" type="submit" disabled><span>${page==='prepare'?'이 조건으로 실행 준비':'시험 시작'}</span><span>→</span></button>
                  </form>
                </section>
              </details>
            </div>

            <aside class="prepare-side-col">
              <section data-live-batch-area class="card section-pad rise d2" ${['prepare','live','execution'].includes(page)?'':'hidden'}>
                <div class="card-head-inline">
                  <div>
                    <span class="step-eyebrow">02 / BATCH EXPERIMENT</span>
                    <h2>실험 계획 실행</h2>
                  </div>
                  <span class="pill neu">반복 · 예산 통제</span>
                </div>
                <p class="live-hint">정상 대조와 위험 시험을 실행합니다. 승인과 중단 기준을 적용합니다.</p>
                <form data-live-batch-form class="batch-form">
                  <label>설계 시험<select name="case_id" required></select></label>
                  <div class="form-row-2">
                    <label>서버 정책<select data-live-batch-system><option value="B0">B0 · 업무 방어 미적용</option><option value="B1">B1 · 업무 방어 적용</option></select></label>
                    <label>목적<select name="mode"><option value="SMOKE">기본 연결 점검 · 조건별 1회</option><option value="RELIABILITY">LLM 반복 검증 · 정책 계산 횟수</option></select></label>
                  </div>
                  <div class="form-row-3">
                    <label>최대 횟수<input name="max_runs" type="number" min="1" max="300" value="8" required></label>
                    <label>최대 시간(초)<input name="max_seconds" type="number" min="1" max="3600" value="900" required></label>
                    <label>비용 한도($)<input name="max_cost_usd" type="number" min="0" max="1" step="0.01" value="1" required></label>
                  </div>
                  <p class="live-hint">정상 처리와 위험 조건을 함께 실행합니다. 비용 한도는 공유 모델 예산에도 적용됩니다.</p>
                  <button class="primary full-cta" type="submit"><span>설계한 실험 시작</span><span>→</span></button>
                </form>
                <div data-live-batch-results></div>
              </section>
            </aside>
          </div>
          <section data-live-compare-area class="card section-pad rise d1" ${page==='compare'?'':'hidden'}>
            <div class="card-head-inline">
              <div>
                <span class="step-eyebrow">05 / POLICY &amp; RUN COMPARISON</span>
                <h2>비교할 실제 실행</h2>
              </div>
              <button type="button" class="secondary" data-live-open-compare-demo>◈ S03 B0 ↔ B1 비교 데모 바로 보기</button>
            </div>
            <p class="live-hint">같은 시나리오의 완료된 실행을 고르세요. 서버 정책과 Agent 버전 등 달라진 조건을 함께 확인합니다.</p>
            <form data-live-compare class="live-compare-form"><label>왼쪽 실행 (기준)<select name="left" required></select></label><label>오른쪽 실행 (비교)<select name="right" required></select></label><button class="primary" type="submit">실제 결과 비교 →</button></form>
          </section>
          <div data-live-comparison class="rise d2" ${page==='compare'?'':'hidden'}></div>
          <section class="card section-pad live-analysis-shell" data-live-analysis hidden>
            <div class="live-row analysis-top-bar">
              <div>
                <span class="step-eyebrow">3D TOPOLOGY &amp; EVENT TRACE</span>
                <h2>실행 흐름</h2>
              </div>
              <div class="live-row">
                <span class="mono dim" data-live-count></span>
                <button class="secondary" data-live-play>재생</button>
                <button class="secondary" data-live-export>근거 JSON 내보내기</button>
              </div>
            </div>
            <div class="live-stage-grid">
              <div class="live-stage-col">
                <div id="live-scene" class="live-scene" aria-label="실제 이벤트 기반 서비스 구조"></div>
                <label class="scrubber-wrap">확인할 이벤트 순서<input data-live-cursor type="range" min="0" value="0" aria-label="확인할 이벤트 순서"></label>
              </div>
              <aside class="live-inspector-col">
                <div class="inspector-subhead"><h3>실행 이벤트</h3><span class="meta">클릭하여 시점 이동</span></div>
                <div data-live-events class="live-events" aria-label="실행 이벤트"></div>
                <div class="inspector-subhead"><h3>선택한 근거</h3><span class="meta mono">RAW PAYLOAD</span></div>
                <pre data-live-evidence tabindex="0"></pre>
              </aside>
            </div>
            <div data-live-divergence></div>
          </section>
          <section data-live-result hidden></section>
        </section>
      </div>
    </div>`;
  host.onsubmit=submit;
  host.onclick=click;
  host.oninput=event=>{
    if(event.target.name==='tools_json'){
      $('[data-qa-tools]').innerHTML='';$('[data-qa-capabilities]').innerHTML='';
    }
  };
  $('[data-qa-tool-file]').onchange=async event=>{
    try{const file=event.target.files[0];if(!file)return;if(file.size>100000)throw new Error('100 KB 이하의 파일을 선택하세요.');
      const text=await file.text();parseTools(text);$('[name=tools_json]').value=text;
      renderToolBindings($('[data-qa-registration]'),state.capabilityOptions);notify('도구를 읽었습니다. 조회·변경과 업무 기능 연결을 확인하세요.');
    }catch(error){failure(error);}
  };
  $('[data-live-start] [name=test_id]').onchange=selectTest;
  $('[name=system_id]').onchange=e=>{state.draft.system_id=e.target.value;$('[data-live-batch-system]').value=e.target.value;};
  $('[data-live-batch-system]').value=state.draft.system_id;
  $('[data-live-batch-system]').onchange=e=>{state.draft.system_id=e.target.value;$('[name=system_id]').value=e.target.value;};
  $('[data-live-design-type]').value=state.targetType;
  $('[data-live-design-type]').onchange=e=>selectTargetType(e.target.value);
  $('[name=custom_data]').onchange=e=>{state.designCaseId=null;state.trialData.enabled=e.target.checked;$('[data-live-data-fields]').hidden=!e.target.checked;for(const input of $('[data-live-data]').querySelectorAll('input[type=number]'))input.disabled=!e.target.checked;};
  for(const name of ['quantity','inventory','unit_price_minor'])$(`[name=${name}]`).oninput=e=>{state.designCaseId=null;state.trialData[name]=e.target.value;};
  for(const name of ['left','right'])$(`[name=${name}]`).onchange=e=>{state.compareDraft[name]=e.target.value;state.comparison=null;$('[data-live-comparison]').innerHTML='';actionHint();};
  $('[data-live-cursor]').oninput=e=>{stopReplay();state.selected=Number(e.target.value);renderEvents();};
  renderRegistrations(); account(); history(); guidance(); renderKnowledge(); renderDesign(); renderBatch();
  if(state.catalog)catalog();
  if(state.run)renderRun(true);
  if(state.comparison)$('[data-live-comparison]').innerHTML=comparisonView(state.comparison);
  if(state.session)refreshBatch().catch(failure);
  if(state.session)refresh().then(()=>{if(state.pendingRunId){const id=state.pendingRunId;state.pendingRunId=null;return openRun(id);}if(state.run)return poll();}).catch(failure);
}
function guidance() {
  const area=$('[data-live-guidance]');if(!area)return;
  let info;
  if(!state.session) info={title:'먼저 개발 계정으로 로그인해 주세요',detail:'로그인하면 시험 목록과 저장된 실행 기록을 불러옵니다.'};
  else if(state.pendingStart) info={title:'실행 요청을 보내고 있습니다',detail:'중복 실행을 막기 위해 시작 버튼을 잠시 잠갔습니다. 접수되면 실행 번호와 진행 상태를 표시합니다.'};
  else if(state.run && !state.settled && ['agents','prepare'].includes(page)) info={title:'이미 실행 중인 시험이 있습니다',detail:`${state.run.run_id}의 진행 상태를 먼저 확인해 주세요. 실행이 끝난 뒤 새 시험을 시작할 수 있습니다.`,action:'현재 실행으로 돌아가기 →',page:'live'};
  else if(state.registration && !registeredCaseReady(state.registration,state.designPlan,state.designCaseId) && page==='live' && !state.run) info={title:'이 Agent는 실행 연결이 필요합니다',detail:'현재는 설명을 바탕으로 시험안을 만들 수 있습니다. 업무 정책·시험 환경·판정 코드를 연결한 뒤 실행합니다.',action:'시험안으로 돌아가기 →',page:'prepare'};
  else if(state.run && ['live','execution'].includes(page)) info=runGuidance(state.run,state.settled);
  else info={
    agents:{title:state.registration?`선택 대상: ${state.registration.name}`:`${state.targetTypes.find(t=>t.type_id===state.targetType)?.name || '자재 구매·발주'} 유형이 선택돼 있습니다`,detail:'실행 가능 여부와 대표 위험을 확인한 뒤 시험을 설계해 주세요.',action:'시험 설계 →',page:'prepare'},
    prepare:{title:'Agent의 기능부터 확인합니다',detail:'시험을 설계한 뒤 실행 가능한 시험과 반복 횟수를 선택하세요.'},
    live:{title:'실행 준비가 됐습니다 · 아직 시작하지 않았습니다',detail:`${agentName(state.draft.agent)} · ${state.draft.test_id} 조건을 확인한 뒤 아래 시험 시작을 눌러 주세요.`},
    execution:{title:'확인할 실행을 선택해 주세요',detail:'왼쪽 실행 기록을 선택하면 진행 기록과 검사 결과를 볼 수 있습니다.',action:'새 시험 준비 →',page:'prepare'},
    compare:{title:'같은 시나리오의 완료된 실행 두 개를 선택해 주세요',detail:'완료된 실행 두 개를 고른 뒤 실제 결과 비교를 누르세요. Agent 단독 시험은 비교 대상에 포함되지 않습니다.'}
  }[page];
  const key=JSON.stringify([page,info]);if(area.dataset.key===key){actionHint();return;}area.dataset.key=key;
  const steps=['agents','prepare','live','execution'];
  area.innerHTML=`<ol class="live-steps" aria-label="시험 진행 단계">${steps.map((step,i)=>`<li><button type="button" data-live-go="${step}" ${step===page?'aria-current="step"':''}>${i+1}. ${pageCopy[step][0]}</button></li>`).join('')}</ol><div class="live-guidance-copy" role="status" aria-live="polite" aria-atomic="true"><strong>${esc(info.title)}</strong><p>${esc(info.detail)}</p></div>${info.action && info.page!==page?`<button class="primary" data-live-go="${info.page}">${esc(info.action)}</button>`:''}${page==='live' && state.run?.status==='WAITING_APPROVAL'?'<button class="primary" data-live-show-approval>승인 요청 확인 ↓</button>':''}${page==='execution' && state.settled?'<button class="primary" data-live-show-results>검사 결과·보고서로 이동 ↓</button>':''}`;
  actionHint();
}
function actionHint() {
  const hint=nextActionHint({page,...state});
  const target=hint && $(hint.selector);
  const previous=$('[data-action-hint-anchor]');
  if(previous && target===previous.lastElementChild && previous.firstElementChild.textContent===hint?.text)return;
  if(previous){const control=previous.lastElementChild;control.removeAttribute('aria-describedby');previous.replaceWith(control);}
  if(!target || target.disabled || target.closest('[hidden]'))return;
  const anchor=document.createElement('div');anchor.className='live-action-anchor';anchor.dataset.actionHintAnchor='';
  const bubble=document.createElement('p');bubble.className='live-action-bubble';bubble.id='live-next-action-hint';bubble.textContent=hint.text;
  target.before(anchor);anchor.append(bubble,target);target.setAttribute('aria-describedby',bubble.id);
}
function selectTargetType(kind) {
  if(state.registration){state.registration=null;state.designPlan=null;state.designCaseId=null;state.batchRequest=null;}
  if(state.targetType!==kind){state.designPlan=null;state.designCaseId=null;state.batchRequest=null;}
  state.targetType=kind;
  $('[data-live-design-type]').value=kind;
  targets();renderDesign();renderBatch();selectedDesign();
}
function renderRegistrations() {
  const area=$('[data-qa-profiles]');if(!area)return;
  const seen=new Set(),latest=[],previous=[];
  for(const p of state.registrations){const key=JSON.stringify([p.name,p.version]);(seen.has(key)?previous:latest).push(p);seen.add(key);}
  const row=p=>`<button type="button" class="secondary" data-qa-profile="${esc(p.profile_id)}" aria-pressed="${state.registration?.profile_id===p.profile_id}">${esc(p.name)} · ${esc(p.version)} · ${p.execution_binding && p.execution_status==='CONNECTED'?'실행기 연결':p.can_design?'설계 가능':'정보 보완'} · ${esc(p.profile_id.slice(-6))}</button>`;
  area.innerHTML=latest.length?latest.map(row).join(''):'<p class="live-hint">아직 등록한 Agent가 없습니다. 예시를 불러오거나 새 정보를 입력하세요.</p>';
  if(previous.length)area.innerHTML+=`<details ${previous.some(p=>p.profile_id===state.registration?.profile_id)?'open':''}><summary>이전 등록 기록 ${previous.length}개</summary>${previous.map(row).join('')}</details>`;
  if(state.registration)area.innerHTML+=profileAnalysis(state.registration,state.capabilityOptions);
  const selected=$('[data-qa-selected]');
  if(selected)selected.innerHTML=state.registration?`<p><strong>선택 대상: ${esc(state.registration.name)}</strong> · ${esc(state.registration.version)}</p><p class="live-hint">${state.registration.execution_binding?`실제 실행 대상: ${esc(state.registration.execution_binding.name)} · ${esc(state.registration.execution_binding.execution_profile.agent_version)} · 등록한 시험 데이터 사용`:'등록한 설명으로 시험안을 만듭니다. 실행 환경은 아직 연결되지 않았습니다.'}</p>`:'';
  $('[data-live-manual]').hidden=!['prepare','live'].includes(page) || !!state.registration && (page==='prepare' || !registeredCaseReady(state.registration,state.designPlan,state.designCaseId));
  $('[data-live-start] [name=test_id]').disabled=!!state.registration;
  const form=$('[data-live-design]');
  form.querySelector('label').hidden=!!state.registration;
  form.querySelector('button').disabled=!!state.registration && !state.registration.can_design;
}
function targets() {
  renderRegistrations();
  $('[data-live-draft-agent]').textContent=`평가 대상: ${agentName(state.draft.agent)}`;
  const defaultTypes=[
    {type_id:'PURCHASE',name:'자재 구매 · 발주',description:'재고를 조회하고 담당자 승인 이후 부품을 발주합니다.',execution:'READY',checks:['승인 통제','중복 발주 방지']},
    {type_id:'PRODUCTION',name:'생산 일정',description:'설비 가용성과 납기를 보고 생산 계획 변경안을 제안합니다.',execution:'READY',checks:['일정 충돌','설비 정합성']},
    {type_id:'QUALITY',name:'품질 · 출하',description:'검사 결과를 근거로 출하 보류 또는 승인을 제안합니다.',execution:'READY',checks:['근거 완전성','보류 준수']}
  ];
  const types=state.targetTypes.length?state.targetTypes:defaultTypes;
  const lastRunFor=typeId=>{
    const prefixes={PURCHASE:['S0','PA'],PRODUCTION:['P0','PN'],QUALITY:['Q0','QL']}[typeId]||[];
    return state.runs.find(r=>prefixes.some(p=>String(r.test_id||'').startsWith(p)));
  };
  $('[data-live-targets]').innerHTML=types.map(type=>{
    const meta=targetTypeMeta[type.type_id]||targetTypeMeta.PURCHASE;
    const isOn=!state.registration && state.targetType===type.type_id;
    const last=lastRunFor(type.type_id);
    const failCount=last?.summary?.FAIL || 0;
    const passCount=last?.summary?.PASS || 0;
    const pillHtml=!last
      ? `<span class="pill neu">${type.execution==='READY'?'실행 대기':'설계 전용'}</span>`
      : failCount
        ? `<span class="pill neg">${failCount} 실패</span>`
        : passCount
          ? `<span class="pill pos">${passCount} 통과</span>`
          : `<span class="pill neu">${esc(last.status)}</span>`;
    const runSub=last?`${esc(last.run_id)} · ${esc(last.test_id)}`:(type.execution==='READY'?'참조 실행 가능':'시험 설계 가능');
    return `<button type="button" class="live-target target-row ${isOn?'selected on':''}" data-live-target-type="${esc(type.type_id)}" aria-pressed="${isOn}">
      <div class="target-main">
        <h3>${esc(type.name)} ${meta.badge?`<span class="pill sig">${esc(meta.badge)}</span>`:''}</h3>
        <p>${esc(type.description)}</p>
        <div class="scn">${meta.scenarios.map(s=>`<span class="${s.fault?'f':''}">${esc(s.code)}</span>`).join('')}</div>
      </div>
      ${renderChainSvg(meta.chain,meta.faultIndex)}
      <div class="target-last">${pillHtml}<span class="num">${runSub}</span></div>
    </button>`;
  }).join('')+`<details class="dev-agent-details"><summary>개별 Agent 점검 (개발용)</summary><div class="dev-agent-row">${['purchase','investigator'].map(agent=>`<button type="button" class="secondary" data-live-agent="${agent}">${agentName(agent)} · ${testsForAgent(state.catalog || {tests:[]},agent).length}개 시험</button>`).join('')}</div></details>`;
  const selectedName=state.registration?state.registration.name:(types.find(t=>t.type_id===state.targetType)?.name || '자재 구매 · 발주');
  const sumEl=$('[data-live-selected-summary]');
  if(sumEl) sumEl.innerHTML=`<b class="text-strong">${esc(selectedName)}</b>${state.registration?' 프로필을':' 유형을'} 선택했습니다. 다음 단계에서 기능 · 근거 · 제안 시험을 확인합니다.`;
  $('[data-live-next]').disabled=!state.session || !state.targetTypes.length;
  syncShellChrome();
  guidance();
}

function renderKnowledge() {
  const area=$('[data-live-knowledge-results]');if(!area)return;
  const data=state.knowledge;
  $('[data-live-knowledge-status]').textContent=state.knowledgeStatus ? `${state.knowledgeStatus.counts.document}개 자료 · ${state.knowledgeStatus.counts.parent}개 큰 문맥 · ${state.knowledgeStatus.counts.child}개 검색 문단 · ${state.knowledgeStatus.index?.model || ''}` : '';
  if(!data){area.innerHTML='';return;}
  $('[data-live-knowledge] [name=target_type]').value=data.target_type;
  area.innerHTML=`<p class="live-hint">${esc(data.model)} · ${esc(data.results.length)}개 문맥. 구매 검색은 다음 가변 데이터 시험 계획에 출처를 기록합니다. 시험 조건은 아직 등록된 양식으로 구성합니다.</p>`+data.results.map(hit=>`<article class="live-knowledge-hit"><h3>${esc(hit.title)}</h3><p class="live-hint">${esc(hit.location)} · ${hit.content_kind==='PDF_TEXT'?'PDF 원문':'자체 작성 요약'} · ${esc(hit.source_id)}</p><p>${esc(hit.matched_text)}</p><details><summary>큰 문맥과 출처 확인</summary><pre>${esc(hit.parent_text)}</pre><p class="live-hint">${esc(hit.scope)}</p><p class="live-hint">${esc(hit.source_url)}</p></details></article>`).join('');
}

function renderDesign() {
  const area=$('[data-live-design-results]'), plan=state.designPlan;if(!area)return;
  if(!plan){area.innerHTML='';return;}
  const analysis=plan.design.analysis, names={PURCHASE:'자재 구매·발주',PRODUCTION:'생산 일정',QUALITY:'품질·출하',COMMON:'분류 확인 필요'};
  const sourceNames={RESEARCH:'Agent 연구',INCIDENT:'실제 제조업 사례',TECHNICAL:'공식 기술 문서',PROJECT_POLICY:'프로젝트 예시 정책',REFERENCE:'기존 참고 자료'};
  const scopeNames={APPLICABLE:'적용 가능',NEEDS_INFORMATION:'추가 정보 필요',OUT_OF_SCOPE:'범위 밖'};
  const screening=(analysis.risk_screening || []).map(r=>`<tr><td>${esc(r.title)}</td><td>${esc(scopeNames[r.status])}</td><td>${esc(r.reason)}${r.missing_capabilities.length?`<br><small>${esc(r.missing_capabilities.map(n=>capabilityLabel(n,state.capabilityOptions)).join(', '))}</small>`:''}</td></tr>`).join('');
  area.innerHTML=`<p><strong>${esc(names[analysis.target_type])}</strong> · ${esc(plan.design.model_kind==='offline'?'규칙 기반 설계':plan.design.model_kind==='injected_model'?'모의 LLM 응답 검증':'LLM 상황·데이터 생성')}</p>
    <p class="live-hint">${plan.design.registration?`${esc(plan.design.registration.name)} · ${plan.design.registration.execution_binding?'선택한 실행기와 해당 업무의 예시 정책에 연결된 시험입니다.':'설명으로 만든 시험안입니다. 실행에는 업무 정책·시험 환경·판정 코드 연결이 필요합니다.'}`:'제조 운영 예시 · 시험용 환경'}</p>${repairMarkup(plan.design.repair)}<p>Scenario Agent가 정상 업무에 예외를 적용해 시험안을 만들었습니다. 위험 유형 ${(analysis.risk_screening || []).filter(r=>r.status==='APPLICABLE').length}종을 바탕으로 시험 조건 ${plan.cases.filter(c=>c.design_basis).length}개를 구성했습니다.</p>${analysis.manufacturing_context?`<details><summary>제조 운영 기준</summary><p>${esc(analysis.manufacturing_context.scope)}</p><ul>${analysis.manufacturing_context.features.map(f=>`<li><strong>${esc(f.name)}</strong> · ${esc(f.question)}</li>`).join('')}</ul><p class="live-hint">업무 상태의 모의 시험 · 설비 실시간 제어·여러 Agent 동시 충돌은 미검증</p></details>`:''}<details><summary>위험 선정 근거</summary><div class="live-table-wrap"><table class="live-table"><thead><tr><th>위험 유형</th><th>대상 적합성</th><th>이유</th></tr></thead><tbody>${screening}</tbody></table></div></details>`+
    plan.cases.filter(c=>c.design_basis).map(c=>`<article class="live-design-case"><h3>${esc(c.hypothesis)}</h3><p>${badge(c.execution.status==='READY'?'실행 가능':'추가 구현 필요')}</p><p class="live-hint">${c.design_basis.execution_data_origin==='VALIDATED_MODEL_DATA'?'모델 생성 데이터를 검증해 적용 · 실행 전':c.design_basis.execution_data_origin==='NOT_APPLIED'?'제안 데이터 미적용 · 실행 보류':'등록된 시험 예시 사용'}</p>${scenarioMarkup(c.design_basis)}<p><strong>확인할 실패:</strong> ${esc(c.design_basis.failure_mode)}</p>${c.execution.status!=='READY'?`<p class="live-hint">필요한 연결: ${esc((c.execution.missing_capabilities || []).map(x=>capabilityLabel(x,state.capabilityOptions)).join(' · '))}</p>`:''}


      ${c.evaluation_strategy?.control_difference?`<p>${esc(c.evaluation_strategy.control_difference)}</p>`:''}

      ${reviewMarkup(c.evaluation_strategy?.review)}
      <details><summary>근거·판정 기준·시험 데이터</summary><p><strong>기대 행동 (제안):</strong> ${esc(c.design_basis.expected_behavior_candidate)}</p>${c.evaluation_strategy?`<p><strong>${esc({P0:'필수 점검',P1:'우선 점검',P2:'일반 점검'}[c.evaluation_strategy.priority])}</strong> · ${esc(c.evaluation_strategy.business_impact)} · 반복 권고(미실행) <strong>${c.evaluation_strategy.trial_design.recommended_repetitions}회</strong></p>`:''}<p class="live-hint">근거 구성: ${esc(Object.entries(c.design_basis.evidence_groups || {}).filter(([,refs])=>refs.length).map(([kind,refs])=>`${sourceNames[kind]} ${new Set(refs).size}건`).join(' · '))}</p><p>${esc(c.design_basis.rationale)}</p><p>${esc(c.execution.reason || '')}</p><p>판정 규칙: ${esc(c.execution.rule_ids.join(', ') || '판정 코드 연결 필요')}</p><p>${esc(c.design_basis.incident_note || '')}</p><p>입력 변경: ${esc(c.design_basis.changes.map(x=>`${x.field}: ${JSON.stringify(x.before)} → ${JSON.stringify(x.after)}`).join(' / ') || '없음')}</p>${c.design_basis.sources.map(ref=>`<p><strong>${esc(sourceNames[ref.source_type] || '참고 자료')}</strong> · ${esc(ref.title)} · ${esc(ref.location)} · ${esc(ref.content_kind)}</p><blockquote>${esc(ref.matched_text)}</blockquote><p class="live-hint">${esc(ref.scope)}${ref.policy_status?` · 정책 상태: ${esc(ref.policy_status==='DRAFT'?'미채택 초안':'해당 참조 환경에 채택')}`:''}</p><p class="live-hint">${esc(ref.source_url)}</p>`).join('')}
      <p>아래는 제안한 추가 조건입니다. 실제 주입된 상태와 구분합니다.</p><pre>${json(c.design_basis.proposed_test_data)}</pre><p class="live-hint">${esc(c.design_basis.evidence_review)}</p></details>
      ${c.execution.status==='READY'?`<button class="secondary" data-live-use-design="${esc(c.case_id)}">이 시험 선택</button>`:''}</article>`).join('')+
    `<details><summary>분석 과정 (개발용)</summary><pre>${json({unknowns:analysis.unknowns,steps:plan.design.trace})}</pre></details>`;
}

function renderBatch() {
  const form=$('[data-live-batch-form]'), area=$('[data-live-batch-results]');if(!form || !area)return;
  const selected=form.case_id.value;
  const cases=state.designPlan?.cases.filter(c=>c.design_basis && c.execution.status==='READY' && c.evaluation_strategy) || [];
  form.hidden=!cases.length;
  form.case_id.innerHTML=cases.map(c=>`<option value="${esc(c.case_id)}">${esc(c.hypothesis)}</option>`).join('');
  if(cases.some(c=>c.case_id===selected))form.case_id.value=selected;
  form.querySelector('button').disabled=!state.session || !cases.length || !!(state.batch && ['RUNNING','WAITING_APPROVAL','STOPPING'].includes(state.batch.status));
  const b=state.batch;
  const active=b && ['RUNNING','WAITING_APPROVAL','STOPPING'].includes(b.status);
  if(!b || (page==='prepare' && !active && b.plan_id!==state.designPlan?.plan_id)){area.innerHTML=`<p class="live-hint">${state.designPlan && !cases.length?'이 유형은 시험 설계만 지원합니다. 실행 환경과 판정 코드를 추가해야 합니다.':'실행 가능한 시험을 설계하면 실험 조건이 표시됩니다.'}</p>`;return;}
  const labels={RUNNING:'실험 진행 중',WAITING_APPROVAL:'담당자 승인 대기',STOPPING:'현재 실험 종료 후 중단',STOPPED:'추가 실험 중단',COMPLETED:'계획한 실험 완료',INTERRUPTED:'서비스 재시작으로 중단',ERROR:'실험 실행 오류'};
  const reasons={RULE_FAILURE:'판정 규칙 위반 발견',RUN_LIMIT:'실행 횟수 한도',TIME_LIMIT:'시간 한도',COST_LIMIT:'비용 한도',USER_STOP:'사용자 중단 요청',INSUFFICIENT_OBSERVATION:'관측 근거 부족',RUN_ERROR:'개별 실험 오류',EXECUTION_PROFILE_CHANGED:'대상 실행 설정 변경',EXECUTION_VERSION_CHANGED:'실행 버전 불일치'};
  const results={FAIL:'위반 발견',NO_VIOLATION_OBSERVED:'시험 범위에서 위반 미관측',INSUFFICIENT_EVIDENCE:'추가 검증 필요'};
  const previous=!active && state.run && state.run.qa_batch_id!==b.batch_id;
  area.innerHTML=`${previous?'<details><summary>이전 실험 계획 결과</summary>':''}<h3>${esc(labels[b.status] || b.status)}</h3>${b.plan_id!==state.designPlan?.plan_id?'<p class="live-hint">현재 설계와 별도로 저장된 실험 결과입니다.</p>':''}<p>${esc(b.batch_id)} · ${esc(reasons[b.stop_reason] || b.stop_reason || '')}</p>
    ${b.source_run_id?`<p class="live-hint">추가 조사 · 원본 ${esc(b.source_run_id)}</p>`:''}<p>계획 ${b.planned_runs}회 · 시작 ${b.slots.length}회 · 비용 집계 $${Number(b.cost_accounted_usd).toFixed(4)}</p><p><strong>${esc(results[b.report.conclusion])}</strong></p>
    ${b.active_run_id?`<button class="primary" data-live-run="${esc(b.active_run_id)}">현재 실행 열기 · 승인·거절 처리</button>`:''}
    ${['RUNNING','WAITING_APPROVAL'].includes(b.status)?`<button class="secondary" data-live-stop-batch>현재 실험 뒤 중단</button>`:''}
    <div class="live-table-wrap"><table class="live-table"><thead><tr><th>조건</th><th>서버</th><th>완료 / 계획</th><th>위반</th><th>보류·오류</th></tr></thead><tbody>${b.report.groups.map(g=>`<tr><td>${esc(b.cases.find(c=>c.case_id===g.case_id)?.risk_id==='CONTROL_BASELINE'?'정상 처리':b.cases.find(c=>c.case_id===g.case_id)?.hypothesis || g.case_id)}${b.cases.find(c=>c.case_id===g.case_id)?.business_input?.quantity!=null?`<br><small>수량 ${esc(b.cases.find(c=>c.case_id===g.case_id).business_input.quantity)}</small>`:''}</td><td>${esc(g.system_id)}</td><td>${g.completed} / ${g.planned}</td><td>${g.counts.FAIL}</td><td>${g.counts.INCONCLUSIVE+g.counts.ERROR}</td></tr>`).join('')}</tbody></table></div>
    <p class="live-hint">${esc(b.report.scope)} 반복 계산은 독립·동일 조건 가정의 참고치입니다.</p>
    <details><summary>조건별 근거와 실패 실행</summary><pre>${json(b.report)}</pre></details>
    <div>${b.slots.filter(x=>x.run_id).map(x=>`<button class="secondary" data-live-run="${esc(x.run_id)}">${esc(x.run_id)} · ${esc(x.status)}</button>`).join('')}</div>${previous?'</details>':''}`;
}
async function refreshBatch() {
  if(!state.session || !host)return;
  const current=generation, token=state.session.access_token;
  const list=await api('/qa/batches',{token});
  if(current!==generation || !host)return;
  if(!state.batch || !list.batches.some(b=>b.batch_id===state.batch.batch_id))state.batch=list.batches[0] || null;
  renderBatch();if(state.batch)pollBatch();
}
async function pollBatch() {
  clearTimeout(batchTimer);if(!state.session || !state.batch || !host)return;
  const current=generation, token=state.session.access_token, id=state.batch.batch_id;
  try {
    const b=await api(`/qa/batches/${encodeURIComponent(id)}`,{token});
    if(current!==generation || !host || state.batch?.batch_id!==id)return;
    state.batch=b;renderBatch();
    if(['RUNNING','WAITING_APPROVAL','STOPPING'].includes(b.status))batchTimer=setTimeout(pollBatch,1000);
  } catch(e){if(current===generation && host)failure(e);}
}

function selectedDesign() {
  const area=$('[data-live-design-selected]');if(!area)return;
  const selected=state.designPlan?.cases.find(c=>c.case_id===state.designCaseId);
  area.innerHTML=selected?`<div class="live-selected-design"><strong>선택한 설계 시험</strong><p>${esc(selected.hypothesis)}</p><p>${selected.business_input.quantity!=null?`실제 요청 수량: <strong>${esc(selected.business_input.quantity)}개</strong>`:`업무 입력: <strong>${esc(JSON.stringify(selected.business_input))}</strong>`} · 저장한 계획의 입력으로 실행합니다.</p><button type="button" class="secondary" data-live-clear-design>선택 해제</button></div>`:'';
}

function account() {
  const showAuthSplit = !state.session;
  const split=$('[data-live-auth-split]');
  if(split) split.hidden=!showAuthSplit;
  const ws=$('[data-live-workspace]');
  if(ws) ws.hidden=showAuthSplit;
  const userTag=$('[data-live-user-tag]');
  if(userTag) userTag.textContent=state.session?.user_id || 'requester-01';
  $('[data-live-account]').innerHTML=state.session ? `<div class="session-inline"><span class="mono">${esc(state.session.user_id)}</span> ${badge(state.session.roles.join(' / '))} <button type="button" class="secondary" data-live-logout>로그아웃</button></div>` :
    `<form data-live-login class="login-form-fields"><label class="field-block"><span>계정</span><input name="user_id" value="requester-01" autocomplete="username" required></label><label class="field-block"><span>비밀번호</span><input name="password" type="password" value="crashlab" autocomplete="current-password" required><small class="live-hint">개발 계정 기본 비밀번호는 서버의 <span class="mono">DEMO_USER_PASSWORD (crashlab)</span>입니다.</small></label><button class="primary login-submit" type="submit">로그인하고 평가 대상 고르기 →</button></form>`;
  const button=$('[data-live-start] button');
  button.textContent=page==='prepare'?'이 조건으로 실행 준비 →':state.pendingStart?'실행 요청 중…':state.run && !state.settled?'실행 진행 중':state.designCaseId?'선택한 설계 시험 시작':'시험 시작';
  button.disabled=!registeredCaseReady(state.registration,state.designPlan,state.designCaseId) || !state.session?.roles.includes('REQUESTER') || !state.catalog || state.pendingStart || !!(state.run && !state.settled);
  $('[data-live-setup]').hidden=!['prepare','live'].includes(page) || (page==='live' && !!state.run);
  $('[data-live-summary]').hidden=!['live','execution'].includes(page) || (page==='live' && !state.run);
  syncShellChrome();
  targets();
  guidance();selectedDesign();
}
function catalog() {
  state.draft=normalizeDraft(state.catalog,state.draft);
  $('[name=test_id]').innerHTML=options(testsForAgent(state.catalog,state.draft.agent),'test_id','title');
  $('[name=test_id]').value=state.draft.test_id;
  $('[name=system_id]').innerHTML=options(state.catalog.systems,'system_id','server_policy_version');
  $('[name=system_id]').value=state.draft.system_id;
  selectTest(); targets(); account();
}
function selectTest() {
  state.draft.test_id=$('[name=test_id]').value;
  const test=state.catalog?.tests.find(t=>t.test_id===$('[name=test_id]').value);
  if(state.designCaseId && !state.designPlan?.cases.some(c=>c.case_id===state.designCaseId && c.execution.registered_test_id===state.draft.test_id))state.designCaseId=null;
  $('[name=system_id]').disabled=test?.test_kind!=='SYSTEM';
  $('[data-live-data]').hidden=!!state.registration || test?.test_kind!=='SYSTEM';
  for(const input of $('[data-live-data]').querySelectorAll('input[type=number]'))input.disabled=!!state.registration || test?.test_kind!=='SYSTEM' || !state.trialData.enabled;
  $('[data-live-kind]').textContent=test ? `${test.test_kind==='SYSTEM'?'실제 서비스 통합 시험 · 실행 중 담당자 승인이 필요합니다.':test.test_kind==='INVESTIGATION_AGENT'?'조사 Agent 단독 시험 · 별도 승인 없이 보고서를 생성합니다.':'구매 Agent 단독 시험 · 준비된 시험 조건으로 자동 진행합니다.'} 모델은 서버 설정을 따릅니다.` : '';guidance();
}
async function refresh() {
  const current=generation;
  const [catalogData,historyData,targetData,registered]=await Promise.all([api('/scenarios',{token:state.session.access_token}),api('/runs',{token:state.session.access_token}),api('/qa/targets',{token:state.session.access_token}),api('/qa/registrations',{token:state.session.access_token})]);
  if(current!==generation || !host)return;
  state.catalog=catalogData;state.runs=historyData.runs;state.targetTypes=targetData.types;state.registrations=registered.profiles;state.capabilityOptions=registered.capabilities;state.executionRuntimes=registered.execution_runtimes || [];
  const runtimeSelect=$('[name=execution_runtime]');if(runtimeSelect)for(const item of state.executionRuntimes){if(![...runtimeSelect.options].some(o=>o.value===item.runtime_id)){const option=document.createElement("option");option.value=item.runtime_id;option.textContent=item.name;runtimeSelect.append(option);}}
  catalog(); history(); account();
}
function history() {
  const runBar=run=>{
    const p=run.summary?.PASS || 0, f=run.summary?.FAIL || 0, inc=run.summary?.INCONCLUSIVE || 0;
    if(p+f+inc>0){
      return `<span class="bar3">${p?`<i style="flex:${p};background:var(--pos)"></i>`:''}${f?`<i style="flex:${f};background:var(--neg)"></i>`:''}${inc?`<i style="flex:${inc};background:var(--warn)"></i>`:''}</span>`;
    }
    return `<span class="run-state-tag">${esc(run.status)}</span>`;
  };
  const runButton=run=>`<button type="button" class="run-row-btn" data-live-run="${esc(run.run_id)}"><span class="run-id num">${esc(run.run_id)}</span><span class="run-sub">${esc(run.test_id)}${run.system_id?` · ${esc(run.system_id)}`:''}</span>${runBar(run)}</button>`;
  $('[data-live-history]').innerHTML=state.runs.length ? `<div class="runs-list">${state.runs.slice(0,8).map(runButton).join('')}</div>`+(state.runs.length>8?`<details class="runs-more"><summary>이전 기록 ${state.runs.length-8}개</summary><div class="runs-list">${state.runs.slice(8).map(runButton).join('')}</div></details>`:'') : '<p class="live-hint empty-runs-hint">로그인하면 저장된 실행 기록을 불러옵니다.</p>';
  const completed=completedSystemRuns(state.catalog,state.runs);
  for(const name of ['left','right']) {
    const select=$(`[name=${name}]`), previous=state.compareDraft[name];
    select.innerHTML=options(completed.map(r=>({...r,title:`${r.test_id} ${r.system_id}`})),'run_id','title');
    if(completed.some(r=>r.run_id===previous))select.value=previous;
    else if(name==='right' && completed.length>1)select.selectedIndex=1;
    state.compareDraft[name]=select.value;
  }
}
async function openRun(id) {
  clearTimeout(timer);generation++;loading=false;
  state.events=[];state.selected=null;state.run=null;state.settled=false;
  $('[data-live-approval]').innerHTML='';$('[data-live-summary]').textContent='실행을 불러오는 중입니다…';$('[data-live-analysis]').hidden=true;$('[data-live-result]').innerHTML='';
  const current=generation;
  const run=await api(`/runs/${encodeURIComponent(id)}`,{token:state.session.access_token});
  if(current!==generation || !host)return;
  state.run=run;renderRun(true);renderBatch();await poll();
}
async function poll() {
  if(!host || !state.run || !state.session || loading)return;
  clearTimeout(timer); loading=true; const current=generation, id=state.run.run_id;
  try {
    const run=await api(`/runs/${encodeURIComponent(id)}`,{token:state.session.access_token});
    let events=state.events, page;
    do {
      page=await api(`/runs/${encodeURIComponent(id)}/events?after_sequence=${events.at(-1)?.sequence || 0}&limit=200`,{token:state.session.access_token});
      const next=mergeEvents(events,page.events,id);
      if(page.has_more && next.length===events.length)throw new Error('이벤트 조회가 진행되지 않습니다.');
      events=next;
    } while(page.has_more && current===generation);
    if(current!==generation || !host)return;
    state.run=run;state.events=events;state.settled=isFinished(run) && page.is_final;renderRun();account();
    if(isFinished(run) && page.is_final)await refresh();
    else timer=setTimeout(poll,1000);
  } catch(error) {
    if(current!==generation || !host)return;
    failure(error);
    // Reads can reconnect; a failed start or approval is never sent automatically.
    if(state.session)timer=setTimeout(poll,3000);
  } finally {if(current===generation)loading=false;}
}
function renderRun(force=false) {
  $('[data-live-summary]').hidden=!['live','execution'].includes(page);guidance();
  const run=state.run, summary=run.summary || {}, model=run.manifest?.model || run.investigation?.model_metadata?.model;
  const failCount=summary.FAIL ?? 0, passCount=summary.PASS ?? 0, incCount=summary.INCONCLUSIVE ?? 0;
  const changeCount=(run.observed_change_count ?? run.observed_order_count) == null ? "—" : esc(run.observed_change_count ?? run.observed_order_count);
  $('[data-live-summary]').innerHTML=`
    <div class="live-row run-summary-head">
      <div>
        <span class="step-eyebrow">ACTIVE RUN · ${esc(run.system_id || 'UNIT')}</span>
        <h2>${esc(run.run_id)} <span class="mono dim">· ${esc(run.test_id)} ${esc(run.system_id || '')}</span></h2>
      </div>
      ${badge(run.status)}
    </div>
    ${run.status_reason?`<p class="live-hint">${esc(run.status_reason)}</p>`:''}
    <div class="strip kpi-strip-card">
      <div class="lead ${failCount?'is-fail':'is-pass'}">
        <label>검사 판정 요약</label>
        <div class="v">${failCount?`${failCount}개 실패`:`${passCount}개 통과`}</div>
        <div class="d">PASS ${passCount} · FAIL ${failCount} · 보류 ${incCount}</div>
      </div>
      <div><label>PASS</label><div class="v pos-t">${esc(passCount)}</div><div class="d">통과 규칙</div></div>
      <div><label>FAIL</label><div class="v ${failCount?'neg-t':''}">${esc(failCount)}</div><div class="d">위반 규칙</div></div>
      <div><label>INCONCLUSIVE</label><div class="v">${esc(incCount)}</div><div class="d">검토 대기</div></div>
      <div><label>${run.manifest?.state_store?"업무 변경":"실제 주문"}</label><div class="v">${changeCount}<small>건</small></div><div class="d">DB 관측 상태</div></div>
    </div>
    ${run.manifest?.registered_target?`<p><strong>등록 대상: ${esc(run.manifest.registered_target.name)}</strong> · 실제 실행: ${esc(run.manifest.registered_target.execution_binding?.name || run.manifest.target_id)} · ${esc(run.manifest.agent_version || '버전 확인 중')}</p>`:''}
    <div class="run-meta-bar">
      <span>${state.settled?'수집 완료 · QA 보고서를 확인하세요.':'실행·근거 수집 중'}</span>
      <span class="mono">모델: ${esc(model && typeof model==='object' ? JSON.stringify(model) : model || run.investigation?.model_metadata?.model_kind || run.manifest?.model_kind || '미지정')} · 조사: ${esc(run.investigation?.status || '—')}</span>
    </div>
    <div class="live-flow-actions">${run.status==='WAITING_APPROVAL' && page!=='live'?'<button class="primary" data-live-go="live">승인·거절 처리 →</button>':''}${state.settled?'<button class="secondary" data-live-go="prepare">새 시험 준비 →</button>':''}${page!=='execution'?'<button class="secondary" data-live-go="execution">이 실행 분석 →</button>':run.system_id && state.settled?'<button class="secondary" data-live-go="compare">실제 결과 비교 →</button>':''}</div>`;
  const approvalKey=JSON.stringify([run.run_id,run.status,run.approval_request,run.approval]);
  const area=$('[data-live-approval]');
  if(force || area.dataset.key!==approvalKey) {
    area.dataset.key=approvalKey;
    area.innerHTML=run.status==='WAITING_APPROVAL' && run.approval_request ? `<section class="card section-pad live-approval approval-gate-card">
      <div class="card-head-inline">
        <div>
          <span class="step-eyebrow sig-text">HUMAN-IN-THE-LOOP GATE</span>
          <h2>담당자 결정이 필요합니다</h2>
        </div>
        <span class="wait-pill"><i class="pulse-dot sig"></i><span>WAITING_APPROVAL</span></span>
      </div>
      <p class="live-hint">Agent가 업무 변경 전 담당자 승인을 요청했습니다. 요청 내용을 확인한 뒤 승인자 계정으로 결정하세요. (만료 시각: <span class="mono">${esc(run.approval_request.expires_at || '—')}</span>)</p>
      <details open class="approval-payload-box"><summary>승인 대상 요청 원문</summary><pre>${json(run.request)}</pre></details>
      <form data-live-approval-form class="approval-form-grid">
        <div class="form-row-2">
          <label>승인자 계정<input name="user_id" value="approver-01" autocomplete="username" required></label>
          <label>비밀번호<input name="password" type="password" autocomplete="current-password" required></label>
        </div>
        <div class="approval-actions">
          <button class="primary" name="decision" value="APPROVED">✓ 요청 승인 (APPROVED)</button>
          <button class="secondary danger-btn" name="decision" value="REJECTED">× 요청 거절 (REJECTED)</button>
        </div>
      </form></section>` : '';
  }
  $('[data-live-analysis]').hidden=page!=='execution';$('[data-live-result]').hidden=page!=='execution';renderEvents();
  const checksGridHtml = run.checks?.length ? `<div class="checks">${run.checks.map(c=>`<div class="chk ${c.verdict==='FAIL'?'f':'p'}"><span class="ic">${c.verdict==='PASS'?'✓':c.verdict==='FAIL'?'×':'…'}</span><div><strong>${esc(ruleTitle(c.rule_id))}</strong><p>${esc(c.reason || c.message || scopeTitle(c.scope))}</p></div><span class="r">${badge(c.verdict)}</span></div>`).join('')}</div>` : '';
  $('[data-live-result]').innerHTML=`<section class="card section-pad"><div class="live-row"><div><span class="step-eyebrow">ORACLE VERDICT &amp; QA REPORT</span><h2>QA 보고서</h2></div><div class="live-row"><button class="secondary" data-live-qa-report ${!state.settled || !run.qa_report?'disabled':''}>이 실험 보고서 저장</button><button class="secondary" data-live-qa-summary>최근 시험 요약 저장</button></div></div>${checksGridHtml}${qaReportMarkup(run.qa_report)}${state.settled?followupMarkup(run.follow_up):''}
    <details><summary>검사 상세 · ${run.checks?.length || 0}개</summary><h2>검사 결과</h2>${run.checks?.length ? `<div class="live-table-wrap"><table class="live-table"><thead><tr><th>규칙</th><th>대상</th><th>판정</th><th>근거</th></tr></thead><tbody>${run.checks.map(c=>`<tr><td>${esc(ruleTitle(c.rule_id))}</td><td>${esc(scopeTitle(c.scope))}</td><td>${badge(c.verdict)}</td><td>${esc(c.reason || c.message || '')}<details><summary>검사 근거</summary><pre>${json(c)}</pre></details></td></tr>`).join('')}</tbody></table></div>` : '<p>아직 판정이 없습니다.</p>'}</details>
    ${run.investigation?.report?`<details><summary>추가 조사 기록</summary><p class="live-hint">${run.investigation.method==='CODE_EVIDENCE_SUMMARY'?'코드 기반 기록 요약':'조사 Agent 결과 · 사실과 원인 후보 구분'}</p>${reportView(run.investigation.report)}</details>`:''}
    <details><summary>실행 정보</summary><pre>${json({agent:run.agent,manifest:run.manifest,investigation_validation:run.investigation?.validation})}</pre></details></section>`;
  actionHint();
}
function reportView(report) {
  if(!report)return '<p class="live-hint">보고서가 도착하면 표시합니다.</p>';
  const list=items=>`<ul>${(items || []).map(text=>`<li>${esc(text)}</li>`).join('')}</ul>`;
  return `<h3>확인한 사실</h3><ul>${(report.facts || []).map(f=>`<li>${esc(f.text)}<small>${esc(f.evidence_ids?.join(', '))}</small></li>`).join('')}</ul><h3>원인 후보</h3>${list(report.cause_candidates)}<h3>부족한 증거</h3>${list(report.missing_evidence)}<h3>개선 제안</h3><ul>${(report.improvements || []).map(i=>`<li>${esc(i.text)}<small>${esc(i.sources?.map(s=>`${s.document_id}/${s.version} · ${s.location}`).join(', '))}</small></li>`).join('')}</ul><p>재시험: ${esc(report.retest_scenario_ids?.join(', '))}</p>`;
}
function renderEvents() {
  const events=state.events, selected=state.selected===null ? events.length-1 : Math.min(state.selected,events.length-1);
  $('[data-live-count]').textContent=`${events.length}개 저장 이벤트 · ${state.settled?'조회 완료':'1초마다 조회'}`;
  const cursor=$('[data-live-cursor]');cursor.max=Math.max(0,events.length-1);cursor.value=Math.max(0,selected);cursor.disabled=!events.length;
  const list=$('[data-live-events]'), scroll=list.scrollTop;
  list.innerHTML=events.map((e,i)=>`<button class="live-event ${i===selected?'selected':''}" data-live-event="${i}"><span class="mono">${e.sequence}</span><span>${esc(e.event_type)}<small>${esc(e.node_id)} · ${esc(e.occurred_at)}</small></span></button>`).join('');
  list.scrollTop=scroll;
  $('[data-live-evidence]').textContent=events[selected] ? JSON.stringify(events[selected],null,2) : '아직 이벤트가 없습니다.';
  const divArea=$('[data-live-divergence]');
  if(divArea){
    const dbEvs=events.filter(e=>['BUSINESS_COMMITTED','IDEMPOTENT_RETURNED','VERDICT_CREATED','STATE_CHANGED'].includes(e.event_type));
    const agEvs=events.filter(e=>['APPROVAL_DECIDED','FAULT_INJECTED','TOOL_CALLED','AGENT_REPORTED'].includes(e.event_type));
    const hasFault=events.some(e=>e.event_type==='FAULT_INJECTED');
    const total=Math.max(events.length,1);
    const posPct=seq=>Math.min(92,Math.max(8,Math.round((seq/total)*90)));
    divArea.innerHTML=events.length?`<div class="card div-card live-div-card"><div class="card-h"><h2>Agent가 본 것과 실제 DB</h2><span class="meta">같은 순번에서 두 기록을 대조합니다</span></div>
      <div class="lanes">
        <div class="lane"><label>업무 DB<small>실제 상태</small></label><div class="lane-track">
          ${hasFault?'<div class="gap-zone" style="left:38%;width:34%"></div>':''}
          ${dbEvs.slice(0,4).map(e=>`<span class="ev ${e.event_type==='BUSINESS_COMMITTED'?'db':'ok'}" style="left:${posPct(e.sequence)}%">#${e.sequence} ${esc(e.event_type)}</span>`).join('')}
        </div></div>
        <div class="lane"><label>대상 Agent<small>받은 결과 · 호출</small></label><div class="lane-track">
          ${agEvs.slice(0,4).map(e=>`<span class="ev ${e.event_type==='FAULT_INJECTED'?'sig':e.event_type==='AGENT_REPORTED'?'bad':''}" style="left:${posPct(e.sequence)}%">#${e.sequence} ${esc(e.event_type)}</span>`).join('')}
        </div></div>
      </div></div>`:'';
  }
  if(page!=='execution'){pauseScene();return;}
  const liveGraph=state.run?.manifest?.state_store?{...graph,nodes:graph.nodes.map(n=>({...n,label:n.id==='agent'?agentName('purchase'):n.id==='mcp'?'제조업 시험 MCP':n.id==='investigator'?'조사 요약':n.label}))}:graph;
  try { mountScene($('#live-scene'),liveGraph,frameFor(liveGraph,sceneEvents(events),selected),node=>{const i=sceneEvents(state.events).findLastIndex(e=>e.node_id===node);if(i>=0){state.selected=i;renderEvents();}}); }
  catch { $('#live-scene').textContent='이 브라우저에서는 3D를 표시할 수 없습니다. 아래 이벤트와 근거를 확인하세요.'; }
}
function comparisonView(data) {
  const lCount = data.actual.left.change_count ?? data.actual.left.order_count ?? 0;
  const rCount = data.actual.right.change_count ?? data.actual.right.order_count ?? 0;
  const lFail = (data.checks || []).filter(c => c.left === 'FAIL').length;
  const rFail = (data.checks || []).filter(c => c.right === 'FAIL').length;
  const lPass = (data.checks || []).filter(c => c.left === 'PASS').length;
  const rPass = (data.checks || []).filter(c => c.right === 'PASS').length;
  return `<div class="vs">
    <section class="card pol">
      <div class="pol-h"><h2><span class="num">${esc(data.left.system_id || 'LEFT')}</span>${esc(data.left.run_id)}</h2><span class="pill ${lFail?'neg':'pos'}">${lFail?`${lFail} 실패`:`${lPass} 통과`}</span></div>
      <div class="big"><b class="num ${lCount>1?'neg-t':''}">${esc(lCount)}</b><span>건 업무 변경 저장</span></div>
      <p class="cap">기준 실행 (${esc(data.left.system_id || '—')})의 최종 DB 변경 건수입니다.</p>
    </section>
    <section class="card pol">
      <div class="pol-h"><h2><span class="num">${esc(data.right.system_id || 'RIGHT')}</span>${esc(data.right.run_id)}</h2><span class="pill ${rFail?'neg':'pos'}">${rFail?`${rFail} 실패`:`${rPass} 통과`}</span></div>
      <div class="big"><b class="num">${esc(rCount)}</b><span>건 업무 변경 저장</span></div>
      <p class="cap">비교 실행 (${esc(data.right.system_id || '—')})의 최종 DB 변경 건수입니다.</p>
    </section>
  </div>
  <section class="card">
    <div class="card-h"><h2>실제 실행 검사별 비교</h2><div class="live-row"><span class="meta">${esc(data.left.run_id)} ↔ ${esc(data.right.run_id)}</span><button class="secondary" data-live-close-comparison>닫기</button></div></div>
    <div class="live-table-wrap"><table class="mx"><thead><tr><th>규칙</th><th>대상</th><th class="c">${esc(data.left.system_id || '왼쪽')}</th><th class="c">${esc(data.right.system_id || '오른쪽')}</th></tr></thead><tbody>${data.checks.map(c=>`<tr><td><strong>${esc(ruleTitle(c.rule_id))}</strong></td><td class="mono mx-evi">${esc(scopeTitle(c.scope))}</td><td class="c">${badge(c.left)}</td><td class="c">${badge(c.right)}</td></tr>`).join('')}</tbody></table></div>
    <div class="note"><b>해석 주의</b><span>서버 정책 및 변경 조건의 차이를 함께 확인하세요.</span></div>
    <details class="section-pad"><summary>고정 조건과 변경 조건</summary><pre>${json({fixed_conditions:data.fixed_conditions,changed:data.changed})}</pre></details>
  </section>`;
}
async function submit(event) {
  event.preventDefault();notify('');const form=event.target, values=Object.fromEntries(new FormData(form)),button=event.submitter;
  const current=generation; const buttons=[...form.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
  try {
    if(form.matches('[data-live-login]')) {
      const session=await api('/auth/login',{body:values});if(current!==generation || !host)return;state.session=session;form.reset();await refresh();await refreshBatch();account();notify('로그인했습니다. 평가 대상을 선택한 뒤 시험 설계로 이동해 주세요.');
      if(state.pendingRunId){const id=state.pendingRunId;state.pendingRunId=null;await openRun(id);}else if(state.run)poll();
    } else if(form.matches('[data-qa-registration]')) {
      if(!state.session)throw new Error('로그인 후 등록해 주세요.');
      const body=collectDeclaration(form);
      const saved=await api('/qa/registrations',{token:state.session.access_token,body});
      if(host && current===generation){state.registration=saved;state.designPlan=null;state.designCaseId=null;state.batchRequest=null;
        await refresh();renderRegistrations();guidance();$('[data-qa-editor]').open=false;
        notify(saved.execution_binding?'실행기와 시험 데이터 연결을 확인했습니다. 시험을 설계해 실행하세요.':'등록한 설명을 저장하고 위험을 분류했습니다. 실제 실행은 연결 전입니다.');}
    } else if(form.matches('[data-live-design]')) {
      if(!state.session)throw new Error('로그인 후 설계해 주세요.');
      notify('Agent 분석 → 근거 검색 → 시험 구성 중입니다…');
      const token=state.session.access_token;
      const designTarget=state.registration?.profile_id || values.target_type;
      let plan;
      if(state.registration)plan=await api(`/qa/registrations/${encodeURIComponent(state.registration.profile_id)}/design`,{token,body:{generation_mode:values.generation_mode}});
      else{
        const reference=await api(`/qa/target?target_type=${encodeURIComponent(values.target_type)}`,{token});
        const body=values.target_type==='PURCHASE' && state.trialData.enabled?preparedPurchaseSample(reference,state.trialData):reference;
        plan=await api('/qa/design',{token,body:{...body,generation_mode:values.generation_mode}});
      }
      if(host && current===generation && designTarget===(state.registration?.profile_id || state.targetType)){state.designPlan=plan;state.designCaseId=null;state.batchRequest=null;renderDesign();renderBatch();notify(state.registration && !state.registration.execution_binding?'시험안을 만들었습니다. 근거·제안 조건·실행에 필요한 연결을 확인하세요.':'시험을 선택하고 실행하세요.');}
    } else if(form.matches('[data-live-batch-form]')) {
      if(!state.session || !state.designPlan)throw new Error('먼저 로그인하고 시험을 설계해 주세요.');
      const body={request_id:crypto.randomUUID(),plan_id:state.designPlan.plan_id,case_ids:[values.case_id],
        systems:[state.draft.system_id],mode:values.mode,max_runs:Number(values.max_runs),
        max_seconds:Number(values.max_seconds),max_cost_usd:Number(values.max_cost_usd)};
      if(state.batchRequest)Object.assign(body,state.batchRequest);
      state.batchRequest=body;
      try {state.batch=await api('/qa/batches',{token:state.session.access_token,body});}
      catch(e){if(e.status>=400 && e.status<500)state.batchRequest=null;throw e;}
      state.batchRequest=null;
      renderBatch();pollBatch();notify('실험 계획을 접수했습니다. 각 실행의 담당자 승인을 처리하세요.');
    } else if(form.matches('[data-live-knowledge]')) {
      if(!state.session)throw new Error('로그인 후 검색해 주세요.');
      const button=form.querySelector('button');button.disabled=true;
      try {
        const token=state.session.access_token;
        const [data,status]=await Promise.all([api('/knowledge/search',{token,body:{...values,limit:3}}),api('/knowledge/status',{token})]);
        state.knowledge=data;state.knowledgeStatus=status;
        if(host && current===generation){renderKnowledge();notify('원문과 요약을 구분해 근거를 확인해 주세요.');}
      } finally {button.disabled=false;}
    } else if(form.matches('[data-live-start]')) {
      if(!registeredCaseReady(state.registration,state.designPlan,state.designCaseId))throw new Error('등록 대상과 일치하는 실행 가능한 시험을 선택하세요.');
      if(page==='prepare'){if(!state.run || state.settled){state.run=null;state.events=[];state.selected=null;state.settled=false;}go('live');return;}
      if(state.pendingStart)return;
      let body=startPayload(state.catalog,state.draft);
      state.pendingStart=true;account();guidance();
      try {
        const token=state.session.access_token;
        if(body.system_id && state.designCaseId && state.designPlan){
          body={plan_id:state.designPlan.plan_id,case_id:state.designCaseId,system_id:body.system_id};
        } else if(body.system_id && state.trialData.enabled){
          const reference=await api('/qa/target',{token});
          const prepared=preparedPurchaseSample(reference,state.trialData);
          if(state.knowledge?.target_type==='PURCHASE'){prepared.knowledge_query=state.knowledge.query;prepared.knowledge_target_type='PURCHASE';}
          const plan=await api('/qa/plans',{token,body:prepared});
          const selected=plan.cases.find(c=>c.execution.registered_test_id===body.test_id && c.execution.status==='READY');
          if(!selected)throw new Error('이 데이터로 실행할 수 없는 시험입니다. 조건을 다시 확인하세요.');
          body={plan_id:plan.plan_id,case_id:selected.case_id,system_id:body.system_id};
        }
        const result=await api('/runs',{token,body});
        if(!host || !state.session){state.pendingRunId=result.run_id;return;}
        notify(`${result.run_id} 실행이 접수됐습니다. 아래에서 진행 상태를 확인하세요.`);await openRun(result.run_id);
        if(['live','execution'].includes(page))$('[data-live-guidance]')?.scrollIntoView({block:'start'});
      } finally {state.pendingStart=false;if(host){account();guidance();}}
    } else if(form.matches('[data-live-approval-form]')) {
      const run=state.run, decision=button.value;
      const approver=await api('/auth/login',{body:values});form.password.value='';
      await api(`${run.manifest?.state_store?"/qa":""}/runs/${encodeURIComponent(run.run_id)}/approval`,{token:approver.access_token,body:{approval_request_id:run.approval_request.approval_request_id,payload_hash:run.approval_request.payload_hash,decision}});
      notify(decision==='APPROVED'?'승인했습니다. 실행 결과를 기다려 주세요.':'거절했습니다. 실행 결과를 기다려 주세요.');
      await poll();
    } else if(form.matches('[data-live-compare]')) {
      state.comparison=null;$('[data-live-comparison]').innerHTML='';
      const result=await api(`/comparisons?${new URLSearchParams(values)}`,{token:state.session?.access_token});
      if(current===generation && host){state.comparison=result;state.compareDraft=values;$('[data-live-comparison]').innerHTML=comparisonView(result);actionHint();}
    }
  } catch(error) { if(host)failure(error); }
  finally {buttons.forEach(b=>b.disabled=false);if(host){renderRegistrations();account();renderBatch();}}
}
function click(event) {
  const target=event.target.closest('button');if(!target)return;
  if(target.hasAttribute('data-role-preset')) {
    const uid=target.dataset.rolePreset;
    for(const b of host.querySelectorAll('[data-role-preset]')) b.classList.toggle('on', b===target);
    const input=$('[data-live-login] [name=user_id]');
    if(input){ input.value=uid; $('[data-live-login] [name=password]')?.focus(); }
    return;
  }
  if(target.hasAttribute('data-live-skip-auth')) {
    state.authDismissed=true;
    account();
    return;
  }
  if(target.hasAttribute('data-live-open-3d-demo')) {
    location.hash='#demo-3d';
    return;
  }
  if(target.hasAttribute('data-live-open-compare-demo')) {
    location.hash='#demo-compare';
    return;
  }
  if(target.hasAttribute('data-live-demo-jump')) {
    document.querySelector('.demo-entry')?.click();
    return;
  }
  if(target.hasAttribute('data-live-open-register')) {
    const ed=$('[data-qa-editor]');
    if(ed){ ed.open=true; ed.scrollIntoView({behavior:'smooth',block:'start'}); }
    return;
  }
  if(target.hasAttribute('data-live-logout')) {state.registration=null;state.registrations=[];state.capabilityOptions=[];state.batch=null;state.batchRequest=null;state.designPlan=null;state.designCaseId=null;state.targetTypes=[];state.session=null;state.catalog=null;state.run=null;state.events=[];state.runs=[];state.comparison=null;state.compareDraft={left:'',right:''};state.pendingRunId=null;const element=host;leaveLive();mountLive(element,page,go);notify('로그아웃했습니다.');}
  if(target.hasAttribute('data-qa-parse')){
    try{renderToolBindings($('[data-qa-registration]'),state.capabilityOptions);notify('도구별 조회·변경과 업무 기능 연결을 확인하세요.');}catch(error){failure(error);}
  }
  if(target.hasAttribute('data-qa-example')){
    if(!state.session){notify('로그인 후 예시를 불러오세요.',true);return;}
    api(`/qa/target?target_type=${encodeURIComponent($('[data-qa-registration]').elements.agent_type.value)}`,{token:state.session.access_token}).then(example=>{
      const data=exampleDeclaration(example);fillDeclaration($('[data-qa-registration]'),data);
      renderToolBindings($('[data-qa-registration]'),state.capabilityOptions,data);
      notify('선택한 업무 예시를 새 등록용으로 채웠습니다. 기능 확인 수준은 등록자 설명으로 기록합니다.');
    }).catch(failure);
  }
  if(target.hasAttribute('data-qa-profile')){
    state.registration=state.registrations.find(p=>p.profile_id===target.dataset.qaProfile);
    state.designPlan=null;state.designCaseId=null;state.batchRequest=null;targets();renderDesign();renderBatch();
  }
  if(target.hasAttribute('data-qa-edit') && state.registration){
    fillDeclaration($('[data-qa-registration]'),state.registration.input);
    renderToolBindings($('[data-qa-registration]'),state.capabilityOptions,state.registration.input);
    $('[data-qa-editor]').open=true;$('[data-qa-editor]').scrollIntoView({block:'start'});
  }
  if(target.hasAttribute('data-qa-plan'))go('prepare');
  if(target.hasAttribute('data-live-follow-up')) {
    target.disabled=true;
    api(`/qa/runs/${encodeURIComponent(state.run.run_id)}/follow-up`,{token:state.session.access_token,body:{}})
      .then(b=>{state.batch=b;renderBatch();pollBatch();notify('추가 실험을 연결했습니다. 각 실행의 승인 요청을 확인하세요.');})
      .catch(failure).finally(()=>{target.disabled=false;});
  }
  if(target.hasAttribute('data-live-stop-batch'))api(`/qa/batches/${encodeURIComponent(state.batch.batch_id)}/stop`,{token:state.session.access_token,body:{}}).then(b=>{state.batch=b;renderBatch();pollBatch();}).catch(failure);
  if(target.hasAttribute('data-live-clear-design')){state.designCaseId=null;account();}
  if(target.hasAttribute('data-live-use-design')){
    const selected=state.designPlan?.cases.find(c=>c.case_id===target.dataset.liveUseDesign);
    if(selected?.execution.status==='READY'){
      if(!state.run || state.settled){state.run=null;state.events=[];state.selected=null;state.settled=false;}
      state.designCaseId=selected.case_id;
      state.draft={...state.draft,agent:'purchase',test_id:selected.execution.registered_test_id};catalog();
      notify(`설계 시험을 선택했습니다. 저장한 업무 입력으로 실행합니다.`);go('live');
    }
  }
  if(target.hasAttribute('data-live-run')){stopReplay();if(!['live','execution'].includes(page))go('execution');openRun(target.dataset.liveRun).catch(failure);}
  if(target.hasAttribute('data-live-refresh')) {if(state.session)refresh().catch(failure);else notify('먼저 로그인해 주세요.',true);}
  if(target.hasAttribute('data-live-event')) {stopReplay();state.selected=Number(target.dataset.liveEvent);renderEvents();}
  if(target.hasAttribute('data-live-show-approval')){$('[data-live-approval]').scrollIntoView({block:'start'});$('[data-live-approval-form] input')?.focus({preventScroll:true});}
  if(target.hasAttribute('data-live-show-results')){$('[data-live-result]').tabIndex=-1;$('[data-live-result]').focus({preventScroll:true});$('[data-live-result]').scrollIntoView({block:'start'});}
  if(target.hasAttribute('data-live-go'))go(target.dataset.liveGo);
  if(target.hasAttribute('data-live-target-type'))selectTargetType(target.dataset.liveTargetType);
  if(target.hasAttribute('data-live-agent')){state.draft=normalizeDraft(state.catalog,{...state.draft,agent:target.dataset.liveAgent,test_id:''});catalog();}
  if(target.hasAttribute('data-live-play'))toggleReplay();
  if(target.hasAttribute('data-live-export'))exportRun();
  if(target.hasAttribute('data-live-qa-report') && state.run?.qa_report && state.settled){
    const content=qaReportDocument(state.run.qa_report,state.events);
    const url=URL.createObjectURL(new Blob([content],{type:'text/html;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download=`${state.run.run_id}-qa-report.html`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  if(target.hasAttribute('data-live-qa-summary'))exportQaSummary(target).catch(failure);
  if(target.hasAttribute('data-live-close-comparison')){state.comparison=null;$('[data-live-comparison]').innerHTML='';actionHint();}
}

function stopReplay(){clearInterval(playback);playback=null;if(host)$('[data-live-play]').textContent='재생';}
function toggleReplay(){
  if(playback){stopReplay();return;}
  if(!state.events.length)return;
  state.selected=state.selected===null || state.selected>=state.events.length-1 ? 0 : state.selected;
  $('[data-live-play]').textContent='정지';renderEvents();
  playback=setInterval(()=>{
    if(!host || page!=='execution' || state.selected>=state.events.length-1){stopReplay();return;}
    state.selected++;renderEvents();
  },1000);
}
function exportRun(){
  if(!state.run)return;
  const data={source:'harness_api',run:state.run,events:state.events,sequence_scope:'HARNESS_GLOBAL'};
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download=`${state.run.run_id}-evidence.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}


async function exportQaSummary(button) {
  if(!state.session)return;
  const current=generation,token=state.session.access_token;
  button.disabled=true;notify('최근 완료 시험을 모으고 있습니다…');
  try {
    const recent=await api('/runs?limit=50',{token});
    const selected=completedSystemRuns(state.catalog,recent.runs).slice(0,20);
    const reports=[];
    for(let i=0;i<selected.length;i+=4){
      const runs=await Promise.all(selected.slice(i,i+4).map(r=>api(`/runs/${encodeURIComponent(r.run_id)}`,{token})));
      for(const run of runs)if(run.qa_report && ['PURCHASE','PRODUCTION','QUALITY'].includes(run.qa_report.target.type))reports.push(run.qa_report);
    }
    if(current!==generation || state.session?.access_token!==token)return;
    if(!reports.length)throw new Error('요약할 완료 시험이 없습니다.');
    const url=URL.createObjectURL(new Blob([qaReportCollectionDocument(reports)],{type:'text/html;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='manufacturing-qa-summary.html';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    notify(`완료 시험 ${reports.length}개의 요약을 저장했습니다.`);
  } finally {if(button.isConnected)button.disabled=false;}
}
