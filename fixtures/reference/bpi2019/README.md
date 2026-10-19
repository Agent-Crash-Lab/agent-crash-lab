# BPI Challenge 2019 실제 구매 로그 표본

자료: van Dongen, B.F. (2019), **BPI Challenge 2019**, 4TU.Centre for Research Data.

- [DOI와 원본](https://doi.org/10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1)
- [공식 설명](https://icpmconference.org/2019/icpm-2019/contests-challenges/bpi-challenge-2019/)
- 라이선스: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). 해당 DOI의 DataCite rightsList에서 확인.

`sample.json`은 공식 XES 파일 첫 131,072바이트에서 완전한 trace 10개·이벤트 132개를 추출하고 JSON으로 형식 변환한 것이다. 익명 ID·시간·값은 유지했다. 무작위/대표 표본이 아니며 원본 전체는 포함하지 않는다. 수집 시각·주소·바이트 범위·해시·라이선스 메타데이터는 파일 안에 있다.

제조기업의 구매-지급 로그지만 서비스 구매도 포함된다. 승인 워크플로 전체, AI Agent 대화, MCP trace, 응답 유실 여부, 행동 정답은 없다. 일부 SRM 승인 대기 상태로 승인자·내용·권한을 판정하지 않는다. 반복 입고·송장을 중복 발주로 해석하지 않는다.

활용: 업무 이벤트와 case_id 구조 이해, 타임라인 예시의 출처. 실행용 seed와 Oracle의 정답은 `fixtures/drafts/manufacturing-qa/`의 합성 자료를 사용한다.
