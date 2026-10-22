package com.agentcrashlab.mcp.domain;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

import com.agentcrashlab.mcp.common.ToolErrorCode;
import com.agentcrashlab.mcp.common.ToolException;
import tools.jackson.databind.json.JsonMapper;

/**
 * 구매 도구의 읽기 쿼리 (MCP_SPEC 1.3). 항상 토큰의 run_id 안에서만 조회한다.
 */
@Component
public class BusinessQueries {

	private final JdbcClient jdbc;

	private final JsonMapper json;

	BusinessQueries(JdbcClient jdbc, JsonMapper json) {
		this.jdbc = jdbc;
		this.json = json;
	}

	public Map<String, Object> inventory(String runId, String partId, String plantId) {
		return this.jdbc.sql("""
				SELECT part_id, plant_id, available_quantity, unit, inventory_version FROM inventory
				WHERE run_id = ? AND part_id = ? AND plant_id = ?""")
			.params(runId, partId, plantId)
			.query((rs, row) -> {
				Map<String, Object> result = new LinkedHashMap<>();
				result.put("part_id", rs.getString("part_id"));
				result.put("plant_id", rs.getString("plant_id"));
				result.put("available_quantity", rs.getInt("available_quantity"));
				result.put("unit", rs.getString("unit"));
				result.put("inventory_version", rs.getInt("inventory_version"));
				return result;
			})
			.optional()
			.orElseThrow(() -> new ToolException(ToolErrorCode.VALIDATION_ERROR));
	}

	public Map<String, Object> supplier(String runId, String supplierId) {
		return this.jdbc.sql("""
				SELECT supplier_id, status, unit_price_minor, currency, supplier_version FROM supplier
				WHERE run_id = ? AND supplier_id = ?""")
			.params(runId, supplierId)
			.query((rs, row) -> {
				Map<String, Object> result = new LinkedHashMap<>();
				result.put("supplier_id", rs.getString("supplier_id"));
				result.put("status", rs.getString("status"));
				result.put("unit_price_minor", rs.getInt("unit_price_minor"));
				result.put("currency", rs.getString("currency"));
				result.put("supplier_version", rs.getInt("supplier_version"));
				return result;
			})
			.optional()
			.orElseThrow(() -> new ToolException(ToolErrorCode.VALIDATION_ERROR));
	}

	/** An active supplier still needs approval for this exact business scope. */
	public Map<String, Object> eligibility(String runId, String partId, String supplierId,
			String plantId, String purchasingOrgId) {
		var rows = this.jdbc.sql("""
				SELECT allowed, policy_version FROM approved_supply_source
				WHERE run_id=? AND part_id=? AND supplier_id=? AND plant_id=? AND purchasing_org_id=?""")
			.params(runId, partId, supplierId, plantId, purchasingOrgId)
			.query((rs, row) -> Map.<String, Object>of("allowed", rs.getBoolean("allowed"),
				"policy_version", rs.getInt("policy_version"))).list();
		Map<String, Object> result = new LinkedHashMap<>();
		result.put("part_id", partId); result.put("supplier_id", supplierId);
		result.put("plant_id", plantId); result.put("purchasing_org_id", purchasingOrgId);
		result.put("policy_found", !rows.isEmpty());
		result.put("allowed", !rows.isEmpty() && Boolean.TRUE.equals(rows.getFirst().get("allowed")));
		result.put("policy_version", rows.isEmpty() ? 0 : rows.getFirst().get("policy_version"));
		return result;
	}

	/** 해당 요청의 발주를 모두 반환한다. 중복을 숨기지 않는다 */
	public Map<String, Object> ordersByRequest(String runId, String requestId) {
		List<Map<String, Object>> orders = this.jdbc.sql("""
				SELECT order_id, request_id, approval_id, payload::text AS payload, status, committed_at
				FROM purchase_order WHERE run_id = ? AND request_id = ? ORDER BY commit_sequence""")
			.params(runId, requestId)
			.query((rs, row) -> {
				Map<String, Object> order = new LinkedHashMap<>();
				order.put("order_id", rs.getString("order_id"));
				order.put("request_id", rs.getString("request_id"));
				order.put("approval_id", rs.getString("approval_id"));
				order.put("payload", PurchasePayload.fromMap(this.json.readValue(rs.getString("payload"), Map.class)).toMap());
				order.put("status", rs.getString("status"));
				order.put("committed_at", rs.getTimestamp("committed_at").toInstant().toString());
				return order;
			})
			.list();
		Map<String, Object> result = new LinkedHashMap<>();
		result.put("request_id", requestId);
		result.put("orders", orders);
		return result;
	}

}
