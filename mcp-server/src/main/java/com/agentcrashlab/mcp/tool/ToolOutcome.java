package com.agentcrashlab.mcp.tool;

import java.util.Map;

/**
 * 도구 본문이 ToolRunner에 알려 주는 결과 종류. 일반 조회 결과는 이 타입 없이 그대로 돌려준다.
 * 이벤트 기록과 사고 주입은 ToolRunner가 이 신호만 보고 처리하므로, 업무 로직은 둘 다 몰라도 된다.
 */
public sealed interface ToolOutcome {

	/** Agent에게 돌려줄 결과 */
	Map<String, Object> result();

	/**
	 * 업무 변경이 commit됐다. BUSINESS_COMMITTED 이벤트를 남기고 사고 주입 규칙을 확인한다.
	 * @param objectId 변경된 업무 객체 ID (예: order_id)
	 * @param commitEvidenceId commit 근거 ID
	 * @param eventPayload BUSINESS_COMMITTED 이벤트 payload
	 */
	record Committed(Map<String, Object> result, String objectId, String commitEvidenceId,
			Map<String, Object> eventPayload) implements ToolOutcome {
	}

	/** 새 commit 없이 이전 응답을 그대로 돌려줬다 (idempotent-v1 재사용 응답) */
	record Replayed(Map<String, Object> result) implements ToolOutcome {
	}

}
