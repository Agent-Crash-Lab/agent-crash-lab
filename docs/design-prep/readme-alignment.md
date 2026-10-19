# README 정합성 검토

검토 기준: main c6d1975의 루트 README·프론트엔드 안내와 개발 자료. 2026-10-19.

## 결론

구매 S01/S02/S03, B0/B1 서버 비교, 승인·내용·중복·완료 보고 코드 판정, sandbox/harness 권한 분리는 일치한다. 제조 대상 4종·PROFILE/PLAN 노드는 확장 제안이며 현재 필수 범위를 바꾸지 않는다.

| 검토 항목 | 발견과 보완 | 구현 상태 |
|---|---|---|
| README 중복·상태 | 앞의 중복 개요를 제거하고 최신 정적 UI 데모와 backend 골격 상태를 반영 | 문서 반영 |
| Frontend 설명 | Vite build 인자가 현재 사용된다는 오래된 설명 수정. Three.js 고정 시점 3D와 타임라인 구분 | UI 데모 존재, 실제 API 미연결 |
| Oracle scope | 규칙의 서술용 business/reporting과 결과 schema의 scope가 달랐음. config에 명시적 매핑 추가 | 생성·schema 검사 가능 |
| 승인·commit 시각 | 순번만 있던 row에 UTC decided_at/committed_at 추가 | 합성 fixture·계약 준비 |
| RAG 지침 | 출처 URL만 있었음. 버전 있는 팀 정책 5개와 지침 index 추가 | 색인·검색·Resource loader 미구현 |
| PA/IA/D 시험 | 통합 구매 시험만 있었음. PA01~03·IA01~03·D01~03 명세와 IA 사건 추가 | Agent 시험은 미실행 |
| 이벤트·3D | 공통 이벤트 schema·실제 UI 노드 매핑 추가. 도구/Agent 별칭 표시 | 실 SSE 어댑터 미구현 |

## 실제 개발에서 남은 항목

- S01의 승인 API·checkpoint 재개·업무 저장·독립 Oracle 조회 연결.
- RAG 지침 검색 도구와 원문 Resource, 조사 Agent의 읽기 전용 도구 구현.
- 실제 이벤트 수집·저장·SSE 복구·검사 근거·3D 연결.
- Agent·모델·프롬프트·도구·업무정책·fixture·시나리오·판정기 버전의 실제 실행 manifest 수집.
- Oracle 정답 사례 실행, PA/IA 시험, B0/B1 실제 시험, D01~03 리허설.

자료/입력 생성 테스트 통과와 실제 Agent·서비스 검증 통과는 별도다. 위 기능이 구현됐다고 표시하지 않는다.
