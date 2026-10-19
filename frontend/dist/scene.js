import * as THREE from './vendor/three.module.js';
let engine;
const positions={agent:[-3.1,2.38,.55],investigator:[-3.2,2.38,-.75],mcp:[0,1.25,.4],guide:[.1,1.25,-.85],db:[3.1,.16,.1],oracle:[3.7,.16,-.9]};
const palettes={paper:0xf1f2ed,white:0xfdfdfb,ink:0x35423e,green:0x92a879,orange:0xef7747,muted:0xc0c9c2};
function createEngine(){
 const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.setClearColor(0xf1f3f1,0);renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.35;
 const scene=new THREE.Scene();const camera=new THREE.OrthographicCamera(-7,7,5,-5,.1,100);camera.position.set(10,10,13);camera.lookAt(0,1,0);
 scene.add(new THREE.HemisphereLight(0xffffff,0x93a28c,2.3));const sun=new THREE.DirectionalLight(0xfffaf0,4);sun.position.set(-4,12,5);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);Object.assign(sun.shadow.camera,{left:-11,right:11,top:10,bottom:-10,near:.5,far:35});sun.shadow.bias=-.0005;sun.shadow.normalBias=.035;sun.shadow.radius=7;scene.add(sun);const fill=new THREE.DirectionalLight(0xe1e9ff,1.7);fill.position.set(6,5,-8);scene.add(fill);
 const ground=new THREE.Mesh(new THREE.PlaneGeometry(200,200),new THREE.ShadowMaterial({color:0x46513e,opacity:.12}));ground.rotation.x=-Math.PI/2;ground.position.y=-.44;ground.receiveShadow=true;scene.add(ground);
 const content=new THREE.Group();scene.add(content);const labels=[];const hitTargets=[];const pulses=[];const model={};let host;let callback;let activeRing;let faultMarker;let orderGroup;let animationId;
 const material=(color,extra={})=>new THREE.MeshStandardMaterial({color,roughness:.65,metalness:.08,...extra});
 function addMesh(geometry,mat,x,y,z,parent=content,node=null){const mesh=new THREE.Mesh(geometry,mat);mesh.position.set(x,y,z);mesh.castShadow=true;mesh.receiveShadow=true;parent.add(mesh);if(node){mesh.userData.node=node;hitTargets.push(mesh);}return mesh;}
 function box(w,h,d,x,y,z,color,parent=content,node=null,r=.05){
  const shape=new THREE.Shape();const a=w/2,b=d/2;shape.moveTo(-a+r,-b);shape.lineTo(a-r,-b);shape.quadraticCurveTo(a,-b,a,-b+r);shape.lineTo(a,b-r);shape.quadraticCurveTo(a,b,a-r,b);shape.lineTo(-a+r,b);shape.quadraticCurveTo(-a,b,-a,b-r);shape.lineTo(-a,-b+r);shape.quadraticCurveTo(-a,-b,-a+r,-b);
  const geom=new THREE.ExtrudeGeometry(shape,{depth:h-2*r,bevelEnabled:true,bevelSegments:3,steps:1,bevelSize:r,bevelThickness:r,curveSegments:5});geom.rotateX(-Math.PI/2);geom.translate(0,r,0);return addMesh(geom,material(color),x,y,z,parent,node);
 }
 function label(text,sub,point,node,kind=''){const element=document.createElement('button');element.className=`scene-label ${kind}`;element.innerHTML=`<strong>${text}</strong><span>${sub}</span>`;element.setAttribute('aria-label',`${text} 근거 보기`);element.addEventListener('click',()=>callback?.(node));labels.push({element,point:new THREE.Vector3(...point),node});}
 function cylinder(radius,h,x,y,z,color,parent=content,node=null){return addMesh(new THREE.CylinderGeometry(radius,radius,h,64),material(color),x,y+h/2,z,parent,node);}
 function tube(points,color,radius=.035){const curve=new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p)),false,'catmullrom',.15);const mesh=addMesh(new THREE.TubeGeometry(curve,60,radius,10,false),material(color),0,0,0);return{curve,mesh};}
 function signal(curve){const dot=addMesh(new THREE.SphereGeometry(.065,16,16),material(0xf17946,{emissive:0xe05927,emissiveIntensity:.25}),0,0,0);pulses.push({dot,curve});}
 // Three physically separated terraces with chamfered edges and contact shadows.
 for(const [i,x,y]of [[0,-3.1,2.05],[1,0,.95],[2,3.1,-.15]]){
  box(2.85,.25,2.8,x,y,0,i===1?0xe9ebe5:0xf9faf5,content,null,.06);
  box(2.73,.035,2.69,x,y+.26,0,0xffffff,content,null,.015);
  for(const z of [-1.03,1.03])for(const sx of [-1.03,1.03])cylinder(.035,.018,x+sx,y+.3,z,0xa8afa5);
 }
 // Agent consoles: real screens, stands, vents and inset indicator lights.
 function terminal(x,y,z,node,small=false){const scale=small?.66:1;const group=new THREE.Group();group.position.set(x,y,z);group.scale.setScalar(scale);content.add(group);box(1.02,.12,.76,0,0,0,0xc0c9bf,group,node);box(.2,.4,.2,0,.12,-.08,0x7a8b80,group,node);box(1.13,.78,.29,0,.4,-.15,0xe8eee4,group,node);box(.96,.6,.035,0,.49,.085,0x33473b,group,node,.012);
  for(let i=0;i<3;i++){box(.37-i*.06,.027,.02,-.15,.95-i*.105,.12,0xc5d8a3,group,node,.005);box(.14,.027,.02,.25,.95-i*.105,.12,0x819878,group,node,.005);}cylinder(.035,.025,.4,.14,.15,0x71945e,group,node);return group;}
 terminal(...positions.agent,'agent');terminal(...positions.investigator,'investigator',true);
 label('발주 Agent','승인 확인 · 도구 호출',[-3.6,3.75,1.05],'agent');
 label('조사 Agent','읽기 전용',[-2.95,3.55,-1.05],'investigator','secondary-label');
 // Business MCP: gateway appliance with a prominent orange side casing.
 const [mx,my,mz]=positions.mcp;box(1.2,.77,.9,mx,my,mz,0xed8355,content,'mcp',.06);box(1.07,.1,.78,mx,my+.77,mz,0xf5ad7d,content,'mcp',.035);box(.98,.51,.035,mx,my+.15,mz+.47,0x8e482e,content,'mcp',.012);
 for(let i=0;i<4;i++)box(.65,.032,.035,mx-.05,my+.28+i*.09,mz+.5,0xd99770,content,'mcp',.005);
 cylinder(.04,.025,mx+.4,my+.89,mz+.22,0xfbe9cc,content,'mcp');
 box(.75,.35,.55,.1,1.25,-.85,0xadb8ab,content,'guide');box(.58,.04,.42,.1,1.62,-.85,0xdce2d5,content,'guide',.015);
 label('business-mcp','요청 전달 · 응답 반환',[0,2.78,.45],'mcp');label('rag-mcp','근거 · 지침',[.65,2.02,-1.15],'guide','secondary-label');
 // Database uses stacked machined cylinders. Oracle is a separate physical object.
 for(let i=0;i<3;i++){cylinder(.52,.29,3.0,.17+i*.31,.25,0x526b55,content,'db');cylinder(.525,.045,3.0,.17+i*.31+.26,.25,0x81997a,content,'db');}cylinder(.49,.025,3.0,1.12,.25,0xb1c2a0,content,'db');
 box(.67,.53,.6,3.7,.17,-.85,0xe0e5d9,content,'oracle');box(.5,.14,.03,3.7,.47,-.52,0x4d6151,content,'oracle',.008);
 label('업무 DB','commit으로 확인한 상태',[3.05,1.8,.25],'db');label('Oracle','최종 상태 판정',[3.8,1.15,-.9],'oracle','secondary-label');
 // Physical routed cables connect each logical tier.
 const routeA=tube([[-2.53,2.52,.65],[-1.55,2.52,.65],[-1.4,1.54,.65],[-.6,1.54,.65]],0xb9c6af,.045);signal(routeA.curve);
 const routeB=tube([[.61,1.53,.65],[1.5,1.53,.65],[1.65,.48,.65],[2.49,.48,.65]],0x7b956b,.045);signal(routeB.curve);
 const backA=tube([[-.6,1.55,-.2],[-1.02,1.55,-.2],[-1.2,2.7,-.2]],0xe98a5d,.025);
 const backB=tube([[-1.42,2.7,-.2],[-1.7,2.7,-.2],[-2.53,2.7,-.2]],0xe98a5d,.025);
 faultMarker=addMesh(new THREE.OctahedronGeometry(.15),material(0xef7845,{emissive:0xe45e29,emissiveIntensity:.15}),-1.3,2.7,-.2,content,'fault');
 label('응답 유실','모의 timeout · 1회',[-1.3,3.25,-.2],'fault','fault-label');
 orderGroup=new THREE.Group();content.add(orderGroup);
 activeRing=new THREE.Mesh(new THREE.TorusGeometry(.72,.014,8,80),new THREE.MeshBasicMaterial({color:0xf0864b,transparent:true,opacity:.8}));activeRing.rotation.x=-Math.PI/2;content.add(activeRing);
 const raycaster=new THREE.Raycaster();const pointer=new THREE.Vector2();
 renderer.domElement.addEventListener('pointerup',event=>{const rect=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);const hit=raycaster.intersectObjects(hitTargets).find(h=>h.object.visible);if(hit)callback?.(hit.object.userData.node);});
 function resize(){if(!host?.isConnected)return;const w=host.clientWidth,h=host.clientHeight;const aspect=w/h;const halfWidth=6.7;camera.left=-halfWidth;camera.right=halfWidth;camera.top=halfWidth/aspect;camera.bottom=-halfWidth/aspect;camera.updateProjectionMatrix();renderer.setSize(w,h);positionLabels();renderer.render(scene,camera);}
 function positionLabels(){if(!host)return;for(const l of labels){const p=l.point.clone().project(camera);l.element.style.left=`${(p.x*.5+.5)*host.clientWidth}px`;l.element.style.top=`${(-p.y*.5+.5)*host.clientHeight}px`;}}
 const observer=new ResizeObserver(resize);
 function update(data){Object.assign(model,data);labels.find(l=>l.node==='db').element.querySelector('span').textContent=`발주 ${model.orders}건 · commit 기록`;faultMarker.visible=model.fault;backA.mesh.visible=model.fault;backB.mesh.visible=model.fault;labels.find(l=>l.node==='fault').element.hidden=!model.fault;
  while(orderGroup.children.length){const m=orderGroup.children[0];const targetIndex=hitTargets.indexOf(m);if(targetIndex!==-1)hitTargets.splice(targetIndex,1);m.geometry?.dispose();m.material?.dispose();orderGroup.remove(m);}for(let i=0;i<model.orders;i++)box(.58,.08,.8,2.36,.2+i*.12,1, i?0xf6a070:0xc2d2b0,orderGroup,'db',.015);
  const pos=positions[model.active]||positions.mcp;activeRing.position.set(pos[0],pos[1]+.02,pos[2]);activeRing.visible=model.active!=='fault';
  labels.forEach(l=>l.element.classList.toggle('selected',l.node===model.active));pulses.forEach(p=>p.dot.visible=!!model.playing);resize();
 }
 function animate(time){if(host?.isConnected){if(model.playing&&!matchMedia('(prefers-reduced-motion: reduce)').matches){for(const [i,p]of pulses.entries()){p.dot.position.copy(p.curve.getPoint(((time/2200)+i*.4)%1));}renderer.render(scene,camera);} }animationId=requestAnimationFrame(animate);}
 animationId=requestAnimationFrame(animate);
 return {mount(container,data,onSelect){if(host!==container){observer.disconnect();host=container;container.append(renderer.domElement);labels.forEach(l=>container.append(l.element));observer.observe(container);}callback=onSelect;update(data);},unmount(){observer.disconnect();host=null;},renderer};
}
export function mountScene(container,data,onSelect){if(!container)return;try{engine??=createEngine();engine.mount(container,data,onSelect);}catch(error){console.warn('3D unavailable',error);container.innerHTML='<div class="scene-unavailable"><strong>3D 화면을 표시할 수 없습니다.</strong><p>브라우저의 그래픽 가속을 확인하거나 타임라인에서 사건을 살펴보세요.</p><button data-mode="timeline">타임라인으로 보기 →</button></div>';}}
export function pauseScene(){engine?.unmount();}
