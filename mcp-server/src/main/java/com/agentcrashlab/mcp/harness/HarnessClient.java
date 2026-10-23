package com.agentcrashlab.mcp.harness;

import java.util.List;
import java.util.Map;

import com.agentcrashlab.mcp.domain.Approvals;

/**
 * MCP → Harness 내부 API (MCP_SPEC 4장).
 */
public interface HarnessClient {

	/** 4.1 승인·거절 후 Agent 재개 요청. Harness는 같은 approval_id를 한 번만 재개한다 */
	void resume(String runId, Approvals.Decision decision);

	/** 4.2 이벤트 제출. 본문은 2.1 이벤트에서 sequence를 뺀 형태이고, sequence는 Harness가 발급한다 */
	void submitEvent(String runId, Map<String, Object> event);

	/** 4.3 조사용: FAIL·INCONCLUSIVE 검사 목록 (QaCheck[]) */
	List<Map<String, Object>> failedChecks(String runId);

	/** 4.3 조사용: 저장된 이벤트 목록 (sequence 순) */
	List<Map<String, Object>> runEvents(String runId);

	/** 4.4 조사용: 생산·품질 모의 환경의 업무 상태와 도구 호출 (Harness가 원본) */
	Map<String, Object> simulationState(String runId);

}
