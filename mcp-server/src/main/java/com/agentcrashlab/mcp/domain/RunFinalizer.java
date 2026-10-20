package com.agentcrashlab.mcp.domain;

import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

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

	/**
	 * 확정 시점의 관측 결과를 snapshot 근거(EV-SNAPSHOT-*)에 저장하고, 이후로는 저장된 내용만 돌려준다.
	 * 같은 snapshot 근거 ID는 언제 조회해도 같은 내용이어야 판정 시점과 조사 시점의 데이터가 일치한다.
	 */
	public Map<String, Object> finalizeRun(String runId, long waitMs) {
		this.jdbc.sql("SELECT count(*) FROM run_context WHERE run_id = ?")
			.param(runId)
			.query(Integer.class)
			.optional()
			.filter(count -> count > 0)
			.orElseThrow(() -> ApiException.notFound("Run not found: " + runId));
		Optional<Map<String, Object>> frozen = frozenSnapshot(runId);
		if (frozen.isPresent()) {
			return frozen.get();
		}

		// 1. 구매 Agent 토큰 폐기: 이후 도착하는 변경 요청은 PERMISSION_DENIED
		this.tokens.revoke(runId, AgentKind.PURCHASE_AGENT);

		// 2. 진행 중인 도구 호출이 끝날 때까지 기다린다
		int pending = waitForInFlightCalls(runId, Math.clamp(waitMs, 0, MAX_WAIT_MS));
		boolean snapshotComplete = (pending == 0);

		// 3·4. 확정 기록, 도달하지 않은 사고 규칙 정리, snapshot 저장을 한 트랜잭션에서 한 번만 수행한다.
		// run_context 행을 먼저 갱신(행 잠금)하므로, 동시에 들어온 승인 처리와 순서가 정해진다 (Approvals 참고).
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
			String snapshotId = this.ids.next(runId, RunIds.SNAPSHOT_EVIDENCE);
			Map<String, Object> observation = this.observations.observe(runId, snapshotComplete, pending);
			observation.put("snapshot_evidence_ids", List.of(snapshotId));
			Map<String, Object> refs = new LinkedHashMap<>();
			refs.put("pending_tool_calls", pending);
			refs.put("observation", observation);
			this.jdbc.sql("INSERT INTO evidence (run_id, evidence_id, kind, refs) VALUES (?, ?, 'BUSINESS_SNAPSHOT', ?::jsonb)")
				.params(runId, snapshotId, this.json.writeValueAsString(refs))
				.update();
		});

		return frozenSnapshot(runId).orElseThrow();
	}

	/**
	 * 조사용 상태 (get_business_state). 확정됐으면 저장된 snapshot, 아니면 snapshot_complete=false인 현재 상태.
	 */
	public Map<String, Object> currentState(String runId) {
		Optional<Map<String, Object>> frozen = frozenSnapshot(runId);
		if (frozen.isPresent()) {
			return frozen.get();
		}
		int pending = this.jdbc.sql("SELECT count(*) FROM tool_call WHERE run_id = ? AND status = 'IN_FLIGHT'")
			.param(runId)
			.query(Integer.class)
			.single();
		return this.observations.observe(runId, false, pending);
	}

	/** finalize 때 저장한 관측 결과. 확정 전이면 empty */
	@SuppressWarnings("unchecked")
	private Optional<Map<String, Object>> frozenSnapshot(String runId) {
		return this.jdbc.sql("""
				SELECT refs -> 'observation' FROM evidence
				WHERE run_id = ? AND kind = 'BUSINESS_SNAPSHOT' AND refs -> 'observation' IS NOT NULL
				ORDER BY created_at LIMIT 1""")
			.param(runId)
			.query(String.class)
			.optional()
			.map(observation -> (Map<String, Object>) this.json.readValue(observation, LinkedHashMap.class));
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
