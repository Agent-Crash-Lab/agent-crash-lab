import * as THREE from './vendor/three.module.js';
import { layoutTopology } from './topology.js?v=0.15.0';
let engine,engineKey;
const roleNames={agent:'Agent',runner:'실행 준비',approval:'승인',tool:'도구',database:'업무 상태',store:'읽기 전용 자료',report:'결과 문서',reviewer:'검사·검토'};
function createEngine(graph){
 const layout=layoutTopology(graph),positions=new Map(layout.nodes.map(n=>[n.id,n.position]));
 const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.setClearColor(0xf1f3f1,0);renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.35;
 const scene=new THREE.Scene(),camera=new THREE.OrthographicCamera(-7,7,5,-5,.1,100);camera.position.set(10,10,13);camera.lookAt(0,1,0);camera.updateMatrixWorld();
 scene.add(new THREE.HemisphereLight(0xffffff,0x93a28c,2.3));const sun=new THREE.DirectionalLight(0xfffaf0,4);sun.position.set(-4,14,5);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);Object.assign(sun.shadow.camera,{left:-20,right:20,top:20,bottom:-20,near:.5,far:50});sun.shadow.bias=-.0005;sun.shadow.normalBias=.035;scene.add(sun);const fill=new THREE.DirectionalLight(0xe1e9ff,1.7);fill.position.set(6,5,-8);scene.add(fill);
 const ground=new THREE.Mesh(new THREE.PlaneGeometry(200,200),new THREE.ShadowMaterial({color:0x46513e,opacity:.12}));ground.rotation.x=-Math.PI/2;ground.position.y=-.45;ground.receiveShadow=true;scene.add(ground);
 const content=new THREE.Group();scene.add(content);const labels=[],hitTargets=[],routes=[];let host,callback,animationId,model={counts:{},commits:{},observedEdges:[]};
 const material=(color)=>new THREE.MeshStandardMaterial({color,roughness:.65,metalness:.08});
 function add(geometry,mat,x,y,z,parent=content,node){const m=new THREE.Mesh(geometry,mat);m.position.set(x,y,z);m.castShadow=true;m.receiveShadow=true;parent.add(m);if(node){m.userData.node=node;hitTargets.push(m);}return m;}
 function box(w,h,d,x,y,z,color,parent=content,node,r=.04){
  r=Math.min(r,h/3,w/4,d/4);const s=new THREE.Shape(),a=w/2,b=d/2;s.moveTo(-a+r,-b);s.lineTo(a-r,-b);s.quadraticCurveTo(a,-b,a,-b+r);s.lineTo(a,b-r);s.quadraticCurveTo(a,b,a-r,b);s.lineTo(-a+r,b);s.quadraticCurveTo(-a,b,-a,b-r);s.lineTo(-a,-b+r);s.quadraticCurveTo(-a,-b,-a+r,-b);
  const g=new THREE.ExtrudeGeometry(s,{depth:h-2*r,bevelEnabled:true,bevelSegments:3,steps:1,bevelSize:r,bevelThickness:r,curveSegments:4});g.rotateX(-Math.PI/2);g.translate(0,r,0);return add(g,material(color),x,y,z,parent,node);
 }
 const cylinder=(radius,h,x,y,z,color,parent=content,node)=>add(new THREE.CylinderGeometry(radius,radius,h,40),material(color),x,y+h/2,z,parent,node);
 function terminal(g,id){box(.95,.1,.7,0,0,0,0xc0c9bf,g,id);box(.18,.35,.18,0,.1,-.1,0x7a8b80,g,id);box(1.05,.72,.26,0,.4,-.15,0xe8eee4,g,id);box(.88,.54,.03,0,.49,0,0x33473b,g,id);for(let i=0;i<3;i++)box(.48-i*.07,.025,.02,-.1,.9-i*.11,.03,0xc5d8a3,g,id);}
 for(const p of layout.platforms){box(2.9,.25,p.depth,p.x,p.y,0,0xf5f6f0);box(2.8,.035,p.depth-.12,p.x,p.y+.26,0,0xffffff);for(const z of [-p.depth/2+.2,p.depth/2-.2])for(const x of [-1.2,1.2])cylinder(.035,.015,p.x+x,p.y+.3,z,0xa8afa5);}
 for(const n of layout.nodes){
  const group=new THREE.Group();group.position.set(...n.position);content.add(group);const id=n.id;
  if(n.role==='agent')terminal(group,id);
  else if(n.role==='database'){for(let i=0;i<3;i++){cylinder(.48,.26,0,i*.29,0,0x526b55,group,id);cylinder(.49,.035,0,i*.29+.24,0,0x91a783,group,id);}cylinder(.47,.025,0,.87,0,0xb1c2a0,group,id);}
  else if(n.role==='tool'){box(1.08,.72,.83,0,0,0,0xed8355,group,id);box(.98,.09,.75,0,.72,0,0xf5ad7d,group,id);box(.88,.45,.035,0,.15,.44,0x8e482e,group,id);for(let i=0;i<4;i++)box(.65,.026,.03,-.04,.23+i*.08,.47,0xd99770,group,id);}
  else if(n.role==='store'){for(let i=0;i<3;i++){box(.85,.14,.8,0,.08+i*.21,0,0x8da7a6,group,id);box(.7,.06,.72,0,.22+i*.21,0,0xd6e2db,group,id);}}
  else if(n.role==='report'){box(.94,.12,1.03,0,.05,0,0xb9c8b0,group,id);for(let i=0;i<3;i++)box(.82,.035,.9,i*.025,.19+i*.07,-i*.025,0xfcfcf6,group,id);for(let i=0;i<3;i++)box(.58-i*.08,.014,.025,0,.38,-.2+i*.15,0x8c9c82,group,id);}
  else if(n.role==='approval'){box(.9,.2,.8,0,.05,0,0xd4ddc4,group,id);cylinder(.28,.13,0,.25,0,0x809961,group,id);box(.28,.04,.055,0,.39,0,0xf5f7ed,group,id);}
  else{box(.84,.55,.72,0,.02,0,n.role==='runner'?0xb5c4c1:0xe0e5d9,group,id);box(.62,.18,.025,0,.3,.38,0x4d6151,group,id);}
  const el=document.createElement('button');el.className='scene-label';el.dataset.nodeId=id;el.setAttribute('aria-label',`${n.label} · ${roleNames[n.role]} · 근거 보기`);const title=document.createElement('strong'),sub=document.createElement('span');title.textContent=n.label;el.append(title,sub);el.addEventListener('click',()=>callback?.(id));labels.push({element:el,sub,node:n,point:new THREE.Vector3(n.position[0],n.position[1]+1.6,n.position[2])});
 }
 graph.edges.forEach((edge,index)=>{
  const from=new THREE.Vector3(...positions.get(edge.source)),to=new THREE.Vector3(...positions.get(edge.target));from.y+=.35;to.y+=.35;
  const reverse=graph.edges.some(e=>e.source===edge.target&&e.target===edge.source),offset=reverse?(edge.source<edge.target?.3:-.3):.06*(index%3);
  from.z+=offset;to.z+=offset;
  const mid=from.clone().lerp(to,.5);mid.y+=.2;mid.z+=offset;
  const curve=new THREE.CatmullRomCurve3([from,from.clone().lerp(mid,.65),mid,to.clone().lerp(mid,.65),to],false,'catmullrom',.1);
  const mesh=add(new THREE.TubeGeometry(curve,40,.028,8,false),material(0xc6cec0),0,0,0);
  const arrow=new THREE.ArrowHelper(curve.getTangent(.66).normalize(),curve.getPoint(.66),.34,0x9ba991,.15,.12);content.add(arrow);
  const dot=add(new THREE.SphereGeometry(.065,12,12),material(0xef7845),0,0,0);dot.visible=false;
  routes.push({id:edge.id,curve,mesh,arrow,dot});
 });
 const ring=add(new THREE.TorusGeometry(.69,.018,8,64),new THREE.MeshBasicMaterial({color:0xf0864b}),0,0,0);ring.rotation.x=-Math.PI/2;ring.visible=false;
 const faultMarker=add(new THREE.OctahedronGeometry(.15),material(0xef7845),0,0,0);faultMarker.visible=false;
 // Fit the complete registered graph, including labels, in the fixed isometric view.
 const fitting=[];for(const n of layout.nodes)for(const dx of [-1.4,1.4])for(const dy of [-.3,2.1])for(const dz of [-1,1])fitting.push(new THREE.Vector3(n.position[0]+dx,n.position[1]+dy,n.position[2]+dz).applyMatrix4(camera.matrixWorldInverse));
 const minX=Math.min(...fitting.map(p=>p.x)),maxX=Math.max(...fitting.map(p=>p.x)),minY=Math.min(...fitting.map(p=>p.y)),maxY=Math.max(...fitting.map(p=>p.y));
 function resize(){if(!host?.isConnected||!host.clientWidth||!host.clientHeight)return;const w=host.clientWidth,h=host.clientHeight,aspect=w/h;let halfW=(maxX-minX)/2+.45,halfH=(maxY-minY)/2+.3;if(halfW/halfH<aspect)halfW=halfH*aspect;else halfH=halfW/aspect;const cx=(minX+maxX)/2,cy=(minY+maxY)/2;camera.left=cx-halfW;camera.right=cx+halfW;camera.top=cy+halfH;camera.bottom=cy-halfH;camera.updateProjectionMatrix();renderer.setSize(w,h);for(const l of labels){const p=l.point.clone().project(camera);l.element.style.left=`${(p.x*.5+.5)*w}px`;l.element.style.top=`${(-p.y*.5+.5)*h}px`;}renderer.render(scene,camera);}
 const observer=new ResizeObserver(resize),raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();
 renderer.domElement.addEventListener('pointerup',event=>{const r=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-r.left)/r.width*2-1,-(event.clientY-r.top)/r.height*2+1);raycaster.setFromCamera(pointer,camera);const hit=raycaster.intersectObjects(hitTargets)[0];if(hit)callback?.(hit.object.userData.node);});
 function update(data){model=data;for(const l of labels){const count=model.counts?.[l.node.id]??0;const commits=model.commits?.[l.node.id]??0;l.sub.textContent=commits?`${roleNames[l.node.role]} · 저장 ${commits}건`:`${roleNames[l.node.role]} · 사건 ${count}`;l.element.classList.toggle('selected',l.node.id===model.activeNode);l.element.classList.toggle('observed',count>0);}
  const pos=positions.get(model.activeNode);ring.visible=!!pos;if(pos)ring.position.set(pos[0],pos[1]+.025,pos[2]);
  for(const route of routes){const active=route.id===model.activeEdge,seen=model.observedEdges?.includes(route.id);const color=active?0xef7845:seen?0x789664:0xc6cec0;route.mesh.material.color.setHex(color);route.arrow.setColor(color);route.dot.visible=active&&!!model.playing;}
  const faultRoute=routes.find(r=>r.id===model.activeEdge);faultMarker.visible=!!(model.fault&&faultRoute);if(faultMarker.visible)faultMarker.position.copy(faultRoute.curve.getPoint(.5));resize();
 }
 function animate(time){if(host?.isConnected&&model.playing&&!matchMedia('(prefers-reduced-motion: reduce)').matches){for(const r of routes)if(r.dot.visible)r.dot.position.copy(r.curve.getPoint((time/2200)%1));renderer.render(scene,camera);}animationId=requestAnimationFrame(animate);}animationId=requestAnimationFrame(animate);
 return{mount(container,data,onSelect){if(host!==container){observer.disconnect();host=container;host.dataset.topologyVersion=graph.version;host.dataset.nodeCount=String(graph.nodes.length);host.dataset.edgeCount=String(graph.edges.length);container.append(renderer.domElement);for(const l of labels)container.append(l.element);observer.observe(container);}callback=onSelect;update(data);},unmount(){observer.disconnect();host=null;},dispose(){observer.disconnect();cancelAnimationFrame(animationId);scene.traverse(o=>{o.geometry?.dispose();if(Array.isArray(o.material))o.material.forEach(m=>m.dispose());else o.material?.dispose();});labels.forEach(l=>l.element.remove());renderer.dispose();renderer.domElement.remove();host=null;}};
}
export function mountScene(container,graph,data,onSelect){if(!container)return;try{const key=JSON.stringify(graph);if(!engine||engineKey!==key){engine?.dispose();engine=undefined;engine=createEngine(graph);engineKey=key;}engine.mount(container,data,onSelect);}catch(error){console.warn('3D unavailable',error);container.innerHTML=`<div class="scene-unavailable"><strong>3D 화면을 표시할 수 없습니다.</strong><p>구조 정보와 그래픽 가속을 확인하거나 타임라인을 이용하세요.</p>${data.preview?'<button data-preview-mode="timeline">구조 목록으로 보기 →</button>':'<button data-mode="timeline">타임라인으로 보기 →</button>'}</div>`;}}
export function pauseScene(){engine?.unmount();}
