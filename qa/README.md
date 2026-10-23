# QA 데이터 안내

`qa/`에는 실행 코드가 아니라 서비스가 함께 쓰는 계약, 지식, 참조 입력이 있습니다. 실제 시험에 쓰이는 입력과 출처를 정리하는 보조 기록을 구분합니다.

| 위치 | 용도 | 기준 파일 / 사용처 |
|---|---|---|
| `contracts/` | 서비스 간 요청·응답 형식 | 공통 JSON Schema. Harness·Agent·MCP가 함께 참조 |
| `knowledge/corpus.json` | RAG가 검색하는 문서와 요약 | 색인 입력의 기준 파일 |
| `knowledge/risk-patterns.json` | 코드 판정에 연결된 실행 위험 템플릿 | Harness 계획·판정 |
| `knowledge/risk-library.json` | Scenario Agent가 보는 위험 분류와 검색 힌트 | 설계·검토 입력 |
| `knowledge/manufacturing-operations.json` | 업무 제약과 합성 상태 변경 예시 | Scenario Agent의 생성 참고 |
| `knowledge/sources.json`, `literature.json`, `sources-collected.json` | 출처 조사·수집·검토 이력 | 목록 및 감사용 기록. RAG 원문 입력은 아님 |
| `knowledge/guides/` | 승인·재시도·조사 해석 안내 | Scenario·QA 조사 참고 자료 |
| `knowledge/scenario-review-rubric.json` | 제조업·Agentic 2단계 점수 기준과 통과 규칙 | Scenario Agent 및 Harness 평가 계약 |
| `examples/` | 참조 대상·시험 입력·판정 사례 | 파일별 연결은 [예시 길잡이](examples/README.md) 참고 |
| `reference/` | 외부 공개 데이터 표본 | 출처 분석용. Agent 정답이나 운영 데이터가 아님 |

변경할 때 적용할 폴더 소유권, 파일명·변수명, 근거 기록 및 검증 절차는 [QA 데이터 협업 규칙](CONTRIBUTING.md)을 따릅니다. 제조업과 Agentic 검토는 점수와 문헌 근거를 각각 기록하고, 두 단계가 모두 기준을 통과해야 시나리오가 실행 연결 대상으로 올라갑니다.

`sources*.json`과 `literature.json`은 `corpus.json`의 대체 색인 파일이 아닙니다. 자료 수집·조사 과정과 출처 설명을 남깁니다. 현재 RAG에 무엇이 들어가는지는 `corpus.json`에서 확인합니다.

자세한 필드, 색인, 저장 위치, 등록 방법은 [데이터 안내](../docs/data-guide.md)를 보세요. 전체 시스템은 [아키텍처 안내](../docs/architecture.md), 참조 Agent의 출처와 기능은 [예시 길잡이](examples/README.md)에 설명되어 있습니다.
