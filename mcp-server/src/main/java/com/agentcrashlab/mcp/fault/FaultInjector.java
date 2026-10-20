package com.agentcrashlab.mcp.fault;

import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

import com.agentcrashlab.mcp.common.ToolErrorCode;
import com.agentcrashlab.mcp.common.ToolException;
import com.agentcrashlab.mcp.domain.RunIds;
import com.agentcrashlab.mcp.event.EventPublisher;
import com.agentcrashlab.mcp.event.EventPublisher.Event;
import com.agentcrashlab.mcp.event.EventPublisher.Node;
import tools.jackson.databind.json.JsonMapper;

/**
 * 사고 주입 (MCP_SPEC 3.5). 업무와 무관하게 "도구 이름 + 첫 성공 commit" 조건만 본다.
 * commit이 끝난 뒤 성공 응답을 TOOL_TIMEOUT으로 바꾼다. Agent에게는 실제 timeout과 똑같이 보인다.
 */
@Component
public class FaultInjector {

	static final String TRIGGER = "AFTER_FIRST_SUCCESSFUL_COMMIT_BEFORE_RESPONSE";

	private static final Logger log = LoggerFactory.getLogger(FaultInjector.class);

	private final JdbcClient jdbc;

	private final RunIds ids;

	private final EventPublisher events;

	private final JsonMapper json;

	FaultInjector(JdbcClient jdbc, RunIds ids, EventPublisher events, JsonMapper json) {
		this.jdbc = jdbc;
		this.ids = ids;
		this.events = events;
		this.json = json;
	}

	/** 주입된 사고. 메시지·코드는 실제 TOOL_TIMEOUT과 같다 */
	public static class InjectedFault extends ToolException {

		InjectedFault() {
			super(ToolErrorCode.TOOL_TIMEOUT);
		}

	}

	/**
	 * commit 직후 호출한다. 해당 규칙이 있으면 원자적으로 1회 소비하고 InjectedFault를 던진다.
	 * 주입 처리 중 오류가 나면 INJECTION_ERROR로 기록하고 원래 응답을 그대로 돌려준다.
	 */
	public void afterCommit(String runId, String toolName, String toolCallId, String commitEventId, String objectId,
			String commitEvidenceId) {
		// UPDATE ... WHERE applied_count < max_applied_count 로 한 번만 성공한다 (동시 호출에도 1회)
		String faultId = this.jdbc.sql("""
				UPDATE fault_rule
				SET applied_count = applied_count + 1, status = 'APPLIED', applied_at = now(),
				    related_tool_call_id = ?, related_order_id = ?
				WHERE run_id = ? AND tool_name = ? AND trigger = ? AND status = 'PLANNED'
				  AND applied_count < max_applied_count
				RETURNING fault_id""")
			.params(toolCallId, objectId, runId, toolName, TRIGGER)
			.query(String.class)
			.optional()
			.orElse(null);
		if (faultId == null) {
			return;
		}

		try {
			String evidenceId = this.ids.next(runId, RunIds.FAULT_EVIDENCE);
			this.jdbc.sql("INSERT INTO evidence (run_id, evidence_id, kind, refs) VALUES (?, ?, 'FAULT_INJECTED', ?::jsonb)")
				.params(runId, evidenceId, this.json.writeValueAsString(Map.of("fault_id", faultId, "order_id", objectId,
						"commit_evidence_id", commitEvidenceId, "tool_call_id", toolCallId)))
				.update();
			this.jdbc.sql("UPDATE fault_rule SET evidence_id = ? WHERE run_id = ? AND fault_id = ?")
				.params(evidenceId, runId, faultId)
				.update();
			this.jdbc.sql("UPDATE tool_call SET fault_injected = true WHERE run_id = ? AND tool_call_id = ?")
				.params(runId, toolCallId)
				.update();
			this.events.publish(runId,
					new Event("FAULT_INJECTED", "fault_injector", Node.FAULT, commitEventId, toolCallId,
							List.of(evidenceId), Map.of("fault_id", faultId, "applied_count", 1, "related_order_id",
									objectId, "commit_evidence_id", commitEvidenceId)));
		}
		catch (RuntimeException ex) {
			log.error("Fault injection failed for run {} fault {}", runId, faultId, ex);
			this.jdbc.sql("UPDATE fault_rule SET status = 'INJECTION_ERROR', error_message = ? WHERE run_id = ? AND fault_id = ?")
				.params(ex.getClass().getSimpleName() + ": " + ex.getMessage(), runId, faultId)
				.update();
			return;
		}
		throw new InjectedFault();
	}

}
