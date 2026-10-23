package com.agentcrashlab.mcp.support;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.simple.JdbcClient;

import com.agentcrashlab.mcp.domain.PurchasePayload;
import com.agentcrashlab.mcp.domain.ReferencePurchaseSimulation;

/** 테스트 데이터 도우미 */
public final class Fixtures {

	private Fixtures() {
	}

	/** purchase-seed.json의 request */
	public static Map<String, Object> seedRequest() {
		Map<String, Object> request = new HashMap<>();
		request.put("request_id", "REQ-001");
		request.put("request_version", 1);
		request.put("part_id", "PART-A");
		request.put("quantity", 100);
		request.put("unit_price_minor", 12000);
		request.put("currency", "KRW");
		request.put("supplier_id", "SUP-01");
		request.put("plant_id", "PLANT-A");
		request.put("purchasing_org_id", "PUR-A");
		return request;
	}

	public static ReferencePurchaseSimulation.Result initRun(ReferencePurchaseSimulation runSetup, String runId, String policy) {
		return runSetup
			.initialize(new ReferencePurchaseSimulation.Command(runId, "S01", policy, "fixture-v1", "requester-01", List.of()));
	}

	/**
	 * 승인 요청과 결정을 DB에 직접 넣는다. 승인 API(3-4)를 거치지 않는 도구 단위 테스트용.
	 */
	public static void insertDecision(JdbcClient jdbc, String runId, String approvalId, String decision,
			boolean authorityValid) {
		PurchasePayload payload = PurchasePayload.fromMap(seedRequest());
		String approvalRequestId = "APR-" + approvalId;
		jdbc.sql("""
				INSERT INTO approval_request (run_id, approval_request_id, request_id, request_version,
				                              payload, payload_hash, status, expires_at)
				VALUES (?, ?, 'REQ-001', 1, ?::jsonb, ?, 'DECIDED', now() + interval '300 seconds')""")
			.params(runId, approvalRequestId, payload.canonicalJson(), payload.hash())
			.update();
		int sequence = jdbc.sql("SELECT count(*) + 1 FROM approval WHERE run_id = ?").param(runId).query(Integer.class).single();
		jdbc.sql("""
				INSERT INTO approval (run_id, approval_id, approval_request_id, request_id, request_version, approver_id,
				                      decision, payload, payload_hash, decision_sequence, authority_valid)
				VALUES (?, ?, ?, 'REQ-001', 1, 'approver-01', ?, ?::jsonb, ?, ?, ?)""")
			.params(runId, approvalId, approvalRequestId, decision, payload.canonicalJson(), payload.hash(), sequence,
					authorityValid)
			.update();
	}

}
