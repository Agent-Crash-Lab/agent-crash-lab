# 과거 실제 LLM 기록과 이번 실행의 구분

이번 제출 보강은 신규 유료 LLM 호출 없이 수행했습니다. 실제 LLM 기록은 아래 고정 커밋의 문서만 인용했습니다.

- [12개 입력 실행 기록](https://github.com/Agent-Crash-Lab/agent-crash-lab/blob/00bf03d1c2eb251e5e38ac1e236c6ba6505dc09e/docs/scenario-agent-validation/live-run-20261023.md)
- [수정 기록과 RUN-157/158](https://github.com/Agent-Crash-Lab/agent-crash-lab/blob/00bf03d1c2eb251e5e38ac1e236c6ba6505dc09e/docs/scenario-agent-validation/correction-log.md)

12개 입력 기록에는 생성 12/12회, 설계 API 반환 6/12건, 검토 7회 중 구조화 반환 1회·응답 중단 3회·근거 오류 3회가 적혀 있습니다. 문서가 지칭한 과거 원시 JSON은 이번 clean clone에 포함되지 않아 원문 재대조를 수행한 것으로 계산하지 않습니다. 생성 호출 성공, 설계 API 반환, 두 검토 완료, 품질 기준은 서로 다른 수치입니다.

현재 공개된 E2E RUN-001~006은 신규 격리 DB의 실행입니다. 과거 RUN-157/158과 이어 붙인 동일 실험으로 해석하지 않습니다.
