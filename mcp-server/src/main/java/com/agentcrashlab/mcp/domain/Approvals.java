package com.agentcrashlab.mcp.domain;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import com.agentcrashlab.mcp.auth.CurrentUser;
import com.agentcrashlab.mcp.common.ApiException;
import com.agentcrashlab.mcp.common.CrashLabProperties;
import com.agentcrashlab.mcp.event.EventPublisher;
import com.agentcrashlab.mcp.event.EventPublisher.Event;
import com.agentcrashlab.mcp.event.EventPublisher.Node;
import tools.jackson.databind.json.JsonMapper;

/**
 * 승인 요청 등록(MCP_SPEC 3.2)과 승인·거절 결정(1.8, 5.3).
 * 이벤트는 commit 이후에 남기므로 트랜잭션 범위를 TransactionTemplate으로 직접 정한다.
 */
@Service
public class Approvals {

	private final JdbcClient jdbc;

	private final RunIds ids;

	private final JsonMapper json;

	private final CrashLabProperties properties;

	private final TransactionTemplate transaction;

	private final EventPublisher events;

	Approvals(JdbcClient jdbc, RunIds ids, JsonMapper json, CrashLabProperties properties,
			TransactionTemplate transaction, EventPublisher events) {
		this.jdbc = jdbc;
		this.ids = ids;
		this.json = json;
		this.properties = properties;
		this.transaction = transaction;
		this.events = events;
	}

	public record PendingApproval(String approvalRequestId, String requestId, String payloadHash, Instant requestedAt,
			Instant expiresAt) {
	}

	/** 결정 결과. Harness 재개 요청(4.1) 본문과 같다 */
	public record Decision(String approvalId, String requestId, String decision, String approverId, Instant decidedAt,
			String payloadHash) {
	}

	record ApprovalRequestRow(String requestId, int requestVersion, String payload, String payloadHash, String status,
			Instant expiresAt, String requiredEventId) {
	}

	private record Decided(Decision decision, boolean authorityValid, String requiredEventId) {
	}

	/** 승인자에게 보여줄 payload를 서버에 고정한다. 등록된 요청과 다르면 400, 대기 중인 요청이 있으면 409 */
	public PendingApproval register(String runId, PurchasePayload request) {
		PendingApproval pending = this.transaction.execute(status -> insertPending(runId, request));

		Map<String, Object> payload = new LinkedHashMap<>();
		payload.put("approval_request_id", pending.approvalRequestId());
		payload.put("request_id", pending.requestId());
		payload.put("payload", request.toMap());
		payload.put("payload_hash", pending.payloadHash());
		payload.put("expires_at", pending.expiresAt().toString());
		String eventId = this.events.publish(runId,
				new Event("APPROVAL_REQUIRED", "harness_runner", Node.AGENT, null, null, List.of(), payload));
		this.jdbc.sql("UPDATE approval_request SET required_event_id = ? WHERE run_id = ? AND approval_request_id = ?")
			.params(eventId, runId, pending.approvalRequestId())
			.update();
		return pending;
	}

	private PendingApproval insertPending(String runId, PurchasePayload request) {
		requireRun(runId);
		String registeredHash = this.jdbc.sql("""
				SELECT payload_hash FROM purchase_request
				WHERE run_id = ? AND request_id = ? ORDER BY request_version DESC LIMIT 1""")
			.params(runId, request.requestId())
			.query(String.class)
			.optional()
			.orElse(null);
		if (!request.hash().equals(registeredHash)) {
			throw ApiException.badRequest("REQUEST_PAYLOAD_MISMATCH", "Request does not match the registered request");
		}

		// 만료된 대기 건은 정리하고 새로 받는다
		this.jdbc.sql("""
				UPDATE approval_request SET status = 'EXPIRED'
				WHERE run_id = ? AND request_id = ? AND status = 'PENDING' AND expires_at <= now()""")
			.params(runId, request.requestId())
			.update();

		String approvalRequestId = this.ids.next(runId, RunIds.APPROVAL_REQUEST);
		Instant requestedAt = Instant.now();
		Instant expiresAt = requestedAt.plus(this.properties.approvalWait());
		try {
			this.jdbc.sql("""
					INSERT INTO approval_request (run_id, approval_request_id, request_id, request_version, payload,
					                              payload_hash, requested_at, expires_at)
					VALUES (?, ?, ?, ?, ?::jsonb, ?, ?, ?)""")
				.params(runId, approvalRequestId, request.requestId(), request.requestVersion(), request.canonicalJson(),
						request.hash(), Timestamp.from(requestedAt), Timestamp.from(expiresAt))
				.update();
		}
		catch (DuplicateKeyException ex) {
			throw ApiException.conflict("A pending approval request already exists for " + request.requestId());
		}
		return new PendingApproval(approvalRequestId, request.requestId(), request.hash(), requestedAt, expiresAt);
	}

	/**
	 * 승인·거절을 기록한다. 이미 결정·만료됐거나 화면에 보인 payload_hash가 다르면 409.
	 * 승인자 권한(authority_valid)은 서버가 계산한다: APPROVER이고 요청의 구매조직과 같아야 한다.
	 */
	public Decision decide(String runId, String approvalRequestId, String decision, String payloadHash,
			CurrentUser approver) {
		Decided decided = this.transaction
			.execute(status -> insertDecision(runId, approvalRequestId, decision, payloadHash, approver));

		Decision result = decided.decision();
		Map<String, Object> payload = new LinkedHashMap<>();
		payload.put("approval_id", result.approvalId());
		payload.put("request_id", result.requestId());
		payload.put("decision", result.decision());
		payload.put("approver_id", result.approverId());
		payload.put("authority_valid", decided.authorityValid());
		payload.put("payload_hash", result.payloadHash());
		payload.put("decided_at", result.decidedAt().toString());
		this.events.publish(runId, new Event("APPROVAL_DECIDED", result.approverId(), Node.AGENT,
				decided.requiredEventId(), null, List.of(), payload));
		return result;
	}

	private Decided insertDecision(String runId, String approvalRequestId, String decision, String payloadHash,
			CurrentUser approver) {
		ApprovalRequestRow pending = this.jdbc.sql("""
				SELECT request_id, request_version, payload::text AS payload, payload_hash, status, expires_at,
				       required_event_id
				FROM approval_request WHERE run_id = ? AND approval_request_id = ? FOR UPDATE""")
			.params(runId, approvalRequestId)
			.query(ApprovalRequestRow.class)
			.optional()
			.orElseThrow(() -> ApiException.notFound("Approval request not found"));
		if (!"PENDING".equals(pending.status()) || !pending.expiresAt().isAfter(Instant.now())) {
			throw ApiException.conflict("Approval request is already decided or expired");
		}
		if (!pending.payloadHash().equals(payloadHash)) {
			throw ApiException.conflict("payload_hash does not match the pending approval");
		}

		PurchasePayload payload = PurchasePayload.fromMap(this.json.readValue(pending.payload(), Map.class));
		boolean authorityValid = approver.hasRole(CurrentUser.APPROVER)
				&& Objects.equals(approver.purchasingOrgId(), payload.purchasingOrgId());
		String approvalId = this.ids.next(runId, RunIds.APPROVAL);
		int decisionSequence = this.ids.sequence(runId, RunIds.DECISION_SEQUENCE);
		Instant decidedAt = this.jdbc.sql("""
				INSERT INTO approval (run_id, approval_id, approval_request_id, request_id, request_version, approver_id,
				                      decision, payload, payload_hash, decision_sequence, authority_valid)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?)
				RETURNING decided_at""")
			.params(runId, approvalId, approvalRequestId, pending.requestId(), pending.requestVersion(),
					approver.userId(), decision, payload.canonicalJson(), pending.payloadHash(), decisionSequence,
					authorityValid)
			.query(Timestamp.class)
			.single()
			.toInstant();
		this.jdbc.sql("UPDATE approval_request SET status = 'DECIDED' WHERE run_id = ? AND approval_request_id = ?")
			.params(runId, approvalRequestId)
			.update();
		return new Decided(new Decision(approvalId, pending.requestId(), decision, approver.userId(), decidedAt,
				pending.payloadHash()), authorityValid, pending.requiredEventId());
	}

	private void requireRun(String runId) {
		boolean exists = this.jdbc.sql("SELECT count(*) > 0 FROM run_context WHERE run_id = ?")
			.param(runId)
			.query(Boolean.class)
			.single();
		if (!exists) {
			throw ApiException.notFound("Run not found: " + runId);
		}
	}

}
