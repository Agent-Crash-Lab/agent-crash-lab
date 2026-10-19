// Registered, declared structures. Coordinates are derived from layer/lane, not agent IDs.
export const purchaseTopology={version:'purchase-topology-v1',nodes:[
 {id:'harness',label:'Harness',role:'runner',layer:0,lane:-1},
 {id:'agent',label:'발주 Agent',role:'agent',layer:0,lane:1},
 {id:'approval',label:'담당자 승인',role:'approval',layer:1,lane:-1},
 {id:'mcp',label:'business-mcp',role:'tool',layer:1,lane:1},
 {id:'oracle',label:'Oracle',role:'reviewer',layer:2,lane:-1},
 {id:'db',label:'업무 DB',role:'database',layer:2,lane:1},
 {id:'investigator',label:'사고 조사 Agent',role:'agent',layer:3,lane:0},
],edges:[
 {id:'start',source:'harness',target:'agent',label:'시험 시작'},
 {id:'approval-request',source:'agent',target:'approval',label:'승인 요청·결정'},
 {id:'call',source:'agent',target:'mcp',label:'업무 도구 호출'},
 {id:'commit',source:'mcp',target:'db',label:'발주 저장'},
 {id:'response',source:'mcp',target:'agent',label:'도구 응답 반환'},
 {id:'snapshot',source:'db',target:'oracle',label:'최종 상태 검사'},
 {id:'evidence',source:'oracle',target:'investigator',label:'검사 근거 조회'},
]};
export const investigationTopology={version:'investigation-topology-v1',nodes:[
 {id:'harness',label:'사건 로더',role:'runner',layer:0,lane:-1},
 {id:'investigator',label:'사고 조사 Agent',role:'agent',layer:0,lane:1},
 {id:'evidence-store',label:'사건 기록',role:'store',layer:1,lane:-1},
 {id:'guide',label:'지침 검색',role:'tool',layer:1,lane:1},
 {id:'report',label:'조사 보고서',role:'report',layer:2,lane:1},
 {id:'reviewer',label:'검사·사람 검토',role:'reviewer',layer:2,lane:-1},
],edges:[
 {id:'load',source:'harness',target:'investigator',label:'사건 제공'},
 {id:'read-evidence',source:'investigator',target:'evidence-store',label:'읽기 전용 근거 조회'},
 {id:'search-guide',source:'investigator',target:'guide',label:'판정 지침 검색'},
 {id:'write-report',source:'investigator',target:'report',label:'사실·가설·부족한 근거'},
 {id:'review',source:'report',target:'reviewer',label:'구조 검사·사람 검토 대기'},
]};
export const registrationExample={id:'research-demo',name:'리서치 Agent',version:'example-v1',topology:{version:'research-topology-v1',nodes:[
 {id:'researcher',label:'리서치 Agent',role:'agent',layer:0},
 {id:'search',label:'문서 검색',role:'tool',layer:1,lane:-1},
 {id:'archive',label:'문서 저장소',role:'store',layer:1,lane:1},
 {id:'answer',label:'근거 포함 답변',role:'report',layer:2},
],edges:[
 {id:'query',source:'researcher',target:'search',label:'검색 요청'},
 {id:'retrieve',source:'search',target:'archive',label:'문서 조회'},
 {id:'compose',source:'researcher',target:'answer',label:'답변 작성'},
]},events:[
 {event_id:'CUSTOM-001',sequence:1,node_id:'researcher',type:'STARTED',title:'리서치 시작'},
 {event_id:'CUSTOM-002',sequence:2,node_id:'search',edge_id:'query',type:'TOOL_CALLED',title:'검색 도구 호출'},
 {event_id:'CUSTOM-003',sequence:3,node_id:'archive',edge_id:'retrieve',type:'DOCUMENTS_FETCHED',title:'문서 근거 조회'},
 {event_id:'CUSTOM-004',sequence:4,node_id:'answer',edge_id:'compose',type:'REPORT_READY',title:'근거를 포함한 답변 작성'},
]};
