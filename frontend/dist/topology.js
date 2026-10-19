// Public, renderer-independent structure contract. No code or URLs are executed.
export const nodeRoles = ['agent','runner','approval','tool','database','store','report','reviewer'];
const identifier = value => typeof value === 'string' && /^[a-zA-Z][a-zA-Z0-9_-]{0,47}$/.test(value) && !['constructor','prototype','__proto__'].includes(value);
const shortText = (value, max=80) => typeof value === 'string' && value.trim().length > 0 && value.length <= max;
export function validateTopology(graph) {
  const errors=[];
  if(!graph || typeof graph!=='object')return {ok:false,errors:['구조 객체가 필요합니다.']};
  if(!shortText(graph.version,48))errors.push('구조 version은 1~48자 문자열이어야 합니다.');
  if(!Array.isArray(graph.nodes)||graph.nodes.length<1||graph.nodes.length>16)errors.push('nodes는 1~16개여야 합니다.');
  if(!Array.isArray(graph.edges)||graph.edges.length>32)errors.push('edges는 최대 32개인 배열이어야 합니다.');
  if(errors.length)return{ok:false,errors};
  const ids=new Set(),edgeIds=new Set(),slots=new Set();
  for(const n of graph.nodes){
    if(!n||!identifier(n.id)){errors.push('노드 id 형식을 확인하세요.');continue;}
    if(ids.has(n.id))errors.push(`중복 노드: ${n.id}`);ids.add(n.id);
    if(!shortText(n.label,40))errors.push(`${n.id}: label은 1~40자여야 합니다.`);
    if(!nodeRoles.includes(n.role))errors.push(`${n.id}: 지원하지 않는 역할입니다.`);
    if(!Number.isInteger(n.layer)||n.layer<0||n.layer>5)errors.push(`${n.id}: layer는 0~5 정수여야 합니다.`);
    if(n.lane!==undefined){if(!Number.isInteger(n.lane)||Math.abs(n.lane)>4)errors.push(`${n.id}: lane은 -4~4 정수여야 합니다.`);const slot=`${n.layer}:${n.lane}`;if(slots.has(slot))errors.push(`${n.id}: 같은 layer/lane에 노드가 겹칩니다.`);slots.add(slot);}
  }
  for(const e of graph.edges){
    if(!e||!identifier(e.id)){errors.push('연결 id 형식을 확인하세요.');continue;}
    if(edgeIds.has(e.id))errors.push(`중복 연결: ${e.id}`);edgeIds.add(e.id);
    if(!ids.has(e.source)||!ids.has(e.target))errors.push(`${e.id}: 존재하지 않는 연결 끝점입니다.`);
    if(e.source===e.target)errors.push(`${e.id}: 자기 자신을 향하는 연결은 지원하지 않습니다.`);
    if(!shortText(e.label,60))errors.push(`${e.id}: label은 1~60자여야 합니다.`);
  }
  return {ok:errors.length===0,errors};
}
export function layoutTopology(graph){
  const result=validateTopology(graph);if(!result.ok)throw new Error(result.errors.join('\n'));
  const layers=[...new Set(graph.nodes.map(n=>n.layer))].sort((a,b)=>a-b);
  const nodes=[],platforms=[];
  layers.forEach((layer,index)=>{
    const members=graph.nodes.filter(n=>n.layer===layer),used=new Set(members.filter(n=>n.lane!==undefined).map(n=>n.lane));
    const assigned=members.map(n=>{let lane=n.lane;if(lane===undefined){lane=0;while(used.has(lane))lane=lane>0?-lane:1-lane;used.add(lane);}return{...n,lane};});
    const middle=(Math.min(...assigned.map(n=>n.lane))+Math.max(...assigned.map(n=>n.lane)))/2;
    const x=(index-(layers.length-1)/2)*3.5,y=(layers.length-1-index)*.85;
    assigned.forEach(n=>nodes.push({...n,position:[x,y,(n.lane-middle)*1.8]}));
    const depth=Math.max(2.5,(Math.max(...assigned.map(n=>n.lane))-Math.min(...assigned.map(n=>n.lane)))*1.8+2.2);
    platforms.push({layer,x,y:y-.3,depth});
  });
  return {nodes,platforms};
}
export function mapEvents(graph,events){
  const nodes=new Map(graph.nodes.map(n=>[n.id,n])),edges=new Map(graph.edges.map(e=>[e.id,e]));
  return events.map(event=>{
    if(!event||typeof event!=='object')return{event:{},node:null,edge:null,errors:['이벤트 객체가 필요합니다.'],ok:false};
    const node=nodes.get(event.node_id),edge=event.edge_id?edges.get(event.edge_id):null,errors=[];
    if(!node)errors.push(`미등록 노드: ${event.node_id??'(없음)'}`);
    if(event.edge_id&&!edge)errors.push(`미등록 연결: ${event.edge_id}`);
    if(edge&&node&&edge.source!==node.id&&edge.target!==node.id)errors.push('이벤트 노드가 해당 연결의 끝점이 아닙니다.');
    return{event,node:node??null,edge:errors.length?null:edge,errors,ok:errors.length===0};
  });
}
export function frameFor(graph,events,cursor,selectedIndex=cursor){
  const mapped=mapEvents(graph,events),visible=mapped.slice(0,cursor+1),active=mapped[selectedIndex];
  return {activeNode:active?.ok?active.node.id:null,activeEdge:active?.ok?active.edge?.id:null,fault:active?.event.type==='FAULT_INJECTED',
    counts:Object.fromEntries(graph.nodes.map(n=>[n.id,visible.filter(m=>m.ok&&m.node.id===n.id).length])),
    commits:Object.fromEntries(graph.nodes.map(n=>[n.id,visible.filter(m=>m.ok&&m.node.id===n.id&&m.event.type==='BUSINESS_COMMITTED').length])),
    observedEdges:[...new Set(visible.filter(m=>m.ok&&m.edge).map(m=>m.edge.id))],unmapped:mapped.filter(m=>!m.ok)};
}
export function validateRegistration(input){
  const errors=[];
  if(!input||typeof input!=='object')return{ok:false,errors:['등록 객체가 필요합니다.']};
  if(!identifier(input.id))errors.push('Agent id는 영문으로 시작하는 1~48자 식별자여야 합니다.');
  if(!shortText(input.name,40)||!shortText(input.version,48))errors.push('Agent 이름과 버전이 필요합니다.');
  const graphResult=validateTopology(input.topology);errors.push(...graphResult.errors);
  const events=input.events??[];
  if(!Array.isArray(events)||events.length>200)errors.push('events는 최대 200개인 배열이어야 합니다.');
  else{
    const ids=new Set();
    events.forEach((e,i)=>{
      if(!e||!identifier(e.event_id)||ids.has(e.event_id))errors.push(`이벤트 ${i+1}: 고유 event_id가 필요합니다.`);
      ids.add(e?.event_id);
      if(e?.sequence!==i+1)errors.push(`이벤트 ${i+1}: sequence는 1부터 연속이어야 합니다.`);
      if(!shortText(e?.type,48)||!shortText(e?.title,80))errors.push(`이벤트 ${i+1}: type과 title이 필요합니다.`);
    });
    if(graphResult.ok)for(const m of mapEvents(input.topology,events))errors.push(...m.errors.map(e=>`${m.event.event_id}: ${e}`));
  }
  if(errors.length)return{ok:false,errors};
  // Keep only the supported contract. Imported objects never become executable code.
  const graph={version:input.topology.version,nodes:input.topology.nodes.map(n=>({id:n.id,label:n.label,role:n.role,layer:n.layer,...(n.lane!==undefined?{lane:n.lane}:{})})),edges:input.topology.edges.map(e=>({id:e.id,source:e.source,target:e.target,label:e.label}))};
  return{ok:true,errors:[],profile:{id:input.id,name:input.name,version:input.version,custom:true,topology:graph,events:events.map(e=>({event_id:e.event_id,sequence:e.sequence,node_id:e.node_id,...(e.edge_id?{edge_id:e.edge_id}:{}),type:e.type,title:e.title,payload:e.payload??{}}))}};
}
