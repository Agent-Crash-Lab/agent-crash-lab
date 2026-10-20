package com.agentcrashlab.mcp.tool.rag;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import io.modelcontextprotocol.server.McpServerFeatures.SyncResourceSpecification;
import io.modelcontextprotocol.server.McpServerFeatures.SyncToolSpecification;
import io.modelcontextprotocol.spec.McpError;
import io.modelcontextprotocol.spec.McpSchema.ReadResourceResult;
import io.modelcontextprotocol.spec.McpSchema.Resource;
import io.modelcontextprotocol.spec.McpSchema.TextResourceContents;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.simple.JdbcClient;

import com.agentcrashlab.mcp.auth.AgentKind;
import com.agentcrashlab.mcp.auth.AgentPrincipal;
import com.agentcrashlab.mcp.auth.AgentTokens;
import com.agentcrashlab.mcp.common.ToolErrorCode;
import com.agentcrashlab.mcp.common.ToolException;
import com.agentcrashlab.mcp.domain.GuideLibrary;
import com.agentcrashlab.mcp.domain.RunFinalizer;
import com.agentcrashlab.mcp.event.EventPublisher;
import com.agentcrashlab.mcp.event.EventPublisher.Event;
import com.agentcrashlab.mcp.event.EventPublisher.Node;
import com.agentcrashlab.mcp.harness.HarnessClient;
import com.agentcrashlab.mcp.tool.ToolArgs;
import com.agentcrashlab.mcp.tool.ToolDefinitions;
import com.agentcrashlab.mcp.tool.ToolRunner;
import com.agentcrashlab.mcp.tool.ToolRunner.ToolCall;
import tools.jackson.databind.json.JsonMapper;

/**
 * rag-mcp: 사고 조사 Agent용 읽기 전용 도구 4개와 지침 원문 Resource (MCP_SPEC 1.4).
 * INVESTIGATION_AGENT 토큰만 호출할 수 있고, run_id 인자는 토큰에 묶인 조사 대상 실행과 같아야 한다.
 */
@Configuration(proxyBeanMethods = false)
class RagTools {

	static final String SERVER = "rag-mcp";

	static final int GUIDE_RESULTS = 3;

	private final ToolDefinitions definitions;

	private final ToolRunner runner;

	private final EventPublisher events;

	RagTools(JsonMapper json, ToolRunner runner, EventPublisher events) {
		this.definitions = ToolDefinitions.load(json, "mcp/rag-tools.json");
		this.runner = runner;
		this.events = events;
	}

	@Bean
	List<SyncToolSpecification> ragToolSpecifications(HarnessClient harness, RunFinalizer finalizer,
			GuideLibrary guides, JdbcClient jdbc, JsonMapper json) {
		return List.of(tool("get_failed_checks", call -> {
			String runId = targetRun(call);
			List<Map<String, Object>> checks = fromHarness(() -> harness.failedChecks(runId));
			Map<String, Object> result = new LinkedHashMap<>();
			result.put("run_id", runId);
			result.put("checks", checks);
			evidenceFetched(call, "get_failed_checks", evidenceIds(checks, "evidence_ids"));
			return result;
		}), tool("get_run_trace", call -> {
			String runId = targetRun(call);
			List<Map<String, Object>> runEvents = fromHarness(() -> harness.runEvents(runId));
			Map<String, Object> result = new LinkedHashMap<>();
			result.put("run_id", runId);
			result.put("events", runEvents);
			result.put("tool_calls", toolCalls(jdbc, json, runId));
			evidenceFetched(call, "get_run_trace", evidenceIds(runEvents, "evidence_ids"));
			return result;
		}), tool("get_business_state", call -> {
			String runId = targetRun(call);
			Map<String, Object> state = finalizer.currentState(runId);
			List<String> ids = new ArrayList<>(strings(state.get("snapshot_evidence_ids")));
			ids.addAll(strings(state.get("commit_evidence_ids")));
			evidenceFetched(call, "get_business_state", ids);
			return state;
		}), tool("search_failure_guides", call -> {
			ToolArgs.requireKeys(call.arguments(), Set.of("query"));
			String query = ToolArgs.text(call.arguments(), "query");
			List<Map<String, Object>> results = guides.search(query, GUIDE_RESULTS);
			List<Map<String, Object>> documents = results.stream()
				.map(r -> Map.<String, Object>of("document_id", r.get("document_id"), "version", r.get("version")))
				.toList();
			this.events.publish(call.principal().runId(), new Event("GUIDE_RETRIEVED", "investigation_agent",
					Node.GUIDE, call.calledEventId(), call.toolCallId(), List.of(),
					Map.of("via", "search_failure_guides", "query", query, "documents", documents)));
			return Map.of("results", results);
		}));
	}

	/** 지침 원문 Resource. guides/index.json의 문서마다 guide://{document_id}/{version} */
	@Bean
	List<SyncResourceSpecification> guideResources(GuideLibrary guides, AgentTokens tokens) {
		return guides.index().stream().map(entry -> {
			String uri = "guide://%s/%s".formatted(entry.documentId(), entry.version());
			Resource resource = Resource.builder(uri, entry.documentId())
				.title(entry.title())
				.mimeType("text/markdown")
				.build();
			return new SyncResourceSpecification(resource, (exchange, request) -> {
				Object authorization = exchange.transportContext().get(ToolRunner.AUTHORIZATION);
				AgentPrincipal principal = tokens.resolve((authorization instanceof String s) ? s : null)
					.filter(p -> p.kind() == AgentKind.INVESTIGATION_AGENT)
					.orElseThrow(() -> McpError.builder(-32003).message("Permission denied.").build());
				GuideLibrary.Guide guide = guides.find(entry.documentId(), entry.version())
					.orElseThrow(() -> McpError.RESOURCE_NOT_FOUND.apply(uri));
				this.events.publish(principal.runId(),
						new Event("GUIDE_RETRIEVED", "investigation_agent", Node.GUIDE, null, null, List.of(),
								Map.of("via", "resources/read", "documents",
										List.of(Map.of("document_id", guide.documentId(), "version", guide.version())))));
				return ReadResourceResult
					.builder(List.of(TextResourceContents.builder(uri, guide.body()).mimeType("text/markdown").build()))
					.build();
			});
		}).toList();
	}

	/** run_id 인자는 토큰에 묶인 조사 대상 실행이어야 한다 */
	private static String targetRun(ToolCall call) {
		ToolArgs.requireKeys(call.arguments(), Set.of("run_id"));
		String runId = ToolArgs.text(call.arguments(), "run_id");
		if (!runId.equals(call.principal().runId())) {
			throw new ToolException(ToolErrorCode.PERMISSION_DENIED);
		}
		return runId;
	}

	private void evidenceFetched(ToolCall call, String tool, List<String> evidenceIds) {
		List<String> ids = List.copyOf(new LinkedHashSet<>(evidenceIds));
		this.events.publish(call.principal().runId(),
				new Event("EVIDENCE_FETCHED", "investigation_agent", Node.INVESTIGATOR, call.calledEventId(),
						call.toolCallId(), ids, Map.of("tool", tool, "target_run_id", call.principal().runId(),
								"returned_evidence_ids", ids)));
	}

	/** Harness 조회가 실패하면 재시도 가능한 INTERNAL_ERROR로 알린다 */
	private static <T> T fromHarness(java.util.function.Supplier<T> query) {
		try {
			return query.get();
		}
		catch (RuntimeException ex) {
			throw new ToolException(ToolErrorCode.INTERNAL_ERROR);
		}
	}

	/** MCP_SPEC 1.4 tool_calls[] 항목 */
	private static List<Map<String, Object>> toolCalls(JdbcClient jdbc, JsonMapper json, String runId) {
		return jdbc.sql("""
				SELECT tool_call_id, tool, arguments::text AS arguments, started_at, finished_at, is_error, error_code
				FROM tool_call WHERE run_id = ? ORDER BY started_at, tool_call_id""")
			.param(runId)
			.query((rs, row) -> {
				Map<String, Object> call = new LinkedHashMap<>();
				call.put("tool_call_id", rs.getString("tool_call_id"));
				call.put("tool", rs.getString("tool"));
				call.put("arguments", json.readValue(rs.getString("arguments"), Map.class));
				call.put("started_at", rs.getTimestamp("started_at").toInstant().toString());
				var finished = rs.getTimestamp("finished_at");
				call.put("finished_at", (finished != null) ? finished.toInstant().toString() : null);
				call.put("is_error", rs.getObject("is_error"));
				call.put("error_code", rs.getString("error_code"));
				return call;
			})
			.list();
	}

	private static List<String> evidenceIds(List<Map<String, Object>> items, String field) {
		List<String> ids = new ArrayList<>();
		items.forEach(item -> ids.addAll(strings(item.get(field))));
		return ids;
	}

	private static List<String> strings(Object value) {
		return (value instanceof List<?> list) ? list.stream().map(String::valueOf).toList() : List.of();
	}

	private SyncToolSpecification tool(String name, ToolRunner.ToolBody body) {
		return SyncToolSpecification.builder()
			.tool(this.definitions.tool(name))
			.callHandler(
					(exchange, request) -> this.runner.run(exchange, SERVER, AgentKind.INVESTIGATION_AGENT, request, body))
			.build();
	}

}
