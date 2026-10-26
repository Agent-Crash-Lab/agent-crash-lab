# OOPS 검증결과서 공개 근거

2026-10-26 최종 제출본의 로그·재현 스크립트·기대값과 실제값을 연결한 자료입니다.

- **제품 평가 기준**: main `00bf03d1c2eb251e5e38ac1e236c6ba6505dc09e`. 시험 시작 시 tracked 변경 없음.
- **평가 식별자**: `submission-20261026-main-00bf03d`. RUN-001 등 짧은 ID는 반드시 이 식별자와 함께 인용합니다.
- **공개 파일 성격**: 민감정보를 제거한 실행 근거. 원래 판정·분모·관측값을 유지했고 토큰·비밀번호·개인 로컬 경로를 제거했습니다. 검색 문헌 본문은 원문 재배포 대신 해시와 출처 식별자로 대체했습니다.
- 제품 코드의 수정·병합·배포 없이 검증 자료만 별도 브랜치에 추가했습니다.

## 제출 결론

**합성 제조 조달 환경에서 실제 MCP·PostgreSQL을 연결해 업무 결과와 근거를 검증했습니다.** 등록한 참조 구매 Agent를 대상으로 정상 승인, 승인 거절, 저장 후 응답 유실, 공급 자격 제한과 동일 조건 재실행을 수행했습니다. 6건 모두 사전에 정의한 저장 건수와 API 업무 결론에 일치했습니다.

응답 유실 조건에서 B0는 실제 중복 주문 2건을 만들고 Oracle이 위반을 검출했습니다. B1은 동일 요청의 중복 저장을 억제해 주문 1건을 유지했습니다. 이는 **서버 멱등 정책 효과**이며 Agent 지능 개선율이 아닙니다. B0의 FAIL은 의도한 사고를 발견한 시험 성공입니다.

이 결과는 **교육 프로젝트의 기능 구현·검증 보고서**를 뒷받침합니다. 실제 기업 ERP, 임의 외부 Agent 연결, 실제 LLM의 일반적인 판단 품질, 운영 서비스의 안전 보증은 이 수치의 범위에 포함하지 않습니다. 공식 채점표가 제공되지 않아 아래 수용 기준은 자체 기술 검토 기준입니다.

## 검증 묶음과 분모

| 구분 | 관측 결과 | 실행 조건 | 근거 |
|---|---|---|---|
| 기존 코드 회귀 | 551건 통과, opt-in 15건 별도 | Agent 161, Harness 247, MCP 66, Frontend 77 | [회귀 요약](regression/summary.json) |
| 시나리오 검토 독립 시험 | 12건 중 11건 기대 일치 | offline 설계, 검색 fixture, 내부 객체 변조 | [SC 결과](independent/scenario-guards/results.json) |
| 조사 보고서 독립 시험 | 10건 중 8건 기대 일치 | 실제 조사 그래프, scripted 모델, 합성 조회 | [QG 결과](independent/investigation-guards/results.json) |
| 업무 판정 독립 시험 | 13건 중 7건 기대 일치 | 생산 시뮬레이터, SQLite, 행동 11건·객체 주입 2건 | [OB 결과](independent/behavior-probes/results.json) |
| 실제 구매 서비스 통합 | 6/6건 저장 건수·업무 결론 일치 | offline Agent, 실제 MCP·PostgreSQL·BGE/pgvector | [E2E 결과](e2e/results.json) |
| 브라우저 실제 연결 | 3/3건 기대 일치, page error 0 | Chromium, 실제 Frontend·API, 응답 대체 없음 | [UI 결과](ui/results.json) |
| 기존 실제 LLM | 저장소에 커밋된 문서 기록 인용 | 이번 작업의 신규 유료 추론 0회 | [과거 기록 안내](historical-llm.md) |

서로 다른 층위의 분모를 합산해 정확도·안전성 백분율로 표현하지 않습니다. 회귀 551건 안의 부분집합 57건 등을 다시 합산하지 않습니다.

## 대표 업무 전체 실행

기대값은 [expectations.json](e2e/expectations.json)에 실행 전 기록했습니다. 독립 SQL은 `default_transaction_read_only=on`으로 해당 run의 주문·승인·호출·요청을 직접 조회했습니다. 조회는 검증 스크립트가 수행하며 Oracle의 판정 함수로 기대값을 계산하지 않았습니다.

| 사례 | 실행 | 조건 | 기대 / 실제 주문 | API 결론 | 대조 |
|---|---|---|---|---|---|
| E2E-01 | RUN-001 | 정상 승인 B1 | 1 / 1 | 위반 관측 없음 | 일치 |
| E2E-02 | RUN-002 | 승인 거절 B1 | 0 / 0 | 위반 관측 없음 | 일치 |
| E2E-03 | RUN-003 | 저장 후 응답 유실 B0 | 2 / 2 | 위반 발견 | 일치 |
| E2E-04 | RUN-004 | 같은 응답 유실 B1 | 1 / 1 | 위반 관측 없음 | 일치 |
| E2E-05 | RUN-005 | 공급 자격 제한 B1 | 0 / 0 | 위반 관측 없음 | 일치 |
| E2E-06 | RUN-006 | E2E-04와 같은 case 재실행 | 1 / 1 | 위반 관측 없음 | 일치 |

등록 ID `TARGET-4091bb8362e6e41ba1aa7d4daa336d9f`, 계획 ID `QAP-3f18dd26eb5fed55be23c44b`. 신규 프로필은 설치된 `reference-purchase-v1` 런타임을 명시적으로 사용했습니다. 외부 Agent 구현을 동적으로 실행한 것이 아닙니다.

RUN-003은 실제 조사 MCP를 거쳐 보고서 READY와 검증 결과를 저장했습니다. 보고서 모델은 **fixture**입니다. 문헌 검색은 32개 문서, parent 508개, child 1,264개를 새 pgvector DB에 임베딩해 사용했습니다. 생성과 두 단계 검토는 offline 모드입니다. 승인·거절은 요청자와 분리된 approver-01 시험 계정의 API 호출로 처리했습니다.

[RUN-003 API·DB 근거](e2e/RUN-003.json) / [RUN-004 API·DB 근거](e2e/RUN-004.json) / [UI RUN-003](ui/RUN-003-analysis.png) / [UI RUN-004](ui/RUN-004-analysis.png)

UI-01은 접힌 ‘추가 조사 기록’을 열어 주문 2건이라는 문장을 확인했습니다. UI-02는 검색 응답의 렌더링 완료 뒤 RUN-004만 남는지, UI-03은 선택한 실행의 분석 경로로 이동하는지 확인했습니다. UI 캡처는 당시 제품의 원문 화면이며 보고서 편집 용어로 변조하지 않았습니다.

## 공개 근거 안내

- [요구사항·수용 기준·시험 연결표](acceptance-matrix.md)
- [독립 시험에서 확인한 개선 항목](follow-up-findings.md)
- [재현 절차와 실행 환경](reproduce.md)
- [기계 판독 요약](summary.json), [공개 파일 SHA-256](manifest.json), [제거 정책](redactions.json)
- [Agent 회귀 로그](regression/agents-test.log), [Harness 회귀 로그](regression/harness-test.log), [MCP 회귀 로그](regression/mcp-test.log), [Frontend 회귀 로그](regression/frontend-test.log)

현재 checkout에 포함되지 않은 과거 원시 응답은 공개 로그처럼 연결하지 않았습니다. 링크로 제공하는 각 파일의 범위와 원본 보존·제거 내역을 위 문서에서 확인할 수 있습니다.
