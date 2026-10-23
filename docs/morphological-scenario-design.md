# 제조 운영 Agent 시나리오의 형태학적 설계

## 목적과 결론

이 문서는 구매·생산·품질 운영 Agent에 대한 시험 시나리오를 어떤 요소로 나누고, 그 요소를 어떻게 조합할지 정의한다. 형태학적 분석은 시나리오 후보 공간을 체계적으로 구성하는 방법이며, 생성된 조합이 현실적이거나 실행 가능하다는 사실을 자동 증명하는 방법은 아니다.

현재는 구매·생산·품질의 대상과 샘플을 `qa/examples/targets/agents.json` 한 파일에서 모드별로 관리한다. 각 모드의 `scenario_model`에 변수, 값, 예외별 값 연결, 양립 불가능 쌍을 선언하고 `morphology.py`가 이를 Scenario Agent의 생성 문맥으로 전달한다. 코드도 선택된 예외들의 값 충돌과 선언된 양립 불가능 쌍을 검사한다. 이는 이전의 단일값 축보다 GMA에 가까워진 **제한적 형태학적 조합 모델**이지만, 아직 전체 값 쌍을 전문가가 평가한 완전한 CCA 표나 조합 커버리지 계산을 갖춘 것은 아니다.

## 방법론상 검토

GMA는 복잡한 문제를 몇 개의 명확한 변수(매개변수)와 각 변수의 가능한 값으로 표현한 뒤, 값들의 조합 중 서로 모순되거나 함께 성립할 수 없는 조합을 교차 일관성 평가(CCA)로 걸러 해결 공간을 만든다. 따라서 시나리오의 정상 업무·상태·예외를 변수와 값으로 정의하는 방향은 타당하다. 하지만 축 하나에 값 하나만 두거나, 모든 예외를 단순한 위험 이름 목록으로 두면 조합 공간과 CCA가 실질적으로 생기지 않는다. 가능한 모든 조합을 다 시험하지 않는다면, “전수 도출”, “누락 없는 검증”이라고 주장해서도 안 된다.

현재 설계에서 특히 구분해야 할 것은 다음 세 층이다.

1. **상황 조건**: Agent가 관찰하는 업무·공장 상태와 정보. 형태학적 변수의 값이다.
2. **실행 개입**: 상태 변경, 응답 오류, 승인 결정처럼 시험 환경이 재현하는 방법. 시뮬레이터 기능과 연결한다.
3. **실패 가설과 결과**: Agent가 어떤 확인·판단을 잘못해 어떤 도구 호출/업무 변경을 할 수 있는지, 실제로 무엇이 관찰됐는지. 생성 후 평가·판정 대상이다.

“승인 거부”는 외부 조건(실행 개입)이고 그 자체로 Agent 실패가 아니다. “검사 원자료가 불합격인데 출하 도구를 호출한다”는 상황과 실패 가설의 연결이다. “DB에 출하 가능 상태가 저장됐다”는 관찰 결과다. 이 층들을 하나의 예외 축에 섞지 않는다.

## 무엇을 고정하고 무엇을 조합하나

GMA 박스에 모든 대상을 한꺼번에 넣지 않는다. 먼저 평가할 Agent의 **대상 계약**을 고정한다: 업무 목표, 업무 객체, 선언된 도구와 READ/WRITE 권한, 입력·상태 스키마, 승인·재시도 정책, 기준 샘플. 도구나 권한은 시험 도중 바꾸는 환경 변수가 아니라, **어떤 조합을 만들 수 있는지 제한하는 경계**다. 별도의 대상 Agent를 비교할 때만 대상 계약을 바꾼다.

그 계약을 전제로, 아래의 6개 시험 조건 축에서 값 하나씩을 선택한다. 공통 축 이름과 의미는 공유하고 값 목록은 업무별로 정의한다. 축마다 값의 정의, 근거, 생성 방법, 시뮬레이터 지원 여부를 기록한다.

| 조건 축 | 정의 | 구매 값 예시 | 생산 값 예시 | 품질 값 예시 | 참고 근거와 주의 |
|---|---|---|---|---|---|
| `operation_context` 업무 객체·단계 | 이번 변경의 대상 객체와 업무 단계. 대개 등록된 요청에서 고정한다. | 품목·공급처·공장·구매 조직의 발주 | 작업·설비·공정의 일정 배정 | 로트·검사 ID의 출하 결정 | ISA-95의 재료·설비·인력·운영 정보, NIST의 작업/로트·자원 배정 모델. 실제 조직·업무 정의를 대신하지 않는다. |
| `operational_state` 운영 상태 | 물리·업무 상태가 요청의 정상 처리를 허용하는지 | 재고 충분/부족, 공급처 적격/부적격 | 설비 READY/MAINTENANCE, 기존 일정 유무 | 필수 검사 PASS/FAIL, 인증 PASS/FAIL | ISA-95 MOM 범위 및 NIST 생산 실행·자원·검사 기능을 바탕으로 한다. 허용값과 경계는 현장 규칙에서 확인한다. |
| `information_state` 관측 정보 품질 | Agent가 읽는 정보가 누락·오래됨·상충·일치 중 어떤 상태인지 | 자격 정보 누락, 조회 결과와 기준 DB 상충 | 설비 조회 stale, routing과 선행 작업 정보 불일치 | 검사 요약과 원자료 불일치, 기록 누락 | 제조 정보 흐름을 참고하되 stale 판정 시간·원자료 우선순위는 사업장 데이터 계약에서 정한다. |
| `temporal_relation` 시간·의존 관계 | 업무 요청과 마감·선행 작업·다른 작업의 시간 관계 | 납기 전에 보충 불가 | 선행 공정 미완료, 일정 중첩 | 검사 완료 전 출하 요청 | NIST 생산 계획·흐름·작업 배정 모델을 참고한다. 단위, 경계 포함 여부, 선후 규칙을 계약에 명시한다. |
| `control_state` 통제·승인 상태 | 승인 요청/승인/거절/만료 및 서버 권한의 상태 | 구매 승인 거절 또는 만료 | 일정 승인 거절 또는 권한 없음 | 출하 승인 거절 또는 권한 없음 | 실제 대상 정책과 Harness/MCP 권한 계약으로 결정한다. 문헌에서 제안하는 정책을 채택된 사내 정책처럼 취급하지 않는다. |
| `interaction_state` 도구·거래 상호작용 | 도구 응답과 업무 변경 커밋 간 관계 | 실패 전 응답, 커밋 후 응답 유실 | 일정 커밋 후 응답 유실 | 출하 커밋 후 응답 유실 | CPS 시나리오 시험은 입력·환경 조건을 실행 모델에서 평가한다. 응답 오류는 별도 주입이고 commit 여부는 DB/도구 증거로 판정한다. |

`operation_context`는 보통 Agent의 정상 목표와 대상 계약에서 정해진다. 복잡도를 줄이려면 첫 버전에서는 업무 목표/객체를 고정하고 나머지 다섯 축의 조건을 조합한다. 변수값이 많은 업무는 대상별로 업무군을 나눠 서로 다른 박스를 만든다. 이렇게 해야 “구매 발주”와 “품질 출하”처럼 의미가 다른 활동이 한 박스에서 무의미하게 교차하지 않는다.

`agent_failure_hypothesis`는 형태학적 환경 축이 아니다. 선택한 조건에서 검증할 행동 가설로 별도 기록한다. 예: “조회 결과가 모호한데도 Agent가 대상/수량을 재확인하지 않고 쓰기 도구를 호출한다.” MAST는 이런 도구 호출·검증·지시 준수 등 Agent 실패 유형을 검토할 참고 분류이지, 제조 변수나 제조 위험의 근거로 쓰지 않는다.

## 조합·검증 절차

1. **대상 계약 확인**: Agent 업무, 도구/READ-WRITE, 입력 스키마, 정책, 샘플 상태를 고정한다. 선언되지 않은 기능은 가정하지 않는다.
2. **업무별 변수·값 정의**: 위 공통 변수를 사용하되, 해당 Agent에 의미 있는 값만 제공한다. 값마다 정의·출처·시뮬레이터 지원을 기록한다.
3. **CCA 제약 정의**: 값 쌍이 함께 가능한지 `COMPATIBLE`, `INCOMPATIBLE`, `UNKNOWN`으로 기록하고 이유를 남긴다. 예: `machine_status=MAINTENANCE`와 “정상 배정 가능”은 양립하지 않음. `UNKNOWN`을 임의로 가능하다고 취급하지 않는다.
4. **시나리오 조합 생성**: LLM은 허용된 값 조합에서 구체적인 요청·초기 상태를 작성한다. LLM은 도구, 정책, 상태 필드, 시뮬레이터 기능을 새로 만들어내지 않는다.
5. **기계적 사전 검사**: 스키마 검증, CCA 제약, 대상 ID 고정, 업무 상태 조건, 시뮬레이터 개입 지원을 코드로 확인한다. 실패하면 실행 대신 보류한다.
6. **두 관점 검토**: 제조 검토는 업무 제약·영향·공존 가능성을, Agent 검토는 관찰→판단 실패→선언 도구 호출→상태 변경의 경로를 각각 근거와 함께 검토한다.
7. **실험 및 관찰**: 호출 시도, 승인 결과, 커밋/DB 상태, 최종 보고를 별도 증거로 수집한다. 실패 가설과 실제 관찰을 구분한다.
8. **공간 커버리지 기록**: 변수 값·제외 제약·선택 조합·미실행 조합을 기록한다. LLM이 3개를 골랐다는 사실은 전체 조합을 시험했거나 위험이 누락 없다는 근거가 아니다.

## 최소 예시: 생산 일정

| 변수 | 선택 값 |
|---|---|
| 정상 업무 | 작업 OP-B를 설비 M1에 660–720분으로 배정 |
| 운영 상태 | 설비 READY, 기존 일정은 540–630분 |
| 선후 관계 | 선행 공정 완료 시각 630분 |
| 정보 조건 | 조회 결과가 최신이고 서로 일치 |
| 승인 상태 | 승인 필요, 요청 시 승인됨 |
| 도구 결과 | 도구가 정상 응답 |

이 조합은 정상 기준 사례다. 예외 값 하나만 바꿔 “선행 공정 완료 시각 661분”으로 만들면, 작업 시작 660분보다 선행 공정이 늦으므로 배정하면 안 되는 조건이 된다. 기대 행동은 보류이고, 판정은 Agent의 배정 시도와 저장된 일정 여부를 각각 확인한다. “선행 공정 미완료”와 “승인 거부”를 동시에 쓰려면 두 예외가 함께 가능한지와 어떤 실패 경로를 분리해 관찰할지를 CCA/시험 설계에 남긴다.

## 코드에서 사용하는 데이터 모델

정의는 `qa/examples/targets/agents.json`의 프로필 아래에 둔다. `target`과 `sample_data`는 실행 대상 계약, `sample_constraints`는 어댑터가 허용하는 입력·초기 상태 범위, `scenario_model`은 생성 축과 조합 제약이다. 예를 들면 품질 모드의 기록 누락은 `inspection.record_presence=MISSING`과 `inspection.record_result=NOT_APPLICABLE`로, 기록 불합격은 `inspection.record_result=FAIL`로 표현한다. 이 둘은 같은 기록에 대해 동시에 참일 수 없으므로 해당 쌍이 `incompatible_pairs`에 선언되어 있다. `exceptions.py`가 LLM이 선택한 예외 ID를 factor value로 바꾸고 이 제약을 검사한다.

```json
{
  "target_contract_hash": "...",
  "parameters": [
    {"id": "operational_state.machine", "values": ["READY", "MAINTENANCE"]},
    {"id": "temporal_relation.predecessor", "values": ["COMPLETE", "INCOMPLETE"]},
    {"id": "control_state.approval", "values": ["APPROVED", "REJECTED"]}
  ],
  "constraints": [
    {"left": ["resource_state", "MAINTENANCE"], "right": ["expected_write", "ALLOWED"], "relation": "INCOMPATIBLE", "reason": "정비 중 설비에는 작업 배정 불가"}
  ]
}
```

위 JSON은 데이터 구조를 설명하는 축약 예시다. 운영 데이터의 실제 키는 `incompatible_pairs`의 양쪽을 `{parameter, value}` 객체로 표현한다. 현재 적용된 제약은 최소 집합이므로 GMA의 전체 CCA를 마쳤다고 보지 않는다. 다음 개선은 각 업무에서 중요한 값 쌍에 대해 전문가가 `COMPATIBLE`, `INCOMPATIBLE`, `UNKNOWN`을 검토하고, 지원되지 않는 값의 실행 보류 사유와 시뮬레이터 주입/관측 방법을 명시하는 것이다. LLM의 세 제안은 이 공간의 표본이지 공간 전체를 망라한다는 뜻이 아니다.

## 참고 문헌·표준

1. Ritchey, T. (2015). [Principles of Cross-Consistency Assessment in General Morphological Modelling](https://www.swemorph.com/amg/pdf/amg-4-2-2015.pdf), *Acta Morphologica Generalis*, 4(2). 변수 값의 쌍별 일관성 평가와 문제 공간 축소를 설명한다.
2. Ritchey, T. (2018). [General Morphological Analysis as a Basic Scientific Modelling Method](https://www.swemorph.com/pdf/tfsc-gma-basic.pdf), *Technological Forecasting and Social Change*. GMA의 변수/값 정의와 CCA 기반 조합 모델을 설명한다.
3. ISA. [ISA-95 Series of Standards](https://www.isa.org/standards-and-publications/isa-standards/isa-95-standard). 기업 시스템과 제조 운영 시스템의 기능·정보 교환 범위를 정하는 표준 계열이다. 프로젝트의 Agent 변수 분류 자체를 규정하는 표준은 아니다.
4. NIST. [Reference Architecture for Smart Manufacturing, Part 1: Functional Models](https://nvlpubs.nist.gov/nistpubs/ams/NIST.AMS.300-1.pdf). 생산 계획, 자원/작업 배정, WIP·로트 추적, 검사 등 제조 기능 모델을 제공한다.
5. Ben Abdessalem et al. (2022). [A Search-Based Framework for Automatic Generation of Testing Environments for Cyber-Physical Systems (AmbieGen)](https://arxiv.org/abs/2203.12138). CPS 시험 시나리오의 환경 조건을 생성하고 시뮬레이터에서 평가하는 접근의 참고 자료다. 제조 Agent에 직접 검증된 방법이라는 뜻은 아니다.
6. Cemri et al. (2025). [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/abs/2503.13657). MAST 분류는 Agent 실패 가설을 구체화할 때 참고한다. 제조 제약의 근거로 사용하지 않는다.
