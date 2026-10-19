# 가상 데이터 초안

이 폴더는 **팀 리뷰용 fixture 제안**이다. 런타임 로더와 초기화 경로는 아직 없다.

- `purchase-seed.json`: 부품·공급업체·구매 자격·요청·역할. 실행 시 새 run_id로 복제한다.
- `agent-profiles.json`: 가상의 제조 업무 대상 4종. 실행 가능한 Agent 코드가 아니다.
- `oracle-cases.json`: 부분 정답 사건 9개. 명시하지 않은 검사 결과는 가정하지 않는다.
- `sources.json`: 공식 출처 9개와 확인일·사용 범위·한계. 사실/설계값을 구분한다.

정답 사례의 R01~R09 정의는 [시나리오 카탈로그](../../../scenarios/drafts/manufacturing-qa/catalog.json)의 base_rules에 있다. 승인 payload는 순서가 고정된 canonical JSON의 SHA-256으로 연결한다. 새 run_id·request_id를 넣으면 관련 승인·발주·hash를 함께 재생성해야 한다.

자료의 `DESIGNED_NOT_EXECUTED`, `SPECIFIED_NOT_IMPLEMENTED`는 구현·시험이 완료되지 않았다는 의미다. QA가 내놓는 실제 결과와 혼합하지 않는다.
