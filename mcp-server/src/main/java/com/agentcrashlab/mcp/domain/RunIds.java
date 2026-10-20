package com.agentcrashlab.mcp.domain;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

/**
 * 실행 안에서 순번을 발급한다 (id_counter). 호출한 트랜잭션에 참여하므로 롤백되면 순번도 돌아간다.
 */
@Component
public class RunIds {

	public static final String APPROVAL_REQUEST = "APR";

	public static final String APPROVAL = "AP";

	public static final String ORDER = "PO";

	public static final String TOOL_CALL = "TC";

	public static final String COMMIT_EVIDENCE = "EV-COMMIT";

	public static final String SNAPSHOT_EVIDENCE = "EV-SNAPSHOT";

	public static final String FAULT_EVIDENCE = "EV-FAULT";

	public static final String EVENT = "EVT";

	public static final String DECISION_SEQUENCE = "DECISION";

	public static final String COMMIT_SEQUENCE = "COMMIT";

	private final JdbcClient jdbc;

	RunIds(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	/** 예: next("RUN-001", "PO") → "PO-001" */
	public String next(String runId, String prefix) {
		return "%s-%03d".formatted(prefix, sequence(runId, prefix));
	}

	public int sequence(String runId, String kind) {
		return this.jdbc.sql("""
				INSERT INTO id_counter (run_id, kind, last_value) VALUES (?, ?, 1)
				ON CONFLICT (run_id, kind) DO UPDATE SET last_value = id_counter.last_value + 1
				RETURNING last_value""").params(runId, kind).query(Integer.class).single();
	}

}
