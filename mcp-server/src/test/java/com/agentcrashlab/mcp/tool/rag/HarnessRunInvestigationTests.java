package com.agentcrashlab.mcp.tool.rag;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.assertj.MockMvcTester;

import com.agentcrashlab.mcp.domain.KnowledgeSearch;
import com.agentcrashlab.mcp.domain.ReferencePurchaseSimulation;
import com.agentcrashlab.mcp.support.McpTestClient;
import com.agentcrashlab.mcp.support.McpTestClient.Result;
import com.agentcrashlab.mcp.support.PostgresIntegrationTest;
import tools.jackson.databind.json.JsonMapper;

/** 생산·품질 실행 조사 (MCP_SPEC 3.6, 4.4): 업무 상태·도구 호출은 Harness가 원본이다 */
@AutoConfigureMockMvc
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class HarnessRunInvestigationTests extends PostgresIntegrationTest {

	@LocalServerPort
	int port;

	@Autowired
	MockMvcTester mvc;

	@Autowired
	ReferencePurchaseSimulation runSetup;

	@Autowired
	JsonMapper json;

	@MockitoBean
	KnowledgeSearch knowledge;

	private MockMvcTester.MockMvcRequestBuilder register(String runId, String agentType) {
		return this.mvc.post()
			.uri("/internal/investigation-runs")
			.header("X-Internal-Token", INTERNAL_TOKEN)
			.contentType(MediaType.APPLICATION_JSON)
			.content("""
					{"run_id":"%s","agent_type":"%s","scenario_id":"PN01","requested_by":"requester-01"}"""
				.formatted(runId, agentType));
	}

	@SuppressWarnings("unchecked")
	private String investigatorToken(String runId, String agentType) throws Exception {
		var result = register(runId, agentType).exchange();
		assertThat(result).hasStatus(HttpStatus.CREATED);
		Map<String, Object> body = this.json.readValue(result.getResponse().getContentAsString(), Map.class);
		return ((Map<String, String>) body.get("agent_tokens")).get("investigation_agent");
	}

	@Test
	void registrationIsInternalAndKeepsTheBusinessType() {
		assertThat(this.mvc.post()
			.uri("/internal/investigation-runs")
			.contentType(MediaType.APPLICATION_JSON)
			.content("{}")).hasStatus(HttpStatus.UNAUTHORIZED);
		assertThat(register("RUN-H0", "PURCHASE")).as("구매는 기존 초기화 경로만 사용").hasStatus(HttpStatus.BAD_REQUEST);
		assertThat(register("RUN-H0", "PRODUCTION")).hasStatus(HttpStatus.CREATED);
		assertThat(register("RUN-H0", "PRODUCTION")).as("재등록은 토큰 재발급").hasStatus(HttpStatus.CREATED);
		assertThat(register("RUN-H0", "QUALITY")).as("업무 유형 변경 불가").hasStatus(HttpStatus.CONFLICT);
	}

	@Test
	@SuppressWarnings("unchecked")
	void investigatorReadsHarnessStateTraceAndScopedKnowledge() throws Exception {
		String token = investigatorToken("RUN-H1", "PRODUCTION");
		when(this.harness.runEvents("RUN-H1")).thenReturn(List.of());
		when(this.harness.simulationState("RUN-H1")).thenReturn(Map.of("run_id", "RUN-H1", "agent_type", "PRODUCTION",
				"snapshot_complete", true, "snapshot_evidence_ids", List.of("SNAP-RUN-H1"), "changes", List.of(),
				"tool_calls", List.of(Map.of("tool", "assign_operation", "effect", "WRITE", "evidence_ids",
						List.of("EV-CALL-1"), "is_error", false))));
		when(this.knowledge.search(anyString(), anyString(), eq(3)))
			.thenReturn(Map.of("results", List.of(), "index_version", "test-index"));

		try (McpTestClient investigator = new McpTestClient(this.port, token)) {
			Result state = investigator.call("get_business_state", Map.of("run_id", "RUN-H1"));
			assertThat(state.text()).containsEntry("run_id", "RUN-H1")
				.containsEntry("agent_type", "PRODUCTION")
				.containsEntry("snapshot_evidence_ids", List.of("SNAP-RUN-H1"))
				.doesNotContainKey("tool_calls");

			Result trace = investigator.call("get_run_trace", Map.of("run_id", "RUN-H1"));
			List<Map<String, Object>> calls = (List<Map<String, Object>>) trace.text().get("tool_calls");
			assertThat(calls).singleElement().satisfies(c -> assertThat(c).containsEntry("tool", "assign_operation"));

			assertThat(investigator.call("search_manufacturing_knowledge", Map.of("query", "maintenance")).isError())
				.isFalse();
			verify(this.knowledge).search("maintenance", "PRODUCTION", 3);

			assertThat(investigator.call("create_purchase_order", Map.of()).error())
				.as("조사 토큰은 업무 변경 불가").containsEntry("code", "PERMISSION_DENIED");
		}
	}

	@Test
	void purchaseRunKeepsPurchaseKnowledgeScope() {
		String token = this.runSetup
			.initialize(new ReferencePurchaseSimulation.Command("RUN-H2", "S01", "baseline-v1", "fixture-v1",
					"requester-01", List.of()))
			.agentTokens()
			.get("investigation_agent");
		when(this.knowledge.search(anyString(), anyString(), eq(3)))
			.thenReturn(Map.of("results", List.of(), "index_version", "test-index"));
		try (McpTestClient investigator = new McpTestClient(this.port, token)) {
			investigator.call("search_manufacturing_knowledge", Map.of("query", "duplicate"));
		}
		verify(this.knowledge).search("duplicate", "PURCHASE", 3);
	}

}
