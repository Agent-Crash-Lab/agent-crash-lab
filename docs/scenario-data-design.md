# Scenario Agent의 대상 설명·위험·근거 데이터

이 문서는 **현재 구현된 분류와 저장 구조**를 설명한다. 아래의 문헌 연결은 제조업에서 관찰된 사건을 Agent가 일으켰다는 주장이 아니라, 격리된 참조 환경에서 시험할 상황으로 옮긴 프로젝트 해석이다.

## 1. 검증 대상 Agent를 어떻게 기술하는가?

대상 등록 입력은 `harness/src/harness/registrations.py`의 `Registration`이고, 서비스 간 계약은 `qa/contracts/qa.schema.json`의 `target`·`sample`이다. 두 형식을 구별해야 한다. `Registration`은 사람이 제공한 설명과 연결 정보를 포함하고, Harness는 이를 Scenario Agent가 읽는 `target`·`sample_data`로 정규화한다.

| 묶음 | 대표 필드 | 목적·해석 |
|---|---|---|
| 식별·업무 | `name`, `version`, `agent_type`, `task`, `industry_context` | 어떤 업무를 시험하는지 선언. `agent_type`은 `PURCHASE`, `PRODUCTION`, `QUALITY`, `COMMON` 중 하나 |
| 도구 | `tools[] {name, effect, input_schema, description}` | 조회(`READ`)와 변경(`WRITE`) 권한 및 입력 형식. 실제 내부 코드 분석 결과가 아니라 등록한 계약 |
| 정책 | `policies {approval_required, max_write_retries}` | 승인과 재시도 조건. 값이 없으면 추정하지 않고 설계를 보류 |
| 기능 연결 | `capability_bindings[] {name, tool_name, basis}`, `excluded_capabilities[]` | `machine_read`, `schedule_write` 등의 기능을 선언된 도구와 연결. 등록 UI의 `basis`는 `DECLARED`이며 연결만으로 실행 검증을 뜻하지 않음 |
| 시험 샘플 | `business_input_schema`, `sample_data {business_input, initial_state}` | JSON Schema로 업무 요청을 검사하고, 샘플을 새로운 시험 상태의 기준으로 사용 |
| 실행 연결 | `execution_runtime` → `simulation_adapter`, 별도 `execution_binding` | 실제 도구·상태 주입·판정기와 맞는지 Harness가 검사. 기본 미연결 등록은 설계만 가능 |

예를 들어 생산 대상은 `get_machine`·`get_routing`을 조회 도구로, `assign_operation`을 변경 도구로 선언한다. `schedule_write → assign_operation` 연결이 있어야 설비 제약 위험을 적용 대상으로 분류할 수 있다. `sample_data`에는 설비 ID와 요청 시간, 현재 설비 상태·기존 일정·선행 공정 완료 시각을 둔다. 참조 입력은 `qa/examples/targets/agents.json`의 `agents.PRODUCTION`에서 확인한다. `agent_type`을 등록했더라도 없는 도구 기능을 자동 추론하지 않는다.

구매·생산·품질 참조 구현은 모두 프로젝트가 만든 합성 Agent다. 실제 Agent의 코드나 실행 로그를 복제하지 않았다. 구매의 BPI2019 표본은 업무 이벤트 구조의 참고 자료이고, ISA 공개 해설은 제조 운영 업무 범위의 배경이며, Kobe·CSB 사건은 위험 상황의 비AI 유사 사례다. 대상별 기능·구현·자료의 역할과 `qa/examples/` 파일 지도는 [참조 Agent 길잡이](../qa/examples/README.md)에 있다.

등록 기록은 사용자별 `harness_qa_target`에 저장되며 입력, 분석 결과, 확인되지 않은 정책, 위험 라이브러리 해시, 실행 연결 상태를 보존한다. 내용이 달라지면 새 식별자로 등록한다. Scenario Agent가 만든 설계는 Harness가 계획으로 묶어 사용자별 `harness_qa_plan`에 저장한다.

## 2. 카테고리는 서로 다른 질문에 답한다

### 시나리오 설계 원칙: 가장 작은 유효 실험부터

이 프로젝트의 우선순위는 **LLM이 간단한 시나리오를 새로 만들고, 코드가 실제 조건이 만들어졌는지 검증하는 것**이다. 먼저 정상 업무 하나와 예외 하나로 시작한다. 복합 예외는 특정 상호작용을 시험해야 할 때만 추가한다. 기본 서버 모드는 유료 호출을 하지 않는 offline이며, 유료 LLM 실험은 별도 허용을 받은 경우에만 실행한다.

최소 LLM 실험은 `정상 업무 → 변수값 조합 → 구체적 시험 데이터와 기대 안전 행동 생성 → 코드 상태 검사`로 구성한다. 검증 보고에는 생성한 조건, 코드가 확인한 조건, Agent 판단을 실제 실행했는지를 구분해 기록한다. 상태 검사만 통과한 것은 시나리오 데이터가 유효하다는 뜻이지 Agent가 안전하게 행동했다는 뜻이 아니다. 발표용 설명 예시는 [형태학적 분석 쉬운 예시](morphological-analysis-for-presentation.md)를 본다.

생성안 검증은 **제안별로 격리**한다. 도구·위험 범위·인용 ID·시험 데이터 스키마를 먼저 검사하고, 실패한 제안은 `CODE_PREREQUISITES`와 이유를 기록한다. 나머지 유효한 제안은 제조업 검토와 Agentic 검토를 계속한다. 중복 `proposal_id`처럼 어떤 제안이 어느 판정에 속하는지 모호한 경우에만 전체 응답을 거절한다. 따라서 한 안의 잘못된 인용이나 필드가 다른 안의 평가를 없애지 않는다.

| 축 | 현재 값·예 | 답하는 질문 |
|---|---|---|
| 대상 업무 유형 | `PURCHASE`·`PRODUCTION`·`QUALITY`·`COMMON` | 어느 업무의 도구·상태를 해석할 것인가? |
| 기능 | `inspection_read`, `machine_read`, `schedule_write`, `release_write` 등 | 해당 위험을 시험할 조회·변경 경로가 선언됐는가? |
| 정상 사용 시나리오 | 업무 맥락·변경 도구·조회 정보·의사결정 권한의 `U..` 후보 | 예외가 없어도 의미 있는 정상 업무인가? |
| 적용 예외 | `E_..` ID, 조건, `INITIAL` 또는 `AFTER_APPROVAL_BEFORE_WRITE` | 어떤 상태·오류가 언제 발생하는가? |
| 프로젝트 위험 계열 | 아래 6개 `risk_key` | 무엇을 시험 대상으로 묶을 것인가? |
| 문헌 종류 | `INCIDENT`, `RESEARCH`, `TECHNICAL`, `PROJECT_POLICY`, `REFERENCE` | 자료가 사건·연구·지침·참조 정책 중 무엇인가? |
| 검토 영역 | `MANUFACTURING`, `AGENTIC` | 자료가 어느 의미 검토의 근거로 허용되는가? |
| 실행 판정 | `READY`·`UNSUPPORTED`, 이후 코드 판정 | 현재 어댑터에서 주입·관측·판정 가능한가? |

현재 `qa/knowledge/risk-library.json`의 여섯 계열은 **프로젝트가 만든 시험 분류**이며 외부 표준이나 순수 Agent 오류 분류가 아니다.

| 위험 계열 | 참조 업무·시험 예 | 대표 필요 기능 |
|---|---|---|
| `AMBIGUOUS_WRITE` | 응답 유실 후 동일 요청 재시도로 중복 변경 | 변경 도구·재시도 |
| `APPROVAL_BYPASS` | 승인 거절 뒤 변경 시도 | 변경 도구·승인 |
| `UNVERIFIED_EVIDENCE` | 검사 원자료 누락·불합격 상태에서 출하 확정 | 검사 조회·변경 |
| `RESOURCE_CONSTRAINT` | 정비·일정 중복·선행 공정 지연 상태에서 배정 | 설비 조회·일정 변경 |
| `UNTRUSTED_INSTRUCTIONS` | 외부 문서의 지시를 업무 명령으로 수용 | 외부 텍스트 조회·변경 |
| `SUPPLIER_QUALIFICATION` | 품목·공장·구매조직에 승인되지 않은 공급원 발주 | 공급 자격 조회·발주 |

`risk_key`는 **업무 제약**(`RESOURCE_CONSTRAINT`), **도구·응답 오류**(`AMBIGUOUS_WRITE`), **권한 경로**(`APPROVAL_BYPASS`)를 한 목록에 담고 있다. 따라서 이 값만으로 Agent 실패 원인을 판정하지 않는다. 여섯 계열이 모두 생성·실행된다는 뜻도 아니다. 예를 들어 `UNTRUSTED_INSTRUCTIONS`에는 현재 지원되는 예외 주입 항목이 없어 LLM 설계의 적용 위험에서 빠진다. 향후 분석을 넓힐 때는 `업무 불변 조건`, `주입 예외`, `관찰된 Agent 행동`, `서버 차단/저장 결과`를 별도 필드로 유지하고 서로의 연결을 검증해야 한다. 현재도 정상 사용 ID와 예외 ID, 도구 시도와 실제 저장은 분리해서 기록한다.

## 3. 어떤 신뢰 자료를 넣었고, 실제 검토에 무엇이 쓰이는가?

`qa/knowledge/corpus.json`에는 현재 32건이 있다: 사고·부정 사례 `INCIDENT` 7건, Agent 연구 `RESEARCH` 5건, 기술 지침 `TECHNICAL` 10건, 프로젝트 참조 정책 `PROJECT_POLICY` 6건, 방법론 참고 `REFERENCE` 4건. `source_type`은 **자료 종류**, `evidence_domains`는 **두 의미 검토의 사용 허용 영역**이다. 공식 기관의 자료여도 관련 문단과 대상 업무의 연결이 자동으로 성립하지는 않는다.

| 자료 예 | 발행 주체·원문 | 현재 저장 형태 | 현재 두 단계 검토에서의 위치 |
|---|---|---|---|
| BP Texas City 사고 | [미국 CSB 최종 조사](https://www.csb.gov/bp-america-texas-city-refinery-explosion/) | 보고서 PDF 텍스트(`PDF_TEXT`) | corpus에는 있으나 `MANUFACTURING` 태그가 없어 1단계 직접 근거 후보는 아님 |
| Chevron Richmond 사고 | [미국 CSB 조사](https://www.csb.gov/chevron-richmond-refinery-fire/) | 출처를 연결한 자체 요약 | corpus에는 있으나 1단계 태그 없음 |
| Kobe Steel 검사 자료 조작 | [회사 공개 보고](https://www.kobelco.co.jp/english/releases/1199082_15581.html) | 출처를 연결한 자체 요약 | `MANUFACTURING` 태그가 있는 유일한 사고 사례. 정부 조사 보고서와 발행 주체가 다름 |
| Agent-SafetyBench | [연구 논문](https://arxiv.org/html/2412.14470v2) | 출처를 연결한 자체 요약 | 현재 `AGENTIC` 태그가 있는 유일한 연구 |

이 밖에 CSB의 DuPont 권고·Williams Geismar 사례, 미국 DOJ의 Takata 사건 기록, Daihatsu 회사 조사도 사고/부정 사례로 등록돼 있다. 그러나 **현재 `MANUFACTURING` 검토 후보는 사고 1건(Kobe), 기술 자료 3건(Oracle·ISA·NIST)**이고, `AGENTIC` 후보는 연구 1건(Agent-SafetyBench)이다. 검색은 위험 태그까지 적용하므로 개별 시험에서 실제로 반환되는 문헌은 이보다 적을 수 있다. 등록된 사고 7건이 모두 초기 제조업 검토에 쓰인다는 뜻은 아니다.

자료별로 원문 URL·발행 주체·버전·위치·수집일·해시·적용 범위·인용 가능한 요약 여부를 기록한다. 자체 요약(`CURATED_SUMMARY`)은 원문 PDF 문장과 구별하고 `source_facts_en`(원문에서 확인한 사실)과 `qa_transfer_en`(시험으로 옮기는 해석)을 나눈다. 사고는 **업무상 위험의 유사 사례**이고 Agent 사고의 증거가 아니다. 연구는 **Agent 실패 가능성의 근거**이며 회사별 안전 규정이 아니다. 실제 기대 행동과 강제 판정은 별도로 채택된 참조 정책·코드에서 정한다.

### 실제 RAG 색인·검색 경로

`knowledge/index.py`가 읽는 입력은 **`qa/knowledge/corpus.json`의 `documents`**다. `PDF_TEXT`는 해시가 맞는 로컬 PDF에서 페이지별 텍스트를 추출한다. `CURATED_SUMMARY`는 `text_en`만 읽는다. 원문 URL이나 로컬 웹 스냅샷의 본문을 자동 수집해 색인하지 않는다. 따라서 CSB 웹페이지가 연결돼 있어도, 그 항목이 `CURATED_SUMMARY`라면 검색 대상은 자체 요약이다.

색인기는 텍스트를 최대 900토큰 parent와 240토큰 child(40토큰 겹침)로 나눈다. child를 BGE 모델로 임베딩해 PostgreSQL `knowledge.child`의 `vector(384)`에 저장하고, 문서 메타데이터·parent 텍스트·색인 버전을 함께 보존한다. 검색은 **대상 유형·자료 종류·위험 계열·검토 영역을 먼저 필터링**한 뒤 벡터 유사도와 영어 전문 검색을 결합한다. 일치한 child의 parent와 출처를 Scenario Agent에 반환한다. 이 검색 결과는 검토 입력이며 자동 합격 판정은 아니다.

이 문서(`docs/scenario-data-design.md`)와 README 수정은 RAG 입력에 포함되지 않는다. corpus 항목이나 검토 태그를 수정하면 별도의 `make knowledge-index` 작업으로 색인 버전을 갱신해야 한다. 현재 문서 변경에서는 corpus와 실행 중인 DB를 수정하거나 재색인하지 않았다.

### 남은 데이터 작업

1. CSB·DOJ 사고 자료를 1단계 근거로 넓히려면, 각 원문의 **정확한 문단/페이지 → 대상 업무 제약 → 시험 상태 필드** 연결을 사람이 검토한 뒤 적절한 `evidence_domains`와 위험 태그를 부여하고 색인을 갱신한다. 출처의 공신력만 보고 일괄 태그를 붙이지 않는다.
2. Agent 연구도 `Agent-SafetyBench` 1건만 초기 영역 태그를 갖는다. 위험별로 도구 재시도·권한·외부 지시·검증 누락의 직접 근거가 부족하면 `NEEDS_INFORMATION`으로 남기는 것이 맞다.
3. 카테고리별 근거 문단·실행 가능한 예외·관측 규칙의 대응표를 만들고, 새로운 기업 Agent를 등록할 때 해당 회사의 실제 업무 정책과 실행 어댑터를 따로 검증해야 한다.

관련 구현: `agents/src/agents/scenario/analysis.py`, `morphology.py`, `exceptions.py`, `design.py`, `review.py`; `harness/src/harness/registrations.py`, `planning.py`, `store.py`.
