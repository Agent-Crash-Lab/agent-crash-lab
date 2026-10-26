# 프론트엔드 실제 실행 화면

2026-10-26 KST에 프론트엔드를 다시 실행하고 실제 API로 기존 저장 실행을 조회해 캡처했습니다. Agent를 새로 실행하거나 기존 DB를 초기화하지 않았습니다.

- 제품 기준: `00bf03d1c2eb251e5e38ac1e236c6ba6505dc09e`
- 평가 묶음: `submission-20261026-main-00bf03d`
- 실제 서비스: Frontend, MCP, Harness, PostgreSQL. 기존 실행의 Agent 모델은 offline, 조사 보고서는 fixture입니다.
- 캡처: Chromium, viewport 1440×1000, deviceScaleFactor 2. 데이터나 화면 문구를 대체하지 않았습니다. 요소별 원본 스크린샷이며 픽셀 편집·AI 이미지 생성은 사용하지 않았습니다.
- 신규 성능 시험 수에 합산하지 않습니다. 브라우저 page error는 0건입니다.

| 캡처 | 확인 내용 |
|---|---|
| [RUN-003 3D 장면](RUN-003-scene.png) | 저장 이벤트 32를 선택한 상태, 업무 DB 저장 2건 |
| [선택한 저장 이벤트](RUN-003-event.png) | BUSINESS_COMMITTED, REQ-001, PO-002, TC-005, EV-COMMIT-002 연결. 스크롤 패널의 화면 표시 영역 |
| [B0 판정 요약](RUN-003-kpi.png) | 통과 규칙 5개, 위반 규칙 3개, 실제 주문 2건 |
| [B1 판정 요약](RUN-004-kpi.png) | 통과 규칙 8개, 위반 규칙 0개, 실제 주문 1건 |
| [RUN-003 전체 요약 영역](RUN-003-summary.png) | 실행 ID, 모델·조사 상태, DB 관측 상태 |
| [RUN-004 전체 요약 영역](RUN-004-summary.png) | 실행 ID와 B1 결과 |
| [저장 실행 목록](saved-runs.png) | 보존된 실행 이력 조회 |

**해석**: B0의 ‘3개 실패’는 중복 없음·완료 보고 사실 일치·정상 완료의 세 규칙에 대한 위반입니다. 사고 3건 또는 Agent 3개의 실패를 뜻하지 않습니다. B1은 같은 저장 후 응답 유실 조건에서 멱등 정책으로 단일 주문을 유지했습니다. 이는 서버 정책의 비교입니다.

장면은 사건 32 시점을 선택한 화면이므로 그 뒤 Oracle·조사 Agent의 이벤트 수는 0으로 표시됩니다. 전체 실행에서는 87개 이벤트와 조사 READY가 저장됐습니다. 장면의 시점별 표시와 최종 결과를 구분합니다.

실제 원시 기록은 [RUN-003](../../e2e/RUN-003.json), [RUN-004](../../e2e/RUN-004.json)에 있으며, [캡처 메타데이터·SHA-256](capture-manifest.json)에 경로·시각·화면 텍스트가 있습니다. 원문 제품 화면의 용어는 보존했습니다.

재현: Playwright Chromium 설치 후 `ACL_TEST_PASSWORD`, `ACL_UI_URL`, `ACL_CAPTURE_OUT`을 환경변수로 설정하고 `node capture_ui.mjs`를 실행합니다. 해당 평가 묶음의 RUN-003/004가 있는 DB를 조회해야 합니다. 스크립트가 새로 만드는 11개 진단 캡처 중 이 폴더에는 제출용 원본 7장을 제공합니다.
