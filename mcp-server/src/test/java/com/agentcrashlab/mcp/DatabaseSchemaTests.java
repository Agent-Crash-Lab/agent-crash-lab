package com.agentcrashlab.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.sql.Connection;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.web.servlet.assertj.MockMvcTester;
import org.springframework.transaction.annotation.Transactional;

import com.agentcrashlab.mcp.support.PostgresIntegrationTest;

/**
 * 2단계 검증: Flyway V1이 mcp_app으로 적용되고, oracle_ro 권한이 의도대로인지 확인한다.
 */
@AutoConfigureMockMvc
class DatabaseSchemaTests extends PostgresIntegrationTest {

	/** Oracle이 읽어야 하는 업무 테이블 */
	static final List<String> BUSINESS_TABLES = List.of("run_context", "id_counter", "part", "inventory", "supplier",
			"approved_supply_source", "purchase_request", "approval_request", "approval", "purchase_order",
			"idempotency_record", "tool_call", "fault_rule", "evidence", "guide_document");

	/** Oracle이 읽으면 안 되는 테이블 */
	static final List<String> SECRET_TABLES = List.of("app_user", "agent_token", "user_session");

	@Autowired
	JdbcClient jdbc;

	@Autowired
	MockMvcTester mvc;

	@Test
	void migrationCreatesAllTablesOwnedByMcpApp() {
		List<String> owners = jdbc
			.sql("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'sandbox'")
			.query(String.class)
			.list();
		List<String> tables = jdbc.sql("SELECT tablename FROM pg_tables WHERE schemaname = 'sandbox'")
			.query(String.class)
			.list();

		assertThat(owners).containsExactly("mcp_app");
		assertThat(tables).containsAll(BUSINESS_TABLES).containsAll(SECRET_TABLES).contains("flyway_schema_history");
	}

	@Test
	void healthIsUpWithDatabase() {
		assertThat(mvc.get().uri("/health")).hasStatusOk().bodyJson().extractingPath("$.status").isEqualTo("UP");
	}

	@Test
	void oracleCanReadBusinessTables() throws SQLException {
		try (Connection oracle = connectAsOracle(); Statement statement = oracle.createStatement()) {
			for (String table : BUSINESS_TABLES) {
				statement.executeQuery("SELECT count(*) FROM " + table).close();
			}
		}
	}

	@Test
	void oracleCannotReadSecretTables() throws SQLException {
		try (Connection oracle = connectAsOracle(); Statement statement = oracle.createStatement()) {
			for (String table : SECRET_TABLES) {
				assertThatThrownBy(() -> statement.executeQuery("SELECT count(*) FROM " + table))
					.isInstanceOf(SQLException.class)
					.extracting(e -> ((SQLException) e).getSQLState())
					.isEqualTo("42501"); // insufficient_privilege
			}
		}
	}

	@Test
	void oracleCannotWrite() throws SQLException {
		try (Connection oracle = connectAsOracle(); Statement statement = oracle.createStatement()) {
			assertThatThrownBy(() -> statement.executeUpdate(
					"INSERT INTO run_context (run_id, scenario_id, server_policy_version, fixture_id, requested_by) "
							+ "VALUES ('RUN-X', 'S01', 'baseline-v1', 'fixture-v1', 'requester-01')"))
				.isInstanceOf(SQLException.class)
				.extracting(e -> ((SQLException) e).getSQLState())
				.isIn("42501", "25006"); // 권한 없음 또는 읽기 전용 트랜잭션
		}
	}

	@Test
	@Transactional
	void sameRequestCanHaveTwoOrdersForB0() {
		insertApprovedRequest("RUN-T1");
		insertOrder("RUN-T1", "PO-001", 1);
		insertOrder("RUN-T1", "PO-002", 2);

		Integer orders = jdbc.sql("SELECT count(*) FROM purchase_order WHERE run_id = 'RUN-T1' AND request_id = 'REQ-001'")
			.query(Integer.class)
			.single();
		assertThat(orders).isEqualTo(2);
	}

	@Test
	@Transactional
	void onlyOnePendingApprovalRequestPerRequest() {
		insertApprovedRequest("RUN-T2");
		insertApprovalRequest("RUN-T2", "APR-002", "PENDING");

		assertThatThrownBy(() -> insertApprovalRequest("RUN-T2", "APR-003", "PENDING"))
			.isInstanceOf(DataIntegrityViolationException.class);
	}

	@Test
	@Transactional
	void sameIdsCanBeReusedAcrossRuns() {
		insertApprovedRequest("RUN-T3");
		insertApprovedRequest("RUN-T4");
		insertOrder("RUN-T3", "PO-001", 1);
		insertOrder("RUN-T4", "PO-001", 1);

		Integer orders = jdbc.sql("SELECT count(*) FROM purchase_order WHERE order_id = 'PO-001' AND run_id IN ('RUN-T3', 'RUN-T4')")
			.query(Integer.class)
			.single();
		assertThat(orders).isEqualTo(2);
	}

	/** 실행 + 요청 + 결정된 승인 요청(APR-001) + 승인(AP-001) */
	private void insertApprovedRequest(String runId) {
		jdbc.sql("""
				INSERT INTO run_context (run_id, scenario_id, server_policy_version, fixture_id, requested_by)
				VALUES (?, 'S03', 'baseline-v1', 'fixture-v1', 'requester-01')""").param(runId).update();
		jdbc.sql("""
				INSERT INTO purchase_request (run_id, request_id, request_version, payload, payload_hash)
				VALUES (?, 'REQ-001', 1, '{}'::jsonb, repeat('a', 64))""").param(runId).update();
		insertApprovalRequest(runId, "APR-001", "DECIDED");
		jdbc.sql("""
				INSERT INTO approval (run_id, approval_id, approval_request_id, request_id, request_version,
				                      approver_id, decision, payload, payload_hash, decision_sequence, authority_valid)
				VALUES (?, 'AP-001', 'APR-001', 'REQ-001', 1, 'approver-01', 'APPROVED', '{}'::jsonb, repeat('a', 64), 1, true)""")
			.param(runId)
			.update();
	}

	private void insertApprovalRequest(String runId, String approvalRequestId, String status) {
		jdbc.sql("""
				INSERT INTO approval_request (run_id, approval_request_id, request_id, request_version,
				                              payload, payload_hash, status, expires_at)
				VALUES (?, ?, 'REQ-001', 1, '{}'::jsonb, repeat('a', 64), ?, now() + interval '300 seconds')""")
			.params(runId, approvalRequestId, status)
			.update();
	}

	private void insertOrder(String runId, String orderId, int commitSequence) {
		jdbc.sql("""
				INSERT INTO purchase_order (run_id, order_id, request_id, request_version, approval_id,
				                            payload, payload_hash, commit_sequence, tool_call_id, commit_evidence_id)
				VALUES (?, ?, 'REQ-001', 1, 'AP-001', '{}'::jsonb, repeat('a', 64), ?, 'TC-001', 'EV-COMMIT-001')""")
			.params(runId, orderId, commitSequence)
			.update();
	}

}
