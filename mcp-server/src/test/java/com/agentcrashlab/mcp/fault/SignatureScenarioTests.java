package com.agentcrashlab.mcp.fault;

import static com.agentcrashlab.mcp.support.Fixtures.seedRequest;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.verify;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.simple.JdbcClient;

import com.agentcrashlab.mcp.auth.CurrentUser;
import com.agentcrashlab.mcp.domain.Approvals;
import com.agentcrashlab.mcp.domain.PurchasePayload;
import com.agentcrashlab.mcp.domain.RunFinalizer;
import com.agentcrashlab.mcp.domain.RunSetup;
import com.agentcrashlab.mcp.support.McpTestClient;
import com.agentcrashlab.mcp.support.McpTestClient.Result;
import com.agentcrashlab.mcp.support.PostgresIntegrationTest;
import tools.jackson.databind.json.JsonMapper;

/**
 * S03 저장 후 응답 유실 (MCP_SPEC 3.5), B0/B1 서버 정책 (1.7), 이벤트 (2장).
 * Agent 재시도는 참조 Agent 정책대로 같은 request·approval_id로 1회 한다.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class SignatureScenarioTests extends PostgresIntegrationTest {

	static final CurrentUser APPROVER = new CurrentUser("approver-01", List.of("APPROVER"), "PUR-A");

	@LocalServerPort
	int port;

	@Autowired
	RunSetup runSetup;

	@Autowired
	Approvals approvals;

	@Autowired
	RunFinalizer finalizer;

	@Autowired
	FaultRules faultRules;

	@Autowired
	JdbcClient jdbc;

	@Autowired
	JsonMapper json;

	@Test
	void s03BaselineRetryCreatesDuplicateOrder() {
		String token = initS03("RUN-F1", "baseline-v1");
		String approvalId = approve("RUN-F1", "APPROVED");

		try (McpTestClient agent = new McpTestClient(this.port, token)) {
			Result first = create(agent, approvalId);
			assertThat(first.error()).containsEntry("code", "TOOL_TIMEOUT")
				.containsEntry("retryable", true)
				.containsEntry("message", "The operation timed out before a response was received.");
			assertThat(orderIds("RUN-F1")).as("응답은 유실됐지만 저장은 됐다").containsExactly("PO-001");

			Result retry = create(agent, approvalId);
			assertThat(retry.text()).containsEntry("order_id", "PO-002");
		}

		assertThat(orderIds("RUN-F1")).as("B0: 재시도가 중복 발주를 만든다").containsExactly("PO-001", "PO-002");
		assertThat(this.faultRules.statuses("RUN-F1")).singleElement().satisfies(fault -> assertThat(fault)
			.containsEntry("status", "APPLIED")
			.containsEntry("applied_count", 1)
			.containsEntry("related_order_id", "PO-001")
			.containsEntry("evidence_id", "EV-FAULT-001"));
		assertThat(jdbc.sql("""
				SELECT fault_injected FROM tool_call WHERE run_id = 'RUN-F1' AND tool = 'create_purchase_order'
				ORDER BY started_at""").query(Boolean.class).list()).containsExactly(true, false);

		Map<String, Object> observation = this.finalizer.finalizeRun("RUN-F1", 1000);
		assertThat(observation).containsEntry("commit_evidence_ids", List.of("EV-COMMIT-001", "EV-COMMIT-002"));

		// 이벤트: commit → 사고 → 응답 순서와 parent 연결
		List<Map<String, Object>> events = events("RUN-F1");
		Map<String, Object> firstCommit = first(events, "BUSINESS_COMMITTED");
		Map<String, Object> fault = first(events, "FAULT_INJECTED");
		assertThat(fault).containsEntry("parent_event_id", firstCommit.get("event_id"))
			.containsEntry("node_id", "fault")
			.containsEntry("evidence_ids", List.of("EV-FAULT-001"));
		assertThat(firstCommit).containsEntry("evidence_ids", List.of("EV-COMMIT-001")).containsEntry("node_id", "db");
		assertThat(payload(firstCommit)).containsEntry("order_id", "PO-001")
			.containsEntry("server_policy_version", "baseline-v1")
			.containsKeys("request_id", "approval_id", "committed_at");
		assertThat(types(events).indexOf("FAULT_INJECTED")).isGreaterThan(types(events).indexOf("BUSINESS_COMMITTED"));
		Map<String, Object> faultResponse = events.stream()
			.filter(e -> "TOOL_RESPONDED".equals(e.get("event_type")) && Boolean.TRUE.equals(payload(e).get("fault_injected")))
			.findFirst()
			.orElseThrow();
		assertThat(payload(faultResponse)).containsEntry("error_code", "TOOL_TIMEOUT");
		assertThat(types(events).stream().filter("BUSINESS_COMMITTED"::equals)).hasSize(2);
	}

	@Test
	void s03IdempotentRetryReturnsTheSameOrder() {
		String token = initS03("RUN-F2", "idempotent-v1");
		String approvalId = approve("RUN-F2", "APPROVED");

		try (McpTestClient agent = new McpTestClient(this.port, token)) {
			assertThat(create(agent, approvalId).error()).containsEntry("code", "TOOL_TIMEOUT");
			Result retry = create(agent, approvalId);
			assertThat(retry.isError()).isFalse();
			assertThat(retry.text()).containsEntry("order_id", "PO-001")
				.containsEntry("status", "CREATED")
				.containsEntry("committed_version", 1);
		}

		assertThat(orderIds("RUN-F2")).as("B1: 재시도해도 발주는 1건").containsExactly("PO-001");
		assertThat(jdbc.sql("SELECT idempotent_replay FROM tool_call WHERE run_id = 'RUN-F2' AND tool = 'create_purchase_order' ORDER BY started_at")
			.query(Boolean.class)
			.list()).containsExactly(false, true);

		List<Map<String, Object>> events = events("RUN-F2");
		assertThat(types(events).stream().filter("BUSINESS_COMMITTED"::equals)).as("재사용 응답은 새 commit이 아니다").hasSize(1);
		assertThat(events.stream()
			.filter(e -> "TOOL_RESPONDED".equals(e.get("event_type")))
			.anyMatch(e -> Boolean.TRUE.equals(payload(e).get("idempotent_replay")))).isTrue();
	}

	@Test
	void blockedCallsDoNotTriggerTheFault() {
		String token = initS03("RUN-F3", "baseline-v1");
		String approvalId = approve("RUN-F3", "APPROVED");

		try (McpTestClient agent = new McpTestClient(this.port, token)) {
			Map<String, Object> wrong = new java.util.HashMap<>(seedRequest());
			wrong.put("quantity", 80);
			assertThat(agent.call("create_purchase_order", Map.of("request", wrong, "approval_id", approvalId)).error())
				.containsEntry("code", "REQUEST_PAYLOAD_MISMATCH");
			assertThat(this.faultRules.statuses("RUN-F3").get(0)).as("검증 실패는 성공 commit이 아니다")
				.containsEntry("status", "PLANNED");

			assertThat(create(agent, approvalId).error()).containsEntry("code", "TOOL_TIMEOUT");
		}
		assertThat(this.faultRules.statuses("RUN-F3").get(0)).containsEntry("status", "APPLIED");
	}

	@Test
	void unreachedFaultBecomesNotReachedAtFinalize() {
		String token = initS03("RUN-F4", "baseline-v1");
		String approvalId = approve("RUN-F4", "REJECTED");
		try (McpTestClient agent = new McpTestClient(this.port, token)) {
			assertThat(create(agent, approvalId).error()).containsEntry("code", "APPROVAL_REJECTED");
		}
		this.finalizer.finalizeRun("RUN-F4", 0);
		assertThat(this.faultRules.statuses("RUN-F4").get(0)).containsEntry("status", "NOT_REACHED")
			.containsEntry("applied_count", 0);
	}

	@Test
	void approvalEventsAreLinked() {
		initS03("RUN-F5", "baseline-v1");
		approve("RUN-F5", "APPROVED");

		List<Map<String, Object>> events = events("RUN-F5");
		Map<String, Object> required = first(events, "APPROVAL_REQUIRED");
		Map<String, Object> decided = first(events, "APPROVAL_DECIDED");
		assertThat(payload(required)).containsEntry("approval_request_id", "APR-001")
			.containsEntry("payload_hash", PurchasePayload.fromMap(seedRequest()).hash());
		assertThat(decided).containsEntry("parent_event_id", required.get("event_id")).containsEntry("node_id", "agent");
		assertThat(payload(decided)).containsEntry("decision", "APPROVED").containsEntry("authority_valid", true);
	}

	@Test
	@SuppressWarnings("unchecked")
	void everyEventMatchesTheDraftEventSchema() throws IOException {
		String token = initS03("RUN-F6", "baseline-v1");
		String approvalId = approve("RUN-F6", "APPROVED");
		try (McpTestClient agent = new McpTestClient(this.port, token)) {
			create(agent, approvalId);
			create(agent, approvalId);
		}

		Map<String, Object> schema = this.json.readValue(
				Files.readString(Path.of("../contracts/drafts/manufacturing-qa/event.schema.json")), Map.class);
		Set<String> fields = new java.util.HashSet<>(((Map<String, Object>) schema.get("properties")).keySet());
		fields.remove("sequence"); // Harness가 저장할 때 붙인다 (4.2)
		List<String> nodes = (List<String>) ((Map<String, Object>) ((Map<String, Object>) schema.get("properties"))
			.get("node_id")).get("enum");

		List<Map<String, Object>> events = events("RUN-F6");
		assertThat(events).isNotEmpty();
		for (Map<String, Object> event : events) {
			assertThat(event.keySet()).as(event.get("event_type").toString()).isEqualTo(fields);
			assertThat(nodes).contains((String) event.get("node_id"));
			assertThat(event).containsEntry("producer", "mcp-server").containsEntry("run_id", "RUN-F6");
		}
		assertThat(events.stream().map(e -> e.get("event_id")).distinct()).hasSameSizeAs(events);
	}

	private String initS03(String runId, String policy) {
		RunSetup.FaultRule fault = new RunSetup.FaultRule("FLT-001", "create_purchase_order",
				"AFTER_FIRST_SUCCESSFUL_COMMIT_BEFORE_RESPONSE", 1, "TOOL_TIMEOUT");
		return this.runSetup
			.initialize(new RunSetup.Command(runId, "S03", policy, "fixture-v1", "requester-01", List.of(fault)))
			.agentTokens()
			.get("purchase_agent");
	}

	private String approve(String runId, String decision) {
		Approvals.PendingApproval pending = this.approvals.register(runId, PurchasePayload.fromMap(seedRequest()));
		return this.approvals.decide(runId, pending.approvalRequestId(), decision, pending.payloadHash(), APPROVER)
			.approvalId();
	}

	private static Result create(McpTestClient agent, String approvalId) {
		return agent.call("create_purchase_order", Map.of("request", seedRequest(), "approval_id", approvalId));
	}

	private List<String> orderIds(String runId) {
		return jdbc.sql("SELECT order_id FROM purchase_order WHERE run_id = ? ORDER BY commit_sequence")
			.param(runId)
			.query(String.class)
			.list();
	}

	@SuppressWarnings({ "unchecked", "rawtypes" })
	private List<Map<String, Object>> events(String runId) {
		ArgumentCaptor<Map> captor = ArgumentCaptor.forClass(Map.class);
		verify(this.harness, atLeastOnce()).submitEvent(eq(runId), captor.capture());
		return (List) captor.getAllValues();
	}

	private static List<String> types(List<Map<String, Object>> events) {
		return events.stream().map(e -> (String) e.get("event_type")).toList();
	}

	private static Map<String, Object> first(List<Map<String, Object>> events, String type) {
		return events.stream().filter(e -> type.equals(e.get("event_type"))).findFirst().orElseThrow();
	}

	@SuppressWarnings("unchecked")
	private static Map<String, Object> payload(Map<String, Object> event) {
		return (Map<String, Object>) event.get("payload");
	}

}
