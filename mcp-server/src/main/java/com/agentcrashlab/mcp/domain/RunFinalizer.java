package com.agentcrashlab.mcp.domain;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import com.agentcrashlab.mcp.auth.AgentKind;
import com.agentcrashlab.mcp.auth.AgentTokens;
import com.agentcrashlab.mcp.common.ApiException;
import tools.jackson.databind.json.JsonMapper;

/**
 * 상태 확정 (MCP_SPEC 3.4). Oracle 판정 직전에 Harness가 호출한다. 여러 번 호출해도 결과가 같다.
 */
@Service
public class RunFinalizer {

	private static final Duration POLL_INTERVAL = Duration.ofMillis(100);

	private static final long MAX_WAIT_MS = 30_000;

	private final JdbcClient jdbc;

	private final AgentTokens tokens;

	private final RunIds ids;

	private final Observations observations;

	private final TransactionTemplate transaction;

	private final JsonMapper json;

	RunFinalizer(JdbcClient jdbc, AgentTokens tokens, RunIds ids, Observations observations,
			TransactionTemplate transaction, JsonMapper json) {
		this.jdbc = jdbc;
		this.tokens = tokens;
		this.ids = ids;
		this.observations = observations;
		this.transaction = transaction;
		this.json = json;
	}

	record Finalized(Boolean snapshotComplete, Integer pendingToolCalls) {
	}

	public Map<String, Object> finalizeRun(String runId, long waitMs) {
		Finalized existing = this.jdbc.sql("SELECT snapshot_complete, pending_tool_calls FROM run_context WHERE run_id = ?")
			.param(runId)
			.query(Finalized.class)
			.optional()
			.orElseThrow(() -> ApiException.notFound("Run not found: " + runId));
		if (existing.snapshotComplete() != null) {
			return this.observations.observe(runId, existing.snapshotComplete(), existing.pendingToolCalls());
		}

		// 1. 구매 Agent 토큰 폐기: 이후 도착하는 변경 요청은 PERMISSION_DENIED
		this.tokens.revoke(runId, AgentKind.PURCHASE_AGENT);

		// 2. 진행 중인 도구 호출이 끝날 때까지 기다린다
		int pending = waitForInFlightCalls(runId, Math.clamp(waitMs, 0, MAX_WAIT_MS));
		boolean snapshotComplete = (pending == 0);

		// 3·4. 확정 기록, 근거, 도달하지 않은 사고 규칙 정리를 한 번만 수행한다
		this.transaction.executeWithoutResult(status -> {
			int updated = this.jdbc.sql("""
					UPDATE run_context SET finalized_at = now(), snapshot_complete = ?, pending_tool_calls = ?
					WHERE run_id = ? AND finalized_at IS NULL""")
				.params(snapshotComplete, pending, runId)
				.update();
			if (updated == 0) {
				return;
			}
			this.jdbc.sql("UPDATE fault_rule SET status = 'NOT_REACHED' WHERE run_id = ? AND status = 'PLANNED'")
				.param(runId)
				.update();
			this.jdbc.sql("INSERT INTO evidence (run_id, evidence_id, kind, refs) VALUES (?, ?, 'BUSINESS_SNAPSHOT', ?::jsonb)")
				.params(runId, this.ids.next(runId, RunIds.SNAPSHOT_EVIDENCE),
						this.json.writeValueAsString(Map.of("pending_tool_calls", pending)))
				.update();
		});

		Finalized stored = this.jdbc.sql("SELECT snapshot_complete, pending_tool_calls FROM run_context WHERE run_id = ?")
			.param(runId)
			.query(Finalized.class)
			.single();
		return this.observations.observe(runId, stored.snapshotComplete(), stored.pendingToolCalls());
	}

	/**
	 * 조사용 현재 상태 (get_business_state). 확정됐으면 확정 결과, 아니면 snapshot_complete=false와 지금 진행 중인 호출 수.
	 */
	public Map<String, Object> currentState(String runId) {
		Finalized stored = this.jdbc.sql("SELECT snapshot_complete, pending_tool_calls FROM run_context WHERE run_id = ?")
			.param(runId)
			.query(Finalized.class)
			.single();
		if (stored.snapshotComplete() != null) {
			return this.observations.observe(runId, stored.snapshotComplete(), stored.pendingToolCalls());
		}
		int pending = this.jdbc.sql("SELECT count(*) FROM tool_call WHERE run_id = ? AND status = 'IN_FLIGHT'")
			.param(runId)
			.query(Integer.class)
			.single();
		return this.observations.observe(runId, false, pending);
	}

	private int waitForInFlightCalls(String runId, long waitMs) {
		Instant deadline = Instant.now().plusMillis(waitMs);
		while (true) {
			int pending = this.jdbc.sql("SELECT count(*) FROM tool_call WHERE run_id = ? AND status = 'IN_FLIGHT'")
				.param(runId)
				.query(Integer.class)
				.single();
			if (pending == 0 || !Instant.now().isBefore(deadline)) {
				return pending;
			}
			try {
				Thread.sleep(POLL_INTERVAL);
			}
			catch (InterruptedException ex) {
				Thread.currentThread().interrupt();
				return pending;
			}
		}
	}

}
