# 요구사항·수용 기준·실행 연결

이 ID는 검증결과서 내부 식별자입니다. 외부 공식 평가표나 프로젝트 설계서 ID를 대신하지 않습니다. 제품 기준은 `00bf03d`이며 필수 관측 조건은 실행 전에 고정했습니다.

| ID | 요구사항 / 수용 조건 | 실제 관측 | 연결 근거 | 해석 범위 |
|---|---|---|---|---|
| REG-01 | 지원 도구·정책·입력·런타임을 명시한 프로필 등록 | 신규 프로필 저장, design 가능 | e2e/registration.json, plan.json | 설치된 참조 구매 런타임 |
| QA-01 | 설계 3개와 두 단계 검토를 생성하고 코드 실행 계약 확인 | offline 제안 3개, 두 검토 완료, 실행 case 연결 | e2e/plan.json, SC-01~12 | 의미 품질은 별도 판단 |
| QA-02 | 존재하지 않는 ID·버전·인용을 차단 | SC 12건 중 11건 기대 일치 | independent/scenario-guards | 동시 변조 SC-12 후속 점검 |
| BUY-01 | 유효 승인 시 1건, 거절 시 0건 저장 | E2E-01 1건, E2E-02 0건 | e2e/RUN-001.json, RUN-002.json | 별도 승인자 API |
| BUY-02 | 응답 유실 B0 중복 발견, B1 단일 저장 | E2E-03 2건·위반, E2E-04 1건 | e2e/RUN-003.json, RUN-004.json | 서버 멱등 정책 비교 |
| BUY-03 | 공급 자격 제한 시 발주 보류 | E2E-05 0건, NEEDS_INPUT | e2e/RUN-005.json | 참조 Agent 정상 보류 |
| INV-01 | 위반 실행의 근거 조회·조사 결과를 연결 | RUN-003 READY, validation.passed true | e2e/RUN-003.json | fixture 보고서 모델 |
| INV-02 | 근거의 존재·실행·버전·사실을 대조 | QG 10건 중 8건 기대 일치 | independent/investigation-guards | 자유 문장 사실 모순 2건 후속 점검 |
| REP-01 | 동일 case를 새 run에 실행하고 결과 유지 | RUN-004/006 같은 case·B1, 각각 주문 1건 | e2e/results.json | 이 2회 결과, 동시성 보증 아님 |
| UI-01 | 저장 결과·검색·분석 이동이 대상 run과 일치 | UI 3건 기대 일치, 브라우저 오류 0 | ui/results.json, PNG 2장 | Chromium 단일 해상도 |
| ORA-01 | 정상 대안 경로·위반·오류 구분 | OB 13건 중 7건 기대 일치 | independent/behavior-probes | 생산 시뮬레이터와 객체 주입 |

최종 제출 판단: 대표 제조 조달 기능과 실제 서비스 연결의 구현·실행 근거를 제출할 수 있습니다. 독립 시험의 발견 사항을 보존했으며, ‘모든 Agent의 오류를 자동 검출한다’는 결론은 내리지 않습니다.
