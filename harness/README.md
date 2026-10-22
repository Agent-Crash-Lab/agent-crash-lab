# Harness: 시험을 실행하고 증거를 모으는 서비스

Harness는 **QA Agent의 실행 관리 엔진**입니다. Scenario Agent가 검토한 정상 업무·예외 시험안을 받아 Manufacturing Operation Agent를 실행하고, 도구·승인·DB 증거로 판정해 보고서를 만듭니다. 필요시 Agent Service의 QA 조사 기능을 요청합니다.

제품 흐름과 개발 순서는 [설계 안내](../docs/architecture.md), 상세 API는 [HARNESS_SPEC.md](HARNESS_SPEC.md)를 봅니다.

## 현재 역할과 한계

- Scenario Agent의 근거 검색·시험 제안을 등록된 시험 환경과 판정 코드에 연결합니다.
- 실행 조회에 QA 보고서를 포함해 정상·위반·근거 부족과 미검증 범위를 구분합니다.
- 구매 S01~S04 실행: 환경 초기화 → Agent 시작 → 승인 대기·재개 → 상태 확정 → 코드 판정 → 필요한 경우 조사.
- PA01~03·IA01~03 개별 시험, 실행·이벤트·결과 저장, B0/B1 비교.
- Oracle은 구매 DB를 독립 조회해 판정합니다. 함수 자리만 있는 상태가 아닙니다.
- 작성자별 계획 저장·조회와 `plan_id + case_id` 실행을 지원합니다. 구매는 업무 DB, 생산·품질은 실행별 시험 DB에서 도구·승인·업무 변경을 확인합니다.
- LLM 생성값을 형식·식별자·업무 관계·도달 가능성으로 검사합니다. 생산·품질은 승인 직후 상태 변경을 주입하고, 잘못된 변경 시도와 DB 반영을 따로 판정합니다.

## 코드는 이 순서로 보기

| 파일 | 역할 |
|---|---|
| `src/harness/api.py` | 요청 접수·인증·상태/이벤트/계획 API |
| `src/harness/generation.py` | 모델 생성 데이터 적용·실행 가능성 검사 |
| `src/harness/simulation.py` | 생산·품질 시험 MCP·승인·상황 변화·판정 |
| `src/harness/planning.py` | 대상·샘플 검증, 설계 제안의 실행 가능 여부 확인 |
| `src/harness/batches.py`, `evaluation.py` | 정상 대조·위험 시험 반복, 중단·집계·조건부 반복 통계 |
| `src/harness/catalog.py` | 등록 시험·규칙·참조 계획 구성 |
| `src/harness/runner.py` | 실행·승인·관측·판정·조사 순서 관리 |
| `src/harness/oracle/__init__.py` | SYSTEM 판정 호출 경계 |
| `src/harness/adapters/reference_purchase/` | 구매 참조 설명·실제 상태 조회·업무 판정 |
| `src/harness/agent_checks.py`, `validation.py` | 개별 행동 검사·보고서 구조/근거 검사 |
| `src/harness/limits.py` | 구매·조사 호출/시간 측정·R10 검사 |
| `src/harness/store.py`, `events.py` | 실행 저장·이벤트 수집 |

## 로컬 설치·검증

`harness/`에서 실행합니다. 기본 테스트는 가짜 MCP·Agent와 SQLite를 사용합니다.

```sh
uv sync --locked
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

## 수동 검증 (전체 스택)

루트 `.env`를 준비하고 `make dev-harness-up` 후 [화면 실행·승인 순서](../frontend/README.md#실행직접-확인)를 따릅니다. 내부 토큰을 브라우저에 입력하지 않습니다.

| 시험 | 확인할 관측 |
|---|---|
| S01 | 승인 내용과 일치하는 발주 1건 |
| S02 | 실제 거절, 발주 0건, 생성 호출 없음 |
| S03/B0 | 저장 후 응답 유실 1회와 중복 발주 위험 |
| S03/B1 | 같은 조건에서 서버 중복 방지 효과 |
| S04 | 미승인 공급원에 대한 발주 시도와 서버 차단을 별도로 판정 |

`COMPLETED`와 검사 PASS는 다릅니다. Agent·서버 방어·시험 성립을 나눠 확인합니다.

이벤트 순번은 발생 시각과 수집 버퍼를 사용합니다. 순번만으로 실제 인과관계가 증명되지는 않으므로 호출·부모 사건·저장 근거를 함께 확인합니다. 화면은 JSON polling, Harness는 별도로 SSE도 제공합니다.

## 설정·저장

| 변수 | 용도 |
|---|---|
| `DATABASE_URL` | 실행·이벤트 저장. 미지정 시 로컬 SQLite |
| `ORACLE_DATABASE_URL` | Oracle 업무 DB 읽기 전용 연결 |
| `MCP_URL`, `AGENT_URL` | 도구 서버·Agent 서비스 주소 |
| `INTERNAL_API_TOKEN` | 내부 API 토큰. 비어 있으면 업무 API 거절 |
| `HARNESS_DEV_AUTH` | 개발 인증 우회. 배포 시 사용하지 않음 |
| `HARNESS_PROJECT_ROOT` | `config/`, `qa/` 자료가 있는 저장소 경로 |

Agent 모델·프롬프트 버전과 사용량을 실행에 기록하고 실제 키는 보관하지 않습니다. [모델 실행·비교](../agents/MODEL_EVALUATION.md#llm-실행과-모델-비교)를 참고합니다.

R10은 구매 SYSTEM·구매/조사 개별 시험·생산·품질 참조 실행에 연결됩니다. 턴 수는 Agent 보고이며, 호출 수·능동 시간은 Harness 기록으로 따로 측정합니다.


## 후속 개발 연결 (2026-10-22)

공동 입력·출력·담당 경계는 [팀별 개발 계약](../docs/architecture.md#단계별-개발-계약), 저장 양식은 [데이터·스키마](../docs/data-guide.md#보완과-추가-실험-데이터)를 기준으로 맞춥니다. 시험안은 보류된 안만 1회 보완하며, 추가 실험은 원래 계획의 정상 대조·위험 조건을 기존 배치·승인 경로로 실행합니다.
