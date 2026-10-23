import * as THREE from './vendor/three.module.js';
import { layoutTopology } from './topology.js?v=0.15.0';

void THREE;
const roleNames={agent:'Agent',runner:'실행 준비',approval:'승인',tool:'도구',database:'업무 상태',store:'읽기 전용 자료',report:'결과 문서',reviewer:'검사·검토'};
const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function renderIsoScene(container, graph, data={}, onSelect) {
  const layout=layoutTopology(graph);
  const layers=[...new Set(layout.nodes.map(n=>n.layer))].sort((a,b)=>a-b);
  const W=880, H=480, S=86, cx=W*0.5, cy=H*0.53;
  const P=(x,y,z=0)=>[+(cx+(x-y)*0.866*S).toFixed(1),+(cy+(x+y)*0.5*S-z*S).toFixed(1)];
  const poly=(pts,fill,stroke='none',sw=1,extra='')=>`<polygon points="${pts.map(p=>p.join(',')).join(' ')}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" ${extra}/>`;

  const pos={};
  const layerSpan=Math.max(layers.length-1,1);
  layers.forEach((layer,lIdx)=>{
    const members=layout.nodes.filter(n=>n.layer===layer);
    const lanes=members.map(m=>m.lane??0);
    const mid=(Math.min(...lanes)+Math.max(...lanes))/2;
    const y0=(lIdx-layerSpan/2)*1.12;
    members.forEach(m=>{
      const x0=((m.lane??0)-mid)*1.15;
      pos[m.id]=[x0,y0];
    });
  });

  let g='';
  // 1. Isometric Terraced Platforms
  layers.forEach((_,lIdx)=>{
    const y0=(lIdx-layerSpan/2)*1.12;
    const a=P(-1.95,y0-0.46), b=P(1.95,y0-0.46), c=P(1.95,y0+0.46), d=P(-1.95,y0+0.46), t=0.12;
    const ad=[a[0],a[1]+t*S], bd=[b[0],b[1]+t*S], cd=[c[0],c[1]+t*S], dd=[d[0],d[1]+t*S];
    g+=poly([d,c,cd,dd],'#101013')+poly([b,c,cd,bd],'#0c0c0e')+poly([a,b,c,d],lIdx%2?'#19191d':'#1c1c21','#25252c',1);
  });

  // 2. Edges + Animated Packet Dots
  graph.edges.forEach((edge,i)=>{
    const p1=pos[edge.source], p2=pos[edge.target];
    if(!p1||!p2)return;
    const isActive=data.activeEdge===edge.id;
    const isFault=isActive && !!data.fault;
    const isSeen=isActive || (data.observedEdges||[]).includes(edge.id);
    const reverse=graph.edges.some(e=>e.source===edge.target&&e.target===edge.source);
    const off=isFault?0.18:reverse?(edge.source<edge.target?0.14:-0.14):0;
    const pts=[P(p1[0]+off,p1[1],0.02),P(p1[0]+off,p2[1],0.02),P(p2[0]+off,p2[1],0.02)];
    const d=`M${pts[0]} L${pts[1]} L${pts[2]}`;
    const col=isFault?'#ff6a3d':isActive?'#ff8a5f':isSeen?'#d9d9de':'#383842';
    g+=`<path d="${d}" fill="none" stroke="${col}" stroke-width="${isActive?2.1:1.6}" ${isFault?'stroke-dasharray="6 5" class="fault-edge"':''} opacity="${isSeen?0.92:0.75}"/>`;
    if(isFault){
      const m=P(p1[0]+off,(p1[1]+p2[1])/2,0.02);
      const half=`M${pts[0]} L${m}`;
      g+=`<circle r="3.5" fill="#ff8a5f"><animateMotion dur="1.7s" repeatCount="indefinite" path="${half}"/></circle>`;
      g+=`<g transform="translate(${m})"><circle r="11" fill="#2a1610" stroke="#ff6a3d" stroke-width="1.5"/><path d="M-4 -4 4 4M4 -4 -4 4" stroke="#ff6a3d" stroke-width="1.8" stroke-linecap="round"/></g>`;
    } else if(isSeen){
      g+=`<circle r="${isActive?3.4:2.8}" fill="${isActive?'#ff8a5f':'#ffffff'}"><animateMotion dur="${2.1+(i%4)*0.35}s" repeatCount="indefinite" path="${d}"/></circle>`;
    }
  });

  // 3. 3D Nodes sorted back-to-front
  const order=[...layout.nodes].sort((a,b)=>(pos[a.id][0]+pos[a.id][1])-(pos[b.id][0]+pos[b.id][1]));
  order.forEach(nd=>{
    const [x,y]=pos[nd.id];
    const count=data.counts?.[nd.id]??0;
    const commits=data.commits?.[nd.id]??0;
    const isActive=data.activeNode===nd.id;
    const isFault=isActive && !!data.fault;
    const isDim=!data.preview && count===0 && !isActive;
    const kind=nd.role==='database'?'cyl':nd.role==='approval'?'disc':nd.role==='agent'?'screen':'box';
    const w=0.27, h=kind==='disc'?0.08:kind==='cyl'?0.42:0.34;
    const top=isFault?'#3a2116':isActive?'#342620':isDim?'#25252a':'#2e2e36';
    const left=isFault?'#2a170f':isActive?'#281c17':isDim?'#1b1b1f':'#222228';
    const right=isFault?'#1f110b':isActive?'#1e1511':isDim?'#151518':'#19191e';
    const st=isFault?'#ff6a3d':isActive?'#ff8a5f':isDim?'#2c2c33':'#3f3f48';

    if(isFault || isActive){
      const c=P(x,y,0);
      g+=`<ellipse class="shock" cx="${c[0]}" cy="${c[1]}" rx="${(0.88*S).toFixed(1)}" ry="${(0.5*S).toFixed(1)}" fill="none" stroke="${isFault?'#ff6a3d':'#ff8a5f'}" stroke-width="1.4"/>`;
      if(isFault) g+=`<ellipse class="shock s2" cx="${c[0]}" cy="${c[1]}" rx="${(0.88*S).toFixed(1)}" ry="${(0.5*S).toFixed(1)}" fill="none" stroke="#ff6a3d" stroke-width="1.1"/>`;
    }

    g+=`<g data-node-hit="${esc(nd.id)}" style="cursor:pointer">`;
    if(kind==='cyl'){
      const c0=P(x,y,0), c1=P(x,y,h), rx=+(w*1.2*S).toFixed(1), ry=+(w*0.69*S).toFixed(1);
      g+=`<path d="M${c0[0]-rx},${c1[1]} L${c0[0]-rx},${c0[1]} A${rx},${ry} 0 0 0 ${c0[0]+rx},${c0[1]} L${c0[0]+rx},${c1[1]} Z" fill="${left}" stroke="${st}"/>`;
      g+=`<path d="M${c0[0]-rx},${(c0[1]+c1[1])/2} A${rx},${ry} 0 0 0 ${c0[0]+rx},${(c0[1]+c1[1])/2}" fill="none" stroke="${st}"/>`;
      g+=`<ellipse cx="${c1[0]}" cy="${c1[1]}" rx="${rx}" ry="${ry}" fill="#2b3a44" stroke="#5b8fb5"/>`;
      g+=`<ellipse cx="${c1[0]}" cy="${c1[1]}" rx="${(rx*(commits>1?0.78:0.52)).toFixed(1)}" ry="${(ry*(commits>1?0.78:0.52)).toFixed(1)}" fill="${commits>1?'#ff8a9c':'#9ccaf0'}" opacity=".32"/>`;
    } else {
      const A=P(x-w,y-w,h), B=P(x+w,y-w,h), C=P(x+w,y+w,h), D=P(x-w,y+w,h), Bd=P(x+w,y-w,0), Cd=P(x+w,y+w,0), Dd=P(x-w,y+w,0);
      g+=poly([D,C,Cd,Dd],left,st)+poly([B,C,Cd,Bd],right,st)+poly([A,B,C,D],top,st,1.2);
      if(kind==='screen'){
        const s1=P(x-w*0.55,y-w*0.1,h), s2=P(x+w*0.1,y-w*0.1,h), s3=P(x+w*0.1,y-w*0.1,h+0.36), s4=P(x-w*0.55,y-w*0.1,h+0.36);
        g+=poly([s1,s2,s3,s4],'#141417',isDim?'#2c2c33':'#4a4a55');
        if(!isDim){
          const l1=P(x-w*0.45,y-w*0.1,h+0.26), l2=P(x-w*0.05,y-w*0.1,h+0.26), l3=P(x-w*0.45,y-w*0.1,h+0.17), l4=P(x-w*0.15,y-w*0.1,h+0.17);
          g+=`<path d="M${l1}L${l2}M${l3}L${l4}" stroke="#6fd4ab" stroke-width="1.6" class="blink"/>`;
        }
      }
      if(kind==='disc'){
        const c=P(x,y,h+0.02);
        g+=`<ellipse cx="${c[0]}" cy="${c[1]}" rx="${(w*0.7*S).toFixed(1)}" ry="${(w*0.4*S).toFixed(1)}" fill="#1f2a24" stroke="#3fb68b"/>`;
      }
      if(isFault){
        const A2=P(x-w*0.6,y-w*0.6,h), C2=P(x+w*0.6,y+w*0.6,h);
        g+=`<line x1="${A2[0]}" y1="${A2[1]}" x2="${C2[0]}" y2="${C2[1]}" stroke="#ff6a3d" stroke-width="1.4" opacity=".75"/>`;
      }
    }
    g+=`</g>`;
  });

  container.dataset.topologyVersion=graph.version;
  container.dataset.nodeCount=String(graph.nodes.length);
  container.dataset.edgeCount=String(graph.edges.length);

  let labelsHtml='';
  order.forEach(nd=>{
    const [x,y]=pos[nd.id];
    const kind=nd.role==='database'?'cyl':nd.role==='approval'?'disc':nd.role==='agent'?'screen':'box';
    const h=kind==='disc'?0.08:kind==='cyl'?0.42:0.34;
    const L=P(x,y,h+(kind==='screen'?0.62:0.42));
    const count=data.counts?.[nd.id]??0;
    const commits=data.commits?.[nd.id]??0;
    const isActive=data.activeNode===nd.id;
    const isFault=isActive && !!data.fault;
    const isDim=!data.preview && count===0 && !isActive;
    const subText=commits?`${roleNames[nd.role]} · 저장 ${commits}건`:`${roleNames[nd.role]} · 사건 ${count}`;
    labelsHtml+=`<button type="button" class="scene-label ${isActive?'selected':''} ${isFault?'fault-label':''} ${count>0?'observed':''} ${isDim?'dim-label':''}" data-node-id="${esc(nd.id)}" aria-label="${esc(nd.label)} · ${esc(roleNames[nd.role])} · 근거 보기" style="left:${(L[0]/W*100).toFixed(1)}%;top:${(L[1]/H*100).toFixed(1)}%"><strong>${esc(nd.label)}</strong><span>${esc(subText)}</span></button>`;
  });

  container.innerHTML=`<svg class="iso-stage-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${g}</svg>${labelsHtml}`;
  container.querySelectorAll('[data-node-id],[data-node-hit]').forEach(el=>{
    el.onclick=e=>{
      e.stopPropagation();
      const id=el.dataset.nodeId||el.dataset.nodeHit;
      if(id) onSelect?.(id);
    };
  });
}

export function mountScene(container,graph,data,onSelect){
  if(!container)return;
  try{
    renderIsoScene(container,graph,data,onSelect);
  }catch(error){
    console.warn('3D unavailable',error);
    container.innerHTML=`<div class="scene-unavailable"><strong>3D 화면을 표시할 수 없습니다.</strong><p>구조 정보와 그래픽 가속을 확인하거나 타임라인을 이용하세요.</p>${data.preview?'<button data-preview-mode="timeline">구조 목록으로 보기 →</button>':'<button data-mode="timeline">타임라인으로 보기 →</button>'}</div>`;
  }
}
export function pauseScene(){}
