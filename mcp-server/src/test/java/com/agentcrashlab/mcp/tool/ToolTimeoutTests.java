package com.agentcrashlab.mcp.tool;

import static com.agentcrashlab.mcp.support.Fixtures.initRun;
import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import java.util.List;
import java.util.Map;

import io.modelcontextprotocol.server.McpServerFeatures.SyncToolSpecification;
import io.modelcontextprotocol.spec.McpSchema.Tool;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.TestPropertySource;

import com.agentcrashlab.mcp.auth.AgentKind;
import com.agentcrashlab.mcp.domain.RunFinalizer;
import com.agentcrashlab.mcp.domain.ReferencePurchaseSimulation;
import com.agentcrashlab.mcp.support.McpTestClient;
import com.agentcrashlab.mcp.support.PostgresIntegrationTest;

/**
 * MCP_SPEC 1.5: 상한을 넘기면 TOOL_TIMEOUT을 먼저 돌려주고 작업은 끝까지 진행된다.
 * 3.4: finalize는 진행 중 호출이 끝날 때까지 기다린다. 상한은 테스트를 위해 200ms로 줄인다.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = "crashlab.tool-timeout=200ms")
class ToolTimeoutTests extends PostgresIntegrationTest {

	static final Duration WORK = Duration.ofMillis(1500);

	@LocalServerPort
	int port;

	@Autowired
	ReferencePurchaseSimulation runSetup;

	@Autowired
	RunFinalizer finalizer;

	@Autowired
	JdbcClient jdbc;

	@TestConfiguration
	static class SlowToolConfig {

		/** 테스트 전용: WORK만큼 걸리는 도구 */
		@Bean
		List<SyncToolSpecification> slowTool(ToolRunner runner) {
			Tool tool = Tool.builder("slow_tool", Map.of("type", "object")).description("test only").build();
			return List.of(SyncToolSpecification.builder()
				.tool(tool)
				.callHandler((exchange, request) -> runner.run(exchange, "business-mcp", AgentKind.PURCHASE_AGENT,
						request, call -> {
							sleep(WORK);
							return Map.of("done", true);
						}))
				.build());
		}

	}

	@Test
	void slowCallReturnsToolTimeoutAndCompletesLater() {
		String token = initRun(this.runSetup, "RUN-T1", "baseline-v1").agentTokens().get("purchase_agent");
		try (McpTestClient agent = new McpTestClient(this.port, token)) {
			var result = agent.call("slow_tool", Map.of());
			assertThat(result.error()).containsEntry("code", "TOOL_TIMEOUT")
				.containsEntry("retryable", true)
				.containsEntry("message", "The operation timed out before a response was received.");
		}
		assertThat(status("RUN-T1")).isEqualTo("IN_FLIGHT");

		// finalize는 작업이 끝날 때까지 기다린 뒤 확정한다
		Map<String, Object> observation = this.finalizer.finalizeRun("RUN-T1", 5000);
		assertThat(observation).containsEntry("snapshot_complete", true).containsEntry("pending_tool_calls", 0);
		assertThat(status("RUN-T1")).isEqualTo("COMPLETED");
		assertThat(jdbc.sql("SELECT error_code FROM tool_call WHERE run_id = 'RUN-T1'").query(String.class).single())
			.as("Agent가 받은 응답이 기록에 남는다")
			.isEqualTo("TOOL_TIMEOUT");
	}

	@Test
	void finalizeReportsUnsettledWhenCallsAreStillRunning() {
		String token = initRun(this.runSetup, "RUN-T2", "baseline-v1").agentTokens().get("purchase_agent");
		try (McpTestClient agent = new McpTestClient(this.port, token)) {
			agent.call("slow_tool", Map.of());
		}
		Map<String, Object> observation = this.finalizer.finalizeRun("RUN-T2", 0);
		assertThat(observation).containsEntry("snapshot_complete", false).containsEntry("pending_tool_calls", 1);
	}

	private String status(String runId) {
		return jdbc.sql("SELECT status FROM tool_call WHERE run_id = ?").param(runId).query(String.class).single();
	}

	private static void sleep(Duration duration) {
		try {
			Thread.sleep(duration);
		}
		catch (InterruptedException ex) {
			Thread.currentThread().interrupt();
		}
	}

}
