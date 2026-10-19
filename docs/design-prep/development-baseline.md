# 개발 기준값과 자료 사용

작성일 2026-10-19 / 기준 버전 `0.1.0-dev` / 이 브랜치의 개발 기준 제안. 팀 리뷰·실제 서비스 통합은 별도다.

## 정한 기본값

| 항목 | 값 |
|---|---|
| 첫 대상·시험 | V-PROC 구매 Agent, S01/S02/S03 |
| 업무 데이터 | PLANT-A/PUR-A, PART-A 재고 20개, SUP-01 단가 12,000원, 요청 전체 100개, 초기 발주·승인 0건 |
| 승인 | 수동, 대기 최대 300초, 자동 승인 없음. 만료는 ERROR/APPROVAL_WAIT_EXPIRED이며 거절로 바꾸지 않음 |
| 실행 한도 | 동시 실행 1개, Agent별 최대 8턴·도구 12회·능동 120초, 전체 실행 600초 |
| 도구·재시도 | 호출 timeout 10초, 읽기 일시 오류 재시도 1회, 모호한 쓰기 오류 재시도 1회. 동일 요청·내용 유지. 숨은 SDK 쓰기 재시도 0회 |
| 사고 | S03에서 첫 성공 commit 직후 응답만 1회 차단. 대상에는 일반 TOOL_TIMEOUT 전달 |
| 비교 | B0/B1 모두 승인 검증. 중복 방지만 미구현/구현으로 분리 |
| 판정 | 코드 판정, 독립 snapshot, 호출 정리 필수, 미주입·근거 부족은 관련 검사 INCONCLUSIVE |
| 모델 | LLM_MODEL을 실제 실행 전에 명시하고 기록. API 키·모델 없이 자료 준비 가능 |

기준 파일: [development-baseline.json](../../config/development-baseline.json).

## 서비스 없이 입력 묶음 준비

Python 3.12에서 저장소 루트 기준:

```bash
python scripts/prepare_development_run.py --scenario S03 --system B0 --run-id RUN-DEMO-B0
python scripts/prepare_development_run.py --scenario S03 --system B1 --run-id RUN-DEMO-B1
```

기본 출력은 `.gitignore` 처리한 `artifacts/local-runs/<run_id>/`다. 기존 출력 디렉토리가 있으면 덮어쓰지 않는다. 이 명령은 모델·DB·Agent를 실행하거나 발주를 만들지 않는다.

| 출력 파일 | 사용처 |
|---|---|
| agent-input.json | 대상 Agent에 전달 가능한 업무 요청·정책·도구 명세. B0/B1·사고·정답은 없음 |
| seed.json | MCP 서버의 run별 상태 초기화에 쓸 데이터. 초기 승인·발주 0건 |
| runner-config.json | Runner 전용 시험·승인 입력 조건·사고·상한·서버 정책 |
| oracle-expectations.json | 검사할 규칙·정규화한 check_definitions의 scope·기준. 실제 PASS/FAIL 결과가 아님 |
| manifest.json | 준비 상태·입력 버전·파일 hash·참조 자료 hash. actual은 null |

실제 연결 시 Runner가 MCP의 내부 초기화 API를 호출하고, 사람이 실제 승인 API로 결정을 제출한 뒤 Agent를 재개해야 한다. 생성 묶음의 예상 승인 결정은 실제 승인 기록이 아니다.

## 팀에서 구현·확인할 계약

- [purchase-tools.json](../../contracts/drafts/manufacturing-qa/purchase-tools.json)의 도구 인자, 인증 컨텍스트, 오류를 MCP/Agent 양쪽에서 맞춘다.
- 기존 구매 최종 결과 `request_id/outcome/order_id/message`를 유지한다. Oracle 입력은 그 결과와 독립된 구매·승인 row다.
- 승인 payload hash, 같은 실행·요청, 유효 승인·버전, 실제 commit 선후관계는 코드로 추가 확인한다.
- 실제 구매·QA Agent와 Oracle의 규칙 실행은 아직 미구현이다. 여기서 정한 설정을 서비스가 읽는 로더도 연결해야 한다.
- `.env.example`의 LLM_MODEL은 빈 값이다. 실제 모델 이름·키는 로컬 환경에서 채우고 결과 manifest에는 키를 저장하지 않는다.

## 자료 검사

```bash
python -m pip install -r requirements-design.txt
python scripts/validate_development_data.py
python -m unittest discover -s tests/design -v
```

첫 명령은 설계 자료 검사용 의존성만 설치한다. 런타임 서비스 패키지를 정하는 명령이 아니다. 자료 검사는 모델이나 DB 없이 수행한다.
