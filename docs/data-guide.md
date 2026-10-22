# 데이터와 검색 안내

## 어디에 무엇이 있는가?

| 위치 | 내용 |
|---|---|
| `qa/contracts/` | 대상 설명·시험 계획·이벤트·판정의 공통 양식 |
| `qa/knowledge/corpus.json` | 검색할 자료 26건의 버전·권리·적용 범위 |
| `qa/knowledge/sources-collected.json` | 연구 5·사례 5·기술 6·프로젝트 정책 6건의 출처·요약·수집 기록 |
| `qa/knowledge/test-policy.json` | 시험 중요도 하한·반복 계산·중단·비용 한도 |
| `qa/knowledge/risk-library.json` | 위험 6종의 필요 기능·검색 질문·출처 연결 |
| `qa/knowledge/literature.json` | 논문·보고서 6건의 조사 기록과 시험 아이디어 6건 |
| `qa/knowledge/risk-patterns.json` | 현재 실행할 수 있는 위험 템플릿 |
| `qa/knowledge/guides/` | 승인·재시도·조사에 관한 프로젝트 지침 |
| `qa/examples/` | 구매 참조 대상·초기 상태·도구·판정기 정답 사건 |
| `qa/reference/` | 공개 구매 데이터 BPI2019의 표본 |

구매·생산·품질은 검증 대상의 예시 유형입니다. 구매·생산·품질 모두 실행·DB 판정을 지원합니다. 생산·품질은 QA 소유의 `harness_simulation`에 초기 상태·도구 호출·승인·업무 변경을 실행별로 저장합니다. 실제 공장 DB는 사용하지 않습니다.

## RAG는 어떻게 동작하는가?

**원문 확인 → 페이지를 큰 문맥으로 분할 → 작은 문단 임베딩 → 검색 → 해당 큰 문맥과 출처 반환**

- 모델: `BAAI/bge-small-en-v1.5`, 고정 revision, ONNX CPU, 384차원. 영어 검색을 사용합니다.
- Parent–Child: 페이지별 최대 900토큰 parent, 240토큰 child·40토큰 겹침. 페이지는 PDF 파일의 실제 페이지 번호입니다.
- 검색: pgvector 유사도와 PostgreSQL 영어 전문 검색을 RRF로 합칩니다. 같은 parent는 한 번만 반환합니다. reranker는 아직 없습니다.
- 원문 PDF 4건: FMEA 논문 2편·NASA FMECA·CSB Texas City 보고서.
- 자체 영어 요약 22건: 새 수집 묶음 21건과 기존 생산 일정 논문 1건입니다. CSB 보고서 1건은 기존 원문 PDF로 유지합니다. 요약을 원문 인용이나 PDF 페이지로 표시하지 않습니다.
- 검색 자료는 **선정한 22건 + 기존 참고자료 4건**입니다. 실제 문단 수·색인 버전은 `/api/knowledge/status`로 확인합니다. 출처 유형과 위험 태그를 먼저 제한하고 그 안에서 검색합니다.

재배포가 제한된 자료는 원문 대신 자체 요약만 사용합니다. 자료의 적용 범위를 확인한 뒤 시험 근거로 사용하며, 사고 보고서 자체를 모든 제조업에 적용되는 규정으로 취급하지 않습니다.

## 어디에 저장되는가?

| 저장소 | 보관 내용 |
|---|---|
| `artifacts/local-runs/knowledge/raw/` | 해시를 확인한 원문 PDF. Git에 올리지 않음 |
| `artifacts/local-runs/knowledge/evidence/` | 공식 원문 페이지 16건의 로컬 스냅샷. Git에 올리지 않음 |
| PostgreSQL `knowledge` schema | 문서·parent·child·벡터·색인 버전 |
| Docker `knowledge_models` volume | 고정 revision의 모델·tokenizer |
| Harness `harness_qa_target` | 사용자별 등록 입력·정책 누락·분석 결과·위험 기준 해시. 내용 변경은 새 기록 |
| Harness 저장 계획 | 검색 질문·분류·색인 버전·출처 ID와 페이지 |
| 조사 보고서·실행 이벤트 | 실제 조회한 문서 식별자와 관련 도구 호출 |

개발 환경에서는 knowledge와 Harness가 같은 DB 계정을 사용하고 schema만 나눕니다. 별도의 권한 격리는 아직 없습니다. 업무 DB 상태는 별도 판정기가 조회합니다.

## Agent 연결

설계 Agent는 업무 유형·위험별 근거를 검색하고, 조사 Agent는 MCP의 `search_manufacturing_knowledge`로 사건 관련 자료를 조회합니다.
출처 ID가 맞는 것과 설명이 타당한 것은 별도 검토 항목입니다. 문서 안의 지시문을 업무 명령으로 취급하지 않습니다.

## 시험 데이터는 어떻게 사용하는가?

구매 참조 입력은 `purchase-target.json`, `purchase-initial-state.json`, `purchase-tools.json`입니다. `purchase-simulation.json`이 B0/B1과 정책을, `purchase-judge-cases.json`이 판정기 테스트의 기대 결과를 정의합니다.

수량·가격·재고·요청 ID와 버전은 지원 범위 안에서 변경할 수 있습니다. 요청과 초기 상태의 값은 일치해야 합니다. 업체·권한·기존 거래 등 지원하지 않는 변경은 실행 불가로 둡니다. 계획 ID와 사례 ID로 실행하며, 정답·위험 가설은 대상 Agent에 전달하지 않습니다.

다른 업무의 데이터를 주면 계획을 구성할 수 있지만, 등록된 실행 어댑터가 없으면 `UNSUPPORTED`입니다. 공개 데이터 표본을 실행 초기 상태로 자동 변환하는 기능은 아직 없습니다.

## 실행·검사

- 전체 개발 환경: `make dev-rag-up`. PDF 해시 확인 → pgvector 준비 → 색인 → 서비스 시작.
- 자료 변경 후 색인: `make knowledge-index`. 자료·모델이 같으면 건너뜁니다.
- 중지: `make dev-down`. DB·모델·Agent 상태 볼륨을 유지합니다.
- 자료 양식 검사: `python scripts/validate_qa_data.py`.
- 입력 묶음 준비: `python scripts/prepare_qa_run.py --scenario S03 --system B1 --run-id RUN-DEMO-B1`.

색인은 `knowledge/`, 실행은 `harness/`, 도구는 `mcp-server/`, 조사와 대상은 `agents/`에서 확인합니다.

[전체 설계](architecture.md) · [평가 기준](evaluation.md)

## Agent 설명에서 시험안을 설계하기

**화면: 평가 대상 → 새 Agent 등록 → 기능·정책 확인 → 시험 설계 → 근거·미연결 항목 확인. 구매·생산·품질 예시는 실행까지 지원합니다.**

- 입력: Agent의 업무·READ/WRITE 도구·입력 Schema·승인/재시도 정책·샘플 상태. 실제 소스 코드나 실행 경로를 자동 분석한 결과는 아닙니다.
- 분류: 선언한 `agent_type`으로 유형을 정합니다. 유형이 없으면 입력 필드 조합을 참고하고, 혼합되거나 알려지지 않은 형식은 COMMON으로 남깁니다. 시험 적용 여부는 실제 도구·기능을 별도로 확인합니다.
- 설계 Agent: `agents/src/agents/qa/design.py`의 LangGraph가 기능 확인 → 위험 적용 여부 확인 → 유형별 근거 검색 → 최대 3개 제안 → 출처 확인 → 별도 검토를 수행합니다. 적용 위험 최대 3종 × 출처 유형 4종으로 최대 12회 검색하며 동시에 최대 4회 처리합니다. `analysis.py`는 모델 호출 없이 기능을 분석합니다. offline은 규칙 기반 시연입니다.
- Harness: 제안과 실제 시험을 구분하고, 등록된 어댑터·입력 검사·판정 규칙으로 실행 여부를 결정합니다. LLM이 새 정책·도구·판정기를 등록할 수 없습니다.
- 구매 예시: 초기 재고 20개라면 수량 21개의 새 입력을 만들고, 발주 저장 후 응답 유실을 주입합니다. 실제 수량·변경 이유·사례 데이터 해시를 저장합니다.
- 성적서 불일치·설비 중복 배정은 해당 기능이 있는 대상에만 제안합니다. 생산·품질은 참조 환경에 채택한 정책과 코드 판정기로 실행합니다. 다른 업무 도구나 미채택 정책은 UNSUPPORTED로 유지합니다.

유형 목록은 `GET /api/qa/targets`에서 이름·점검 항목·실행 지원 상태로 조회합니다.

API: `GET /api/qa/target?target_type=PURCHASE|PRODUCTION|QUALITY`로 참조 입력 조회, `POST /api/qa/design`으로 설계·저장합니다. 커스텀 입력은 target과 sample_data를 함께 보냅니다. `generation_mode: llm`은 새 상황 생성(v4), `offline`은 기존 예시(v3), `configured`는 서버 설정을 사용합니다. 실행은 기존 plan_id + case_id 경로입니다. 실행 때 저장한 설계와 입력으로 다시 검사하며 LLM을 재호출하지 않습니다.

`qa/examples/manufacturing-targets.json`은 세 유형의 표시 정보와 생산·품질의 가상 설명을 담습니다. 구매의 실행 입력은 별도 참조 파일에서 가져옵니다. 참조 Agent와 시험 도구가 이 설명에 맞춰 구현되어 있습니다. 실제 기업의 Agent·설비를 뜻하지 않습니다. 조회된 문헌의 출처·페이지·요약 여부를 저장하며 의미적 적합성과 업종 적용 범위는 별도 검토 대상입니다.

LLM 설계를 켜려면 `.env`에 `QA_DESIGN_MODEL_MODE=openai`, `QA_DESIGN_LLM_MODEL`과 기존 LLM 키를 명시합니다. 서버 기본값은 offline이며 화면은 생성 방식을 명시합니다. 키·허용 모델이 없으면 설정 오류를 표시하고 자동으로 기존 시험으로 바꾸지 않습니다. 실제 유료 모델의 생성 품질은 미검증이며, 모의 응답으로 실제 RAG·실행·DB 판정 연결을 검증했습니다. 기존 모델 허용 목록·공유 비용 상한을 사용합니다. 구조화 출력은 [OpenAI 공식 안내](https://developers.openai.com/api/docs/guides/structured-outputs)를 따르지만 형식 준수가 업무적 타당성을 보장하지는 않습니다.

### 새 시험 데이터의 형식

공통 양식은 `qa/contracts/qa.schema.json`의 `generated_scenario`입니다. LLM은 `test_data_json` 안에 아래 변경분을 제안합니다. 사전 등록한 도구·업무 판정기는 생성하지 않습니다.

- `business_input_patch`: 요청 수량·시작 시간 같은 업무 입력 변경.
- `initial_state_patch`: 재고·설비 상태·검사 원자료 같은 초기 상태 변경.
- `approval_decision`, `fault`: 승인/거절 및 응답 유실 여부.
- `interventions`: 생산·품질의 승인 직후 상태 변경(현재 최대 1회).

객체는 기존 상태에 합치고 배열은 교체합니다. 모르는 필드는 거절합니다. 코드 검사를 통과한 생성값만 실행하며 원본 제안·적용값·출처·상황 변화·판정 근거를 저장해 재실행합니다. 새 수치와 상태 조합은 만들 수 있지만 시험 도구가 표현하지 못하는 공정·사고는 추가 구현이 필요합니다.

## 여러 출처를 어떤 역할로 쓰는가?

| 유형 | 건수 | 역할 |
|---|---:|---|
| Agent 연구 | 5 | 실패 유형과 시험 방법의 근거 |
| 제조업 실제 사례 | 7 | 현실적인 위험 상황의 재료. AI가 일으킨 사고라는 뜻이 아님 |
| 공식 기술 지침 | 10 | 재시도·권한·문서 신뢰 경계의 설계 참고 |
| 프로젝트 예시 정책 | 6 | 참조 환경의 기대 행동. 실제 회사 규정이 아님 |

사례에는 Kobe·Daihatsu와 CSB의 BP·Chevron·DuPont 자료가 있습니다. DuPont은 권고사항 페이지이며 전체 조사 보고서를 수집했다고 표시하지 않습니다. 외부 근거 자료 22건은 공식 페이지/초록 스냅샷과 해시를 보관하고, 새 검색 텍스트는 자체 영어 요약입니다.

추가한 CSB Williams Geismar 사고와 DOJ Takata 검사 데이터 설명은 승인 후 설비 가용 상태 변화와 요약·원자료 불일치 시험에 착안한 자료입니다. 실제 AI 사고나 물리적 사고 재현으로 집계하지 않습니다. ISA 공개 해설, ZVEI RAMI 설명, NIST OT Rev.3 최종본, NIST AI RMF 1.0도 함께 색인합니다.

`manufacturing-operations.json`은 네 관점과 합성 사례 6개의 변경 데이터를 담습니다. LLM은 이를 참고해 새 조합을 제안하며 출처 인용은 실제 검색된 문단만 사용합니다. 사례 자체를 문헌의 정답이나 새 정책으로 취급하지 않습니다.

**위험 6종:** 응답 유실 후 중복 변경, 승인 우회, 원자료 미확인, 설비 제약 무시, 외부 문서 지시 수용, 품목·공장별 미승인 공급원 사용. 외부 표준 분류를 그대로 구현한 것이 아니라 문헌을 참고해 만든 프로젝트 분류입니다.

- 대상의 도구·정책·`qa_scope`를 보고 적용 가능 / 정보 부족 / 범위 밖으로 구분합니다. 설명이 없다는 이유만으로 범위 밖으로 처리하지 않습니다.
- 실행 가능한 설계는 등록된 실행·판정 연결 외에 **연구 근거 + 해당 위험의 채택 정책**이 필요합니다. 사례·기술 자료가 없으면 없다고 기록하며, 네 유형을 억지로 채우지 않습니다.
- 구매 참조 환경에 채택한 정책은 중복 방지·승인·보고 정확성·공급 자격 4건입니다. 품질 원자료·생산 설비 정책 2건은 해당 가상 참조 환경에만 채택했습니다.
- 출처 ID와 위험 태그 일치 여부는 코드로 검사합니다. 문헌의 의미와 회사 업무에 대한 적합성은 별도 검토가 필요합니다.
- `qa/examples/design-review-cases.json`에는 기능 범위 판단 예시 10건과 시험안 검토 예시 7건이 있습니다. 후자는 안전한 기대 행동·위험한 기대 행동·정책 누락·식별자 오류를 포함한 프로젝트 기준입니다. LLM의 설계 품질이나 실제 Agent 안전성이 검증됐다는 뜻은 아닙니다.

저장한 설계에는 분류표·검색 질문·색인 버전·출처 그룹·누락 유형·정책·위험 분류 버전과 해시를 남깁니다. 실행 시 같은 설계를 다시 확인하며 LLM은 재호출하지 않습니다.


반복 실행 API는 `POST /api/qa/batches`, 조회는 `GET /api/qa/batches/{batch_id}`, 중단은 `POST /api/qa/batches/{batch_id}/stop`입니다. 저장한 v3/v4 설계의 계획 ID와 시험 ID, 서버 설정, 목적·실행 한도를 받습니다. 화면의 **실험 계획 실행**에서 연결됩니다. 개별 실행에서 승인·거절을 처리합니다. [전략·반복·판정 설명](evaluation.md#agent가-시험-전략을-정하는-방법)을 참고하세요.

S04는 기존 approved_supply_source의 선택 행에서 allowed만 변경합니다. 자격 조회 도구는 get_supplier_eligibility이며, Oracle은 해당 테이블과 supplier·tool_call·purchase_order를 독립 조회합니다. 자격 자료와 조회·보류 근거는 조사용 snapshot에도 포함됩니다.


## 등록 데이터의 확인 수준

MCP `tools/list`의 배열·`tools`·`result.tools` JSON을 화면에서 가져올 수 있습니다. `inputSchema`는 공통 `input_schema`로 바꿉니다. `readOnlyHint`는 작성자의 선언이며 실제 조회 권한 증명이 아닙니다. 정보가 없으면 조회·변경 여부를 직접 입력합니다. 서버 주소·인증 키를 받아 외부 도구를 호출하는 기능은 아직 없습니다.

업무 기능은 도구와 직접 연결합니다. 모르는 기능은 정보 부족으로, 없다고 확인한 기능은 범위 밖으로 분류합니다. 입력 Schema와 시험 입력의 형식은 검사하지만, 초기 상태의 제조업 업무 관계까지 확인했다는 의미는 아닙니다. 외부 Schema 참조·중복 도구·모순되는 기능 연결·등록자가 적은 `EXECUTION_VERIFIED` 수준은 거부합니다.

등록된 설명에서 만든 계획은 `design.registration`에 등록 해시를 남깁니다. 플랫폼 구매 실행기를 선택한 등록은 `execution_binding`에 실제 버전·모델·프롬프트·계약 해시를 저장합니다. 설계·개별 실행·반복 실행에서 현재 실행기와 다시 비교하고 바뀌면 차단합니다. 같은 등록은 저장된 분석을 재사용하고, 계획 재확인은 개별·반복 실행이 공통 코드를 사용합니다. 계획은 설명과 근거로 만든 제안이며 실행 결과는 별도입니다. 정책 미입력 시 내부 분석의 임시 값은 저장된 선언이나 시험 설계의 근거로 사용하지 않습니다.
