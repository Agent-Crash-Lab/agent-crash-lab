# 제조업 QA 설계 공유 준비안

상태: **DRAFT / 팀 리뷰 전 / 실제 Agent 실행 미실시**. 기준: 현재 README와 `main`의 개발 골격. 작성일 2026-10-19.

이 자료는 대화에서 정리한 사용자의 설계를 팀이 검토할 수 있게 옮긴 초안이다. 기존 MVP 범위를 변경하거나 공통 계약을 확정하지 않는다.

## 현재 저장소와 대화에서 보완한 방향

| 구분 | 내용 |
|---|---|
| README의 현재 기준 | 부품 발주 Agent + 사고 조사 Agent. S01/S02/S03, B0/B1 서버 비교 |
| 사용자가 만들고 싶은 QA | 대상의 업무·도구·정책 분석 → 위험 가설 → 적합한 시험 선택 → 실행 → 증거 기반 판정·설명 |
| 가상 검증 대상 | 구매·조달, 생산계획, 품질·출하판정, 설비정비 작업승인 4종 |
| 첫 개발 제안 | 구매 S01~S03부터. 분석·시험 선택을 조사 Agent에 단계로 추가할지 팀 합의 |
| 다음 확장 제안 | 품질을 두 번째 실제 연결 대상으로 검토. 생산·정비는 프로필과 합성 시험부터 준비 |
| 확보한 실제 자료 | BPI2019 실제 익명 구매 로그 표본 10개 항목·132개 이벤트. 실행용 Agent나 정답 데이터는 아님 |
| 아직 없는 것 | 실행 가능한 대상·QA Agent, 실제 시험 결과, 확정 계약, 물리 업무 테이블 |

초기 관심은 윤리·검증이며 이를 승인 준수·권한·중복 방지·정직한 보고·근거 추적으로 구체화했다. 사용자의 과거 경험을 주제의 제한으로 삼지 않는다. Agent의 위험한 시도와 서버가 막아낸 결과를 나눠 평가한다.

## 정한 개발 기준

[개발 기준값과 준비 명령](development-baseline.md)에 수동 승인·한도·재시도·S03 사고·B0/B1 조건을 고정했다. 자료 생성과 실제 Agent 실행을 구분한다.

## 팀에 공유할 자료

1. [Agent 역할·시험·평가 기준](agents-and-evaluation.md): 누가 무엇을 판단하고 어떤 기록으로 확인할지.
2. [아키텍처·논리 ERD·데이터 사용](architecture-and-data.md): 현재 서비스·schema 이름에 맞춘 설계와 준비 순서.
3. [입출력 계약 초안](../../contracts/drafts/manufacturing-qa/README.md): 기존 구매 결과를 유지하는 JSON Schema와 예시.
4. [가상 Agent 프로필](../../fixtures/drafts/manufacturing-qa/agent-profiles.json), [가상 구매 seed](../../fixtures/drafts/manufacturing-qa/purchase-seed.json), [Oracle 정답 사건](../../fixtures/drafts/manufacturing-qa/oracle-cases.json).
5. [시험·규칙 카탈로그](../../scenarios/drafts/manufacturing-qa/catalog.json), [출처 대장](../../fixtures/drafts/manufacturing-qa/sources.json), [실제 구매 로그 안내](../../fixtures/reference/bpi2019/README.md).

## 우선 합의할 결정

| 결정 | 기본 제안 | 확인할 담당 영역 |
|---|---|---|
| 실행할 첫 대상 | 팀이 제공하는 구매 Agent 1종. 외부 상용 제품 연결로 표현하지 않음 | 기획·Agent |
| QA 분석·선택 위치 | 조사 Agent에 PROFILE/PLAN 노드를 추가하는 확장안 | 기획·Agent·Harness |
| 정상 구매 수량 | 재고 20개에서 요청 전체 100개 발주. 부족분 80개가 아님 | 기획·데이터 |
| 승인 경로 | 담당자 확인은 서버에 기록, Agent는 checkpoint에서 대기·재개 | MCP·Agent·Harness |
| S03 재시도 정책 | 최대 1회, 같은 request_id. B0/B1 공통 | Agent·MCP·Oracle |
| 결과 형식 | 현재 구매 계약 유지. 다중 도메인 result_refs는 후속 버전 | Agent·Harness·Frontend |
| 초기 DB와 migration | sandbox/harness 유지, mcp_app 소유로 업무 테이블 생성 | 데이터·MCP·인프라 |
| 외부 API 진입점 | README 목표 Spring 인증 API와 현재 프론트→Harness 설정 정렬 | MCP·Harness·Frontend |

## 실제 채울 위치와 인수 기준

| 담당 산출물 | 리뷰할 초안 위치 | 합의 후 반영할 위치·완료 기준 |
|---|---|---|
| 공통 입출력 | contracts/drafts/manufacturing-qa | contracts의 버전 계약으로 승격하고 양쪽 담당자가 같은 예시 수용 |
| 도구 인자·권한 | Agent 도구 목록과 본 문서 | MCP 담당자가 도구 이름·필수 인자·승인 검증 경로 확인 |
| 시험 정의 | scenarios/drafts/manufacturing-qa | Runner가 시험별 입력·승인·개입·판정 기준을 읽을 수 있음 |
| seed·정답 사건 | fixtures/drafts/manufacturing-qa | 새 run_id로 초기화, Oracle의 정답 사건 판정이 기대와 일치 |
| 데이터·ERD | architecture-and-data.md | 키·유효기간·snapshot·commit·DB 권한을 migration에 반영 |
| 결과·시연 | 실제 실행 이후 | run_id·버전·actual·evidence를 보고서와 연결 |

`drafts/`의 파일은 현재 앱이 자동으로 로드하는 설정이 아니다. 담당자가 리뷰 후 경로·로더·버전을 확정한다. 기대 판정을 실제 결과로 집계하지 않는다.

## 확인한 현재 차이

- 앱 코드·의존성·API가 아직 없어 전체 서비스 실행을 검증할 단계가 아니다.
- `init.sql`은 schema/계정만 만든다. 업무·평가 테이블은 아직 없다.
- README 앞부분의 간단 안내와 뒤의 상세 안내가 중복된다. 기능 구현 범위와 무관하게 문서 담당자가 통합할 수 있다.
- 임의 대상 연결과 상황 자동 생성은 현재 README의 제외 범위다. 기존 시험 선택 확장과 구분해 합의한다.
