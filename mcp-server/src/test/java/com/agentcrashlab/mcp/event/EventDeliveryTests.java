package com.agentcrashlab.mcp.event;

import static com.agentcrashlab.mcp.support.Fixtures.initRun;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;

import java.time.Duration;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.TestPropertySource;

import com.agentcrashlab.mcp.domain.ReferencePurchaseSimulation;
import com.agentcrashlab.mcp.support.McpTestClient;
import com.agentcrashlab.mcp.support.PostgresIntegrationTest;

/**
 * 이벤트 전송은 도구 응답 시간에 영향을 주지 않는다 (MCP_SPEC 4.2).
 * 리뷰 재현 조건: 도구 제한 200ms, 이벤트 전송마다 600ms 지연.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = "crashlab.tool-timeout=200ms")
class EventDeliveryTests extends PostgresIntegrationTest {

	static final Duration SLOW_HARNESS = Duration.ofMillis(600);

	@LocalServerPort
	int port;

	@Autowired
	ReferencePurchaseSimulation runSetup;

	@Test
	void slowHarnessDoesNotDelayToolResponse() {
		String token = initRun(this.runSetup, "RUN-E1", "baseline-v1").agentTokens().get("purchase_agent");
		doAnswer(invocation -> {
			Thread.sleep(SLOW_HARNESS);
			return null;
		}).when(this.harness).submitEvent(eq("RUN-E1"), any());

		try (McpTestClient agent = new McpTestClient(this.port, token)) {
			long started = System.nanoTime();
			var result = agent.call("get_inventory", Map.of("part_id", "PART-A", "plant_id", "PLANT-A"));
			long elapsedMs = (System.nanoTime() - started) / 1_000_000;

			assertThat(result.isError()).isFalse();
			assertThat(elapsedMs).as("응답이 이벤트 전송(600ms x 2)을 기다리지 않는다").isLessThan(SLOW_HARNESS.toMillis());
		}

		// 전송은 뒤에서 순서대로 끝난다
		List<Map<String, Object>> events = deliveredEvents("RUN-E1");
		assertThat(events.stream().map(e -> e.get("event_type"))).containsExactly("TOOL_CALLED", "TOOL_RESPONDED");
		assertThat(events.get(1)).containsEntry("parent_event_id", events.get(0).get("event_id"));
	}

	@Test
	void eventsKeepTheOrderTheyWerePublished() {
		String token = initRun(this.runSetup, "RUN-E2", "baseline-v1").agentTokens().get("purchase_agent");
		try (McpTestClient agent = new McpTestClient(this.port, token)) {
			for (int i = 0; i < 5; i++) {
				agent.call("get_supplier", Map.of("supplier_id", "SUP-01"));
			}
		}
		List<String> ids = deliveredEvents("RUN-E2").stream().map(e -> (String) e.get("event_id")).toList();
		assertThat(ids).hasSize(10).isSorted(); // EVT-001, EVT-002 … 발급 순서 = 전송 순서
	}

}
