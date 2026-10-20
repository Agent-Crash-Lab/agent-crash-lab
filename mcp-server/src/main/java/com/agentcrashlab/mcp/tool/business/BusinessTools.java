package com.agentcrashlab.mcp.tool.business;

import java.util.List;
import java.util.Set;

import io.modelcontextprotocol.server.McpServerFeatures.SyncToolSpecification;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import com.agentcrashlab.mcp.auth.AgentKind;
import com.agentcrashlab.mcp.domain.BusinessQueries;
import com.agentcrashlab.mcp.domain.PurchaseOrders;
import com.agentcrashlab.mcp.domain.PurchasePayload;
import com.agentcrashlab.mcp.tool.ToolArgs;
import com.agentcrashlab.mcp.tool.ToolDefinitions;
import com.agentcrashlab.mcp.tool.ToolOutcome;
import com.agentcrashlab.mcp.tool.ToolRunner;
import tools.jackson.databind.json.JsonMapper;

/**
 * business-mcp: 구매 Agent용 도구 4개 (MCP_SPEC 1.3). PURCHASE_AGENT 토큰만 호출할 수 있다.
 */
@Configuration(proxyBeanMethods = false)
class BusinessTools {

	static final String SERVER = "business-mcp";

	private final ToolDefinitions definitions;

	private final ToolRunner runner;

	BusinessTools(JsonMapper json, ToolRunner runner) {
		this.definitions = ToolDefinitions.load(json, "mcp/business-tools.json");
		this.runner = runner;
	}

	/** Spring AI 자동설정은 List&lt;SyncToolSpecification&gt; 빈들을 모아 등록한다 */
	@Bean
	List<SyncToolSpecification> businessToolSpecifications(BusinessQueries queries, PurchaseOrders orders) {
		return List.of(tool("get_inventory", call -> {
			ToolArgs.requireKeys(call.arguments(), Set.of("part_id", "plant_id"));
			return queries.inventory(call.principal().runId(), ToolArgs.text(call.arguments(), "part_id"),
					ToolArgs.text(call.arguments(), "plant_id"));
		}), tool("get_supplier", call -> {
			ToolArgs.requireKeys(call.arguments(), Set.of("supplier_id"));
			return queries.supplier(call.principal().runId(), ToolArgs.text(call.arguments(), "supplier_id"));
		}), tool("create_purchase_order", call -> {
			ToolArgs.requireKeys(call.arguments(), Set.of("request", "approval_id"));
			PurchasePayload request = PurchasePayload.fromMap(call.arguments().get("request"));
			String approvalId = ToolArgs.text(call.arguments(), "approval_id");
			PurchaseOrders.Outcome outcome = orders.create(call.principal().runId(), call.toolCallId(), request,
					approvalId);
			return outcome.replayed() ? new ToolOutcome.Replayed(outcome.result())
					: new ToolOutcome.Committed(outcome.result(), outcome.orderId(), outcome.commitEvidenceId(),
							outcome.eventPayload());
		}), tool("get_order_by_request", call -> {
			ToolArgs.requireKeys(call.arguments(), Set.of("request_id"));
			return queries.ordersByRequest(call.principal().runId(), ToolArgs.text(call.arguments(), "request_id"));
		}));
	}

	private SyncToolSpecification tool(String name, ToolRunner.ToolBody body) {
		return SyncToolSpecification.builder()
			.tool(this.definitions.tool(name))
			.callHandler((exchange, request) -> this.runner.run(exchange, SERVER, AgentKind.PURCHASE_AGENT, request, body))
			.build();
	}

}
