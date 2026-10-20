package com.agentcrashlab.mcp.fault;

import java.sql.Timestamp;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

/**
 * 사고 주입 규칙 상태 (MCP_SPEC 3.3). 주입 동작(3.5)은 4단계에서 추가한다.
 */
@Component
public class FaultRules {

	private final JdbcClient jdbc;

	FaultRules(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	public List<Map<String, Object>> statuses(String runId) {
		return this.jdbc.sql("""
				SELECT fault_id, status, applied_count, applied_at, related_tool_call_id, related_order_id, evidence_id
				FROM fault_rule WHERE run_id = ? ORDER BY fault_id""")
			.param(runId)
			.query((rs, row) -> {
				Map<String, Object> fault = new LinkedHashMap<>();
				fault.put("fault_id", rs.getString("fault_id"));
				fault.put("status", rs.getString("status"));
				fault.put("applied_count", rs.getInt("applied_count"));
				Timestamp appliedAt = rs.getTimestamp("applied_at");
				fault.put("applied_at", (appliedAt != null) ? appliedAt.toInstant().toString() : null);
				fault.put("related_tool_call_id", rs.getString("related_tool_call_id"));
				fault.put("related_order_id", rs.getString("related_order_id"));
				fault.put("evidence_id", rs.getString("evidence_id"));
				return fault;
			})
			.list();
	}

}
