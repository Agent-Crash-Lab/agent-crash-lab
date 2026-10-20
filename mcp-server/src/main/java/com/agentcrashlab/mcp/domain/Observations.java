package com.agentcrashlab.mcp.domain;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

import tools.jackson.databind.json.JsonMapper;

/**
 * 업무 상태 관측. 필드는 drafts oracle-observation.schema.json과 정확히 같다 (추가 필드 없음).
 * finalize(MCP_SPEC 3.4)와 get_business_state(1.4)가 함께 쓴다. 사고 hook을 거치지 않고 DB를 직접 읽는다.
 */
@Component
public class Observations {

	private final JdbcClient jdbc;

	private final JsonMapper json;

	Observations(JdbcClient jdbc, JsonMapper json) {
		this.jdbc = jdbc;
		this.json = json;
	}

	public Map<String, Object> observe(String runId, boolean snapshotComplete, int pendingToolCalls) {
		String requestId = this.jdbc.sql("SELECT request_id FROM purchase_request WHERE run_id = ? ORDER BY created_at LIMIT 1")
			.param(runId)
			.query(String.class)
			.single();

		List<Map<String, Object>> orders = this.jdbc.sql("""
				SELECT order_id, run_id, request_id, approval_id, payload::text AS payload, commit_sequence, committed_at
				FROM purchase_order WHERE run_id = ? AND request_id = ? ORDER BY commit_sequence""")
			.params(runId, requestId)
			.query((rs, row) -> {
				Map<String, Object> order = new LinkedHashMap<>();
				order.put("order_id", rs.getString("order_id"));
				order.put("run_id", rs.getString("run_id"));
				order.put("request_id", rs.getString("request_id"));
				order.put("approval_id", rs.getString("approval_id"));
				order.put("payload", payload(rs.getString("payload")));
				order.put("commit_sequence", rs.getInt("commit_sequence"));
				order.put("committed_at", rs.getTimestamp("committed_at").toInstant().toString());
				return order;
			})
			.list();
		List<String> commitEvidenceIds = this.jdbc.sql("""
				SELECT commit_evidence_id FROM purchase_order
				WHERE run_id = ? AND request_id = ? ORDER BY commit_sequence""")
			.params(runId, requestId)
			.query(String.class)
			.list();

		List<Map<String, Object>> approvals = this.jdbc.sql("""
				SELECT approval_id, run_id, request_id, request_version, approver_id, decision, payload::text AS payload,
				       payload_hash, revoked, decision_sequence, authority_valid, decided_at
				FROM approval WHERE run_id = ? AND request_id = ? ORDER BY decision_sequence""")
			.params(runId, requestId)
			.query((rs, row) -> {
				Map<String, Object> approval = new LinkedHashMap<>();
				approval.put("approval_id", rs.getString("approval_id"));
				approval.put("run_id", rs.getString("run_id"));
				approval.put("request_id", rs.getString("request_id"));
				approval.put("request_version", rs.getInt("request_version"));
				approval.put("approver_id", rs.getString("approver_id"));
				approval.put("decision", rs.getString("decision"));
				approval.put("payload", payload(rs.getString("payload")));
				approval.put("payload_hash", rs.getString("payload_hash"));
				approval.put("revoked", rs.getBoolean("revoked"));
				approval.put("decision_sequence", rs.getInt("decision_sequence"));
				approval.put("authority_valid", rs.getBoolean("authority_valid"));
				approval.put("decided_at", rs.getTimestamp("decided_at").toInstant().toString());
				return approval;
			})
			.list();

		List<String> snapshotEvidenceIds = this.jdbc
			.sql("SELECT evidence_id FROM evidence WHERE run_id = ? AND kind = 'BUSINESS_SNAPSHOT' ORDER BY created_at")
			.param(runId)
			.query(String.class)
			.list();

		Map<String, Object> observation = new LinkedHashMap<>();
		observation.put("run_id", runId);
		observation.put("request_id", requestId);
		observation.put("snapshot_complete", snapshotComplete);
		observation.put("pending_tool_calls", pendingToolCalls);
		observation.put("snapshot_evidence_ids", snapshotEvidenceIds);
		observation.put("commit_evidence_ids", commitEvidenceIds);
		observation.put("orders", orders);
		observation.put("approvals", approvals);
		return observation;
	}

	private Map<String, Object> payload(String jsonb) {
		return PurchasePayload.fromMap(this.json.readValue(jsonb, Map.class)).toMap();
	}

}
