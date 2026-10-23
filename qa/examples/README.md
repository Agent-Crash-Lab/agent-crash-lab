# QA 예시 데이터 안내

`examples/`에는 검증 대상의 참조 정의와 시험에 쓰는 합성 데이터를 둡니다. 실제 기업 Agent의 설정·실행 로그·사고 정답 데이터가 아닙니다.

## 폴더 구성

| 위치 | 내용 | 주 사용처 |
|---|---|---|
| `targets/agents.json` | 구매·생산·품질의 대상, 샘플, 샘플 제약, 시나리오 요소 | Harness 계획, Scenario Agent, 시뮬레이터, 구매 MCP |
| `purchase/` | 구매 도구 계약, 시뮬레이션 설정, 판정 사례, 결과·관측 스키마 | Harness, Spring MCP |
| `scenarios/` | 시험 목록, 시나리오 카탈로그, 시나리오 검토 사례 | Harness 계획·시나리오 검토 |
| `investigation/` | 조사 Agent가 읽는 고정 사건 사례 | Agent 조사 기능 |
| `validation/` | 데이터 계약 검증용 예시 입력 | 데이터 검증 스크립트 |

## 대상별 참조 모형

| 대상 | 맡긴 업무 | 대표 도구 | 데이터와 출처의 범위 |
|---|---|---|---|
| 구매 `PURCHASE` | 재고·업체·공급 자격 확인 후 발주 | `get_inventory`, `get_supplier_eligibility`, `create_purchase_order` | 프로젝트 합성 Agent·상태. BPI Challenge 2019는 구매 이벤트 구조를 이해하는 참고 표본이며 Agent 구현이나 정답을 복제하지 않음 |
| 생산 `PRODUCTION` | 설비와 선행 공정을 확인해 작업 일정 확정 | `get_machine`, `get_routing`, `assign_operation` | 프로젝트 가상 업무·상태. ISA-95 자료는 업무 범위의 배경이며 특정 기업 Agent의 사례가 아님 |
| 품질 `QUALITY` | 검사 근거를 확인해 로트 출하 여부 결정 | `get_inspection`, `release_lot` | 프로젝트 가상 업무·상태. 공개 품질 사건은 위험의 비AI 유사 사례이지 이 Agent의 원본이 아님 |

세 대상 모두 프로젝트의 참조 모형입니다. 같은 파일의 `agents.PURCHASE`, `agents.PRODUCTION`, `agents.QUALITY`가 공통 형식으로 관리됩니다. `target`은 업무 계약, `sample_data`는 정상 기준 요청과 초기 상태, `sample_constraints`는 허용 가능한 샘플 범위, `scenario_model`은 Scenario Agent가 조합할 변수·값·제약입니다. 구매 실행 어댑터와 생산·품질 시뮬레이터는 계속 업무별 판정 규칙을 담당합니다. 조사 Agent는 QA 결과 조사 역할이며 제조 운영 대상이 아닙니다.

## 변경할 때

- 서비스 간 공통 요청·응답 형식은 [`../contracts/`](../contracts/)에서 관리합니다.
- 업무 대상·샘플·형태학적 조건은 `targets/agents.json`에서 업무 모드별로 관리합니다. JSON Schema 계약은 `contracts/`, MCP 도구의 추가 실행 설정과 판정 사례는 `purchase/`에 둡니다.
- `sample_constraints`는 허용 범위를 설명하고, 실제 샘플은 각 실행 어댑터의 `supports_sample` 검증을 반드시 통과해야 합니다. 업무 Hard Rule과 DB 판정은 JSON 설명만으로 바뀌지 않으며 어댑터 코드와 계약을 함께 검토합니다.
- 경로를 바꾸면 `config/qa-runtime.json`, 서비스 코드, 테스트, 문서의 참조를 함께 갱신합니다.

전체 데이터 흐름은 [데이터 안내](../../docs/data-guide.md), 대상 등록 형식은 [시나리오 데이터 설계](../../docs/scenario-data-design.md)를 참고하세요.

제안 시나리오의 제조업·Agentic 점수 기준과 통과 조건은 [`../knowledge/scenario-review-rubric.json`](../knowledge/scenario-review-rubric.json), 파일 소유권과 협업 규칙은 [`../CONTRIBUTING.md`](../CONTRIBUTING.md)에 있습니다.
