# 재현 절차

## 버전과 환경

- 제품 소스: `00bf03d1c2eb251e5e38ac1e236c6ba6505dc09e`
- Python 3.12 계열, 저장소 pyproject 의존성. Node.js 24.19.0. Java/Gradle은 저장소 설정을 따릅니다.
- MCP 회귀: Docker PostgreSQL Testcontainers. 구매 통합: 별도 PostgreSQL/pgvector DB.
- 실제 통합 포트: MCP 18289, Agent 18290, Harness 18291, Knowledge 18292, Frontend 18293, PostgreSQL 15446.
- Agent 모델 offline, 시나리오 생성 offline, 조사 보고서 fixture. 검색은 실제 BGE/pgvector.
- 테스트용 requester-01/approver-01 계정. 비밀번호·토큰은 공개하지 않습니다.
- 검색 corpus 문서 32개, child 1,264개. index version은 e2e/index.log 및 plan.json의 버전을 참고합니다. 문헌 본문과 모델 가중치는 포함하지 않으므로 동일 출처 버전의 자료·BGE 모델을 먼저 준비해야 합니다.

새로운 검증 폴더와 DB를 사용하십시오. 기존 DB 초기화나 볼륨 삭제는 이 스크립트에서 수행하지 않습니다. e2e 스크립트는 HTTP API로 신규 프로필·계획·실행·승인 기록을 만듭니다. SQL은 읽기 전용입니다.

## 기존 회귀

아래 명령은 각 모듈 의존성 설치 후 저장소 루트에서 실행합니다. 실제 결과는 regression 로그와 testcase JSON에 있습니다.

```sh
(cd agents && uv run pytest -q)
(cd harness && uv run pytest -q)
(cd mcp-server && ./gradlew test --no-daemon)
(cd frontend && npm test)
(cd frontend && npm run check)
```

Agent opt-in 15건은 기본 실행에서 제외됩니다. 이유는 regression/agents-cases.json의 skip_reason에 있습니다. 이 수를 통과 수에 더하지 않습니다.

## 독립 시험

현재 근거 브랜치의 scripts 폴더를 제품 기준 커밋 checkout 바깥에서 참조해도 됩니다. `ACL_ROOT`는 제품 기준 checkout을 가리킵니다. Harness와 Agent 패키지 및 해당 tests 의존성을 설치한 Python 환경을 사용합니다.

```sh
export ACL_ROOT=/path/to/product-checkout
export ACL_BASELINE_OUT=/path/to/new-replay
mkdir -p "$ACL_BASELINE_OUT"
export ACL_DESIGN_INPUT="$ACL_BASELINE_OUT/current-offline-design.json"
python /path/to/evidence/scripts/generate_baseline.py
ACL_EVIDENCE_OUT="$ACL_BASELINE_OUT/scenario-guards" python /path/to/evidence/scripts/scenario_guards.py
ACL_EVIDENCE_OUT="$ACL_BASELINE_OUT/investigation-guards" python /path/to/evidence/scripts/investigation_guards.py
ACL_EVIDENCE_OUT="$ACL_BASELINE_OUT/behavior-probes" python /path/to/evidence/scripts/behavior_probes.py
```

합성 입력과 기대값을 먼저 생성하고 각 결과 JSON을 저장합니다. SC의 검색은 저장소 test fixture를 사용합니다. 제품 함수로 기대값을 계산하지 않습니다.

## 실제 구매 통합

저장소의 infra/README/Makefile 설정에 따라 **별도 DB와 위 포트**로 5개 서비스를 시작하고 Knowledge 인덱스를 준비합니다. 서비스의 포트·URL·인증키는 서로 같게 설정해야 합니다. 환경 설정 파일이나 개인 비밀키는 이 공개 패키지에 포함하지 않습니다.

```sh
export ACL_ROOT=/path/to/product-checkout
export ACL_API_URL=http://127.0.0.1:18289/api
export ACL_DB_URL='postgresql://<test-user>:<test-password>@127.0.0.1:15446/<test-db>'
export ACL_TEST_PASSWORD='<test-login-password>'
export ACL_EVIDENCE_OUT=/path/to/new-replay/e2e
python /path/to/evidence/scripts/submission_e2e.py
```

E2E 출력 폴더가 이미 있으면 중단해 기존 기록 덮어쓰기를 막습니다. 각 run의 실제 주문·승인·호출과 API 결과를 함께 저장합니다. 새 실행에서 ID·시각·소요시간은 달라질 수 있습니다. 기대값은 저장 건수·업무 결론과 같은 업무 조건입니다.

## 브라우저 대조

Playwright Chromium을 설치한 Node 환경에서 `scripts/browser_check.mjs`를 실행합니다. `ACL_UI_URL`, `ACL_UI_OUT`, `ACL_TEST_PASSWORD`를 설정합니다. 이 스크립트는 빈 DB에서 위 E2E를 처음 실행해 RUN-003/004가 생성됐을 때의 화면을 확인합니다. 기존 이력이 있는 DB라면 새 결과의 run ID로 시험 입력을 명시적으로 바꿔야 합니다.

기존 실행이 끝난 서비스에서 조회·화면만 확인합니다. UI 응답을 가짜 데이터로 교체하지 않습니다.

## 공개 파일 검증

`manifest.json`의 `public_files`에 각 파일의 SHA-256과 크기가 있습니다. `source_files`는 비공개 원본 해시와 공개 사본 해시의 관계를 기록합니다. 해시는 파일 무결성 확인용이며 판정의 정확성을 증명하지는 않습니다.
