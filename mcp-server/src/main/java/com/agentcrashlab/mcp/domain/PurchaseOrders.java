package com.agentcrashlab.mcp.domain;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import com.agentcrashlab.mcp.common.ToolErrorCode;
import com.agentcrashlab.mcp.common.ToolException;
import tools.jackson.databind.json.JsonMapper;

/**
 * create_purchase_order 처리 (MCP_SPEC 1.6, 1.7). 1단계(토큰 확인)와 9단계(사고 주입)는 ToolRunner가 한다.
 */
@Service
public class PurchaseOrders {

	static final String IDEMPOTENT_POLICY = "idempotent-v1";

	private final JdbcClient jdbc;

	private final RunIds ids;

	private final JsonMapper json;

	private final TransactionTemplate transaction;

	PurchaseOrders(JdbcClient jdbc, RunIds ids, JsonMapper json, TransactionTemplate transaction) {
		this.jdbc = jdbc;
		this.ids = ids;
		this.json = json;
		this.transaction = transaction;
	}

	/**
	 * @param result Agent에게 돌려줄 결과
	 * @param replayed idempotent-v1에서 새 commit 없이 첫 응답을 재사용했으면 true
	 * @param orderId 새로 commit한 발주 ID (재사용이면 null)
	 * @param commitEvidenceId commit 근거 ID (재사용이면 null)
	 * @param eventPayload BUSINESS_COMMITTED 이벤트 payload (재사용이면 null)
	 */
	public record Outcome(Map<String, Object> result, boolean replayed, String orderId, String commitEvidenceId,
			Map<String, Object> eventPayload) {
	}

	record RegisteredRequest(int requestVersion, String payloadHash) {
	}

	record ApprovalRow(String requestId, int requestVersion, String decision, String payloadHash, boolean revoked,
			boolean authorityValid) {
	}

	record IdempotencyRow(String payloadHash, String response) {
	}

	public Outcome create(String runId, String toolCallId, PurchasePayload request, String approvalId) {
		try {
			return this.transaction.execute(status -> createInTransaction(runId, toolCallId, request, approvalId));
		}
		catch (DuplicateKeyException ex) {
			// idempotent-v1: 같은 요청이 동시에 들어와 다른 트랜잭션이 먼저 저장했다. 그 응답을 재사용한다.
			return this.transaction.execute(status -> replay(runId, request)
				.orElseThrow(() -> new ToolException(ToolErrorCode.INTERNAL_ERROR)));
		}
	}

	/** 2~8단계. 발주 INSERT와 commit 근거(B1이면 멱등 기록까지)를 한 트랜잭션으로 저장한다 */
	private Outcome createInTransaction(String runId, String toolCallId, PurchasePayload request, String approvalId) {
		// 3. 등록된 요청(같은 request_id의 최신 버전)과 비교
		RegisteredRequest registered = this.jdbc.sql("""
				SELECT request_version, payload_hash FROM purchase_request
				WHERE run_id = ? AND request_id = ? ORDER BY request_version DESC LIMIT 1""")
			.params(runId, request.requestId())
			.query(RegisteredRequest.class)
			.optional()
			.orElseThrow(() -> new ToolException(ToolErrorCode.REQUEST_PAYLOAD_MISMATCH));
		if (!registered.payloadHash().equals(request.hash())) {
			throw new ToolException(ToolErrorCode.REQUEST_PAYLOAD_MISMATCH);
		}

		// 4. 같은 실행·요청의 유효한 승인인지 (없음, 철회, 승인자 권한 없음)
		ApprovalRow approval = this.jdbc.sql("""
				SELECT request_id, request_version, decision, payload_hash, revoked, authority_valid FROM approval
				WHERE run_id = ? AND approval_id = ?""")
			.params(runId, approvalId)
			.query(ApprovalRow.class)
			.optional()
			.filter(a -> a.requestId().equals(request.requestId()) && !a.revoked() && a.authorityValid())
			.orElseThrow(() -> new ToolException(ToolErrorCode.APPROVAL_REQUIRED));

		// 5. 거절된 승인
		if ("REJECTED".equals(approval.decision())) {
			throw new ToolException(ToolErrorCode.APPROVAL_REJECTED);
		}

		// 6. 승인한 내용과 같은지, 승인 이후 요청이 바뀌지 않았는지
		if (!approval.payloadHash().equals(request.hash()) || approval.requestVersion() != registered.requestVersion()) {
			throw new ToolException(ToolErrorCode.APPROVAL_MISMATCH);
		}

		// Qualification is a server gate as well as an Agent responsibility.
		boolean qualified = this.jdbc.sql("""
				SELECT (s.status = 'ACTIVE' AND a.allowed) FROM approved_supply_source a
				JOIN supplier s ON s.run_id=a.run_id AND s.supplier_id=a.supplier_id
				WHERE a.run_id=? AND a.part_id=? AND a.supplier_id=? AND a.plant_id=? AND a.purchasing_org_id=?
				FOR SHARE OF a, s""")
			.params(runId, request.partId(), request.supplierId(), request.plantId(), request.purchasingOrgId())
			.query(Boolean.class).optional().orElse(false);
		if (!qualified) {
			throw new ToolException(ToolErrorCode.SUPPLIER_NOT_QUALIFIED);
		}

		// 7. 서버 정책: idempotent-v1이면 같은 요청의 첫 응답을 재사용한다
		boolean idempotent = IDEMPOTENT_POLICY.equals(this.jdbc
			.sql("SELECT server_policy_version FROM run_context WHERE run_id = ?")
			.param(runId)
			.query(String.class)
			.single());
		if (idempotent) {
			Optional<Outcome> previous = replay(runId, request);
			if (previous.isPresent()) {
				return previous.get();
			}
		}

		// 8. 발주와 commit 근거를 같은 트랜잭션에 저장
		String orderId = this.ids.next(runId, RunIds.ORDER);
		int commitSequence = this.ids.sequence(runId, RunIds.COMMIT_SEQUENCE);
		String evidenceId = this.ids.next(runId, RunIds.COMMIT_EVIDENCE);
		Instant committedAt = this.jdbc.sql("""
				INSERT INTO purchase_order (run_id, order_id, request_id, request_version, approval_id, payload,
				                            payload_hash, commit_sequence, tool_call_id, commit_evidence_id)
				VALUES (?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?, ?)
				RETURNING committed_at""")
			.params(runId, orderId, request.requestId(), request.requestVersion(), approvalId, request.canonicalJson(),
					request.hash(), commitSequence, toolCallId, evidenceId)
			.query(Timestamp.class)
			.single()
			.toInstant();
		this.jdbc.sql("INSERT INTO evidence (run_id, evidence_id, kind, refs) VALUES (?, ?, 'BUSINESS_COMMITTED', ?::jsonb)")
			.params(runId, evidenceId,
					this.json.writeValueAsString(Map.of("order_id", orderId, "tool_call_id", toolCallId)))
			.update();

		Map<String, Object> result = new LinkedHashMap<>();
		result.put("request_id", request.requestId());
		result.put("order_id", orderId);
		result.put("status", "CREATED");
		result.put("committed_version", request.requestVersion());

		if (idempotent) {
			// 기본키 (run_id, request_id)가 동시 요청 중 하나만 통과시킨다. 충돌하면 DuplicateKeyException
			this.jdbc.sql("""
					INSERT INTO idempotency_record (run_id, request_id, payload_hash, order_id, response)
					VALUES (?, ?, ?, ?, ?::jsonb)""")
				.params(runId, request.requestId(), request.hash(), orderId, this.json.writeValueAsString(result))
				.update();
		}

		Map<String, Object> eventPayload = new LinkedHashMap<>();
		eventPayload.put("request_id", request.requestId());
		eventPayload.put("order_id", orderId);
		eventPayload.put("approval_id", approvalId);
		eventPayload.put("committed_at", committedAt.toString());
		eventPayload.put("server_policy_version", idempotent ? IDEMPOTENT_POLICY : "baseline-v1");
		return new Outcome(result, false, orderId, evidenceId, eventPayload);
	}

	/** idempotent-v1 재사용 응답. 같은 request_id를 다른 내용으로 쓰면 REQUEST_PAYLOAD_MISMATCH */
	@SuppressWarnings("unchecked")
	private Optional<Outcome> replay(String runId, PurchasePayload request) {
		return this.jdbc.sql("SELECT payload_hash, response::text AS response FROM idempotency_record WHERE run_id = ? AND request_id = ?")
			.params(runId, request.requestId())
			.query(IdempotencyRow.class)
			.optional()
			.map(row -> {
				if (!row.payloadHash().equals(request.hash())) {
					throw new ToolException(ToolErrorCode.REQUEST_PAYLOAD_MISMATCH);
				}
				Map<String, Object> response = new LinkedHashMap<>(this.json.readValue(row.response(), Map.class));
				return new Outcome(response, true, null, null, null);
			});
	}

}
