# 입출력 계약 초안 — 전원 리뷰 전

README의 공통 계약 리뷰 원칙에 따라 `drafts/`에 준비했다. 현재 서비스가 제공하는 API·확정된 공통 표준이 아니다.

| 파일 | 용도 |
|---|---|
| purchase-result.schema.json | 기존 README의 request_id / outcome / order_id / message 유지 |
| oracle-observation.schema.json | Runner/Oracle이 독립 조회로 구성할 관측 입력. 구매·승인 row 개발 초안 포함 |
| qa-check.schema.json | 항목별 판정·scope·이유·근거 ID |
| examples.json | 정상/거절 결과, 중복 사건의 관측·기대 판정, 시험 계획 예시 |

예시의 PASS/FAIL은 합성 사건의 기대값이다. 실제 Agent 실행 결과가 아니다. 결과 JSON의 문법이 맞아도 발주 성공이 입증되지는 않는다. Agent의 final result와 Oracle의 독립 관측 입력을 나눠서 전달한다.

구매 Agent 입력: 사용자 요청 + 현재 업무 도구 + 회사 정책 + 서버에 기록된 승인 결정. Runner 전용 사고 조건·정답·기대 판정은 제공하지 않는다.

QA 분석 입력: 업무 설명·도구의 인자 schema·권한/승인/재시도 정책·실행 어댑터·관측/주입 가능 기능. 첫 구매 대상의 인자·컨텍스트·오류는 `purchase-tools.json`에 구체화했다. 실제 MCP 구현과 담당자 리뷰는 아직 필요하다.

QA 출력: 선택한 시험과 이유 → 실제 실행 후 항목별 판정·근거 → 조사 설명·부족한 증거·재시험 조건.

`SUCCEEDED`에는 non-null order_id, `REJECTED`에는 null order_id를 요구하는 것은 리뷰할 세부 제안이다. 근거의 실제 존재·같은 run 소속·내용 적합성·trusted producer·승인 권한·정확한 snapshot은 JSON Schema만으로 확인할 수 없고 서버/Oracle 코드가 검사한다.

다중 도메인의 action_type/result_refs는 examples.json의 future proposal로만 기록했다. 이번 구매 계약을 대체하지 않는다. 승인 대기는 실행 상태 WAITING_APPROVAL이며 최종 outcome으로 임의 추가하지 않는다.

합의할 것: (1) 필수/null 필드 (2) ID·시간 형식 (3) 오류·승인 재개 계약 (4) 업무 row 상세 (5) 근거 생성·조회 경로 (6) schema 버전과 승격 위치.

개발 기준: 구매 도구 인자는 `purchase-tools.json`, 공통 한도와 수동 승인 방식은 `config/development-baseline.json`에서 정한다. 관측 row는 모의 DB의 저장된 발주만 포함하며 다른 실행의 row가 섞이면 추가 코드 검사에서 거부해야 한다.


README 정합성 보완: `event.schema.json`·`event-ui-mapping.json`에 공통 이벤트와 현재 UI 노드/필드 매핑을 정의했다. `investigation-tools.json`은 읽기 전용 조사 도구와 현재 데모 별칭의 연결 제안이다. 실제 SSE/도구 어댑터는 미구현이다. 승인·발주 row에는 decided_at/committed_at UTC 시각을 추가했다.
