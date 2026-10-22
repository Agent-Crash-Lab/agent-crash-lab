# Agent 서비스

**QA 시험을 설계하고, 대상 Agent를 실행하며, 실패 근거를 조사합니다.**

## 역할과 연결

| 코드 | 역할 | 연결 |
|---|---|---|
| `src/agents/qa/analysis.py`, `design.py`, `proposals.py` | 기능 분석 → 근거 검색 → 시험 데이터 생성 | Harness 설계 API·MCP 문서 검색 |
| `src/agents/qa/review.py` | 코드 사전 검사 → 제안 상태 계산 → 항목별 의미 검토 | 생성된 시험안·검색 문헌 |
| `src/agents/qa/investigation.py` | 실행 기록·DB 관측·문서를 읽고 조사 보고서 작성 | Harness 조사 요청·MCP 증거 도구 |
| `src/agents/targets/` | 검증 대상인 구매 Agent 참조 구현 | 시험용 MCP 재고·승인·발주 도구 |
| `src/agents/runtime.py`, `execution.py`, `store.py` | 실행·승인 대기·재개·저장 | 내부 HTTP API·SQLite checkpoint |
| `src/agents/tools/` | 실제 MCP 연결과 테스트용 가상 도구 | MCP 서버 또는 mock |
| `src/agents/llm.py` | 모델 호출·구조화 출력·비용 제한 | 선택형 OpenAI 연결 |

구매·생산 일정·품질·출하는 **검증 대상 유형**입니다. 설계·검토·조사는 공통 QA 역할입니다.
구매·생산·품질 참조 Agent 모두 실행됩니다. 생산·품질은 `targets/manufacturing.py`의 규칙 기반 실행기로, Harness가 제공한 실행별 HTTP MCP 도구를 사용합니다. 실제 공장 업무는 수행하지 않습니다.
실행 지원 여부와 최종 판정은 Harness의 등록 어댑터·코드가 결정합니다.
`design.py`는 단계 흐름, `proposals.py`는 생성 형식·프롬프트·offline 예시, `review.py`는 검토 기준과 제안 상태 계산을 담당합니다. 검색 연결은 한 설계에서 재사용하며 최대 4개 요청을 동시에 처리합니다.

모델의 `offline/openai`와 도구의 `mock/mcp`는 별도 설정입니다. 기본 offline은 규칙 기반이며 유료 모델을 호출하지 않습니다.

## 실행과 검증

전체 환경은 루트에서 `make dev-rag-up`으로 시작합니다. `make dev-down`은 저장 볼륨을 유지합니다.
Agent만 개발할 때는 `agents/`에서 실행합니다.

```sh
uv sync --locked
uv run --locked pytest
uv run --locked ruff check .
uv run --locked python -m agents.demo --scenario timeout-once
uv run --locked uvicorn agents.server:app --host 127.0.0.1 --port 8091
```

CLI demo는 가상 도구·임시 SQLite를 사용합니다. HTTP 서버는 `INTERNAL_API_TOKEN` 설정이 필요합니다.
설정은 `config/qa-runtime.json`, 공유 데이터는 `qa/`, 상태 저장 위치는 `AGENT_STATE_DIR`을 확인합니다.

## API와 복구

- 설계: `POST /internal/qa/design`. 대상 설명·샘플 상태와 `generation_mode: llm|offline|configured`를 받습니다. LLM은 업무 입력·초기 상태·승인 후 상태 변화를 생성하고, offline은 기존 시험 예시를 사용합니다. 설계 요청 자체는 대상 Agent를 실행하지 않습니다.
- 실행·조회·승인 재개: 내부 API는 `src/agents/server.py`와 `/docs`를 확인합니다. 사람의 승인 요청은 MCP 공개 API를 사용합니다.
- 동시 활성 실행은 승인 대기를 포함해 1개입니다. 다른 실행은 409로 거절합니다.
- 재시작 후 승인 대기는 원래 만료시각으로 복원합니다. 진행 중 작업은 중단 기록을 남기며 거래를 자동 재실행하지 않습니다.
- 토큰은 메모리에만 보관합니다. checkpoint와 이벤트에 키를 기록하지 않습니다.
- Agent 이벤트는 자신이 본 호출·응답만 나타냅니다. 실제 DB 반영과 사고 주입 여부는 Harness가 별도로 확인합니다.

## 통합 테스트

| 파일 | 확인 범위 | 필요한 환경변수 |
|---|---|---|
| `tests/integration/test_mcp_purchase.py` | 실제 MCP·DB·구매 행동 | `MCP_INTEGRATION_URL`, 선택 `AGENT_INTEGRATION_URL` |
| `tests/integration/test_harness_flow.py` | 승인 콜백·관측·판정·조사·비교 | `MCP_INTEGRATION_URL`, `HARNESS_INTEGRATION_URL` |

통합 테스트는 실행 이력을 추가합니다. 루트 `.env`의 내부 토큰·개발 계정 설정을 사용하고 순차 실행합니다.
환경변수가 없으면 일반 테스트에서 통합 테스트를 건너뜁니다. 실행 종료(`COMPLETED`)와 검사 통과는 별개입니다.

[전체 흐름](../docs/architecture.md) · [화면 실행·승인](../frontend/README.md#실행직접-확인) · [LLM 설정·모델 비교](MODEL_EVALUATION.md#llm-실행과-모델-비교)

QA 생성 모델은 `QA_DESIGN_LLM_MODEL`, 검토 모델은 `QA_REVIEW_LLM_MODEL`로 따로 선택합니다. 검토 설정이 비면 생성 모델을 사용합니다. 검토 출력 한도는 1,024토큰이며 기존 공유 비용 제한을 적용합니다. 고정 사례의 검토와 실제 Agent 실행 결과는 별도입니다.
