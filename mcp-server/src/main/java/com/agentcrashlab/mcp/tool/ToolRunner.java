package com.agentcrashlab.mcp.tool;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import io.modelcontextprotocol.server.McpSyncServerExchange;
import io.modelcontextprotocol.spec.McpSchema.CallToolRequest;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

import com.agentcrashlab.mcp.auth.AgentKind;
import com.agentcrashlab.mcp.auth.AgentPrincipal;
import com.agentcrashlab.mcp.auth.AgentTokens;
import com.agentcrashlab.mcp.common.CrashLabProperties;
import com.agentcrashlab.mcp.common.ToolErrorCode;
import com.agentcrashlab.mcp.common.ToolException;
import com.agentcrashlab.mcp.domain.RunIds;
import com.agentcrashlab.mcp.event.EventPublisher;
import com.agentcrashlab.mcp.event.EventPublisher.Event;
import com.agentcrashlab.mcp.event.EventPublisher.Node;
import com.agentcrashlab.mcp.fault.FaultInjector;
import tools.jackson.databind.json.JsonMapper;

/**
 * 모든 MCP 도구 호출의 공통 처리.
 * <ol>
 * <li>Agent 토큰으로 실행과 Agent 종류를 정한다 (MCP_SPEC 1.1)</li>
 * <li>호출을 tool_call에 IN_FLIGHT로 먼저 기록하고 TOOL_CALLED 이벤트를 남긴다. 차단된 호출도 남긴다 (1.6, 2.2)</li>
 * <li>본문이 commit을 알리면 BUSINESS_COMMITTED를 남기고 사고 주입 규칙을 확인한다 (3.5)</li>
 * <li>10초 안에 끝나지 않으면 TOOL_TIMEOUT을 돌려준다. 작업은 끝까지 진행되고 끝나면 COMPLETED가 된다 (1.5)</li>
 * <li>응답을 MCP_SPEC 1.2 형식으로 만들고 TOOL_RESPONDED를 남긴다</li>
 * </ol>
 */
@Component
public class ToolRunner {

	/** McpTransportContext에 담는 Authorization 헤더 키 */
	public static final String AUTHORIZATION = "authorization";

	private static final Logger log = LoggerFactory.getLogger(ToolRunner.class);

	private final AgentTokens tokens;

	private final RunIds ids;

	private final JdbcClient jdbc;

	private final JsonMapper json;

	private final EventPublisher events;

	private final FaultInjector faults;

	private final ExecutorService executor;

	private final long timeoutMillis;

	ToolRunner(AgentTokens tokens, RunIds ids, JdbcClient jdbc, JsonMapper json, EventPublisher events,
			FaultInjector faults, ExecutorService toolExecutor, CrashLabProperties properties) {
		this.tokens = tokens;
		this.ids = ids;
		this.jdbc = jdbc;
		this.json = json;
		this.events = events;
		this.faults = faults;
		this.executor = toolExecutor;
		this.timeoutMillis = properties.toolTimeout().toMillis();
	}

	/** 도구 본문. 결과는 snake_case로 직렬화된다. 업무 변경이면 ToolOutcome을 돌려준다 */
	@FunctionalInterface
	public interface ToolBody {

		Object call(ToolCall call);

	}

	/** 도구 본문이 받는 호출 정보. calledEventId는 본문이 남기는 이벤트의 parent로 쓴다 */
	public record ToolCall(AgentPrincipal principal, String toolCallId, String calledEventId,
			Map<String, Object> arguments) {
	}

	/** 작업 결과와 Agent 응답에 드러나지 않는 표시 */
	private record Completed(Object result, boolean replayed) {
	}

	public CallToolResult run(McpSyncServerExchange exchange, String server, AgentKind allowed, CallToolRequest request,
			ToolBody body) {
		long startedAt = System.nanoTime();
		Object authorization = exchange.transportContext().get(AUTHORIZATION);
		AgentPrincipal principal = this.tokens.resolve((authorization instanceof String s) ? s : null).orElse(null);
		if (principal == null) {
			return error(ToolErrorCode.PERMISSION_DENIED);
		}
		String runId = principal.runId();
		String tool = request.name();
		Map<String, Object> arguments = (request.arguments() != null) ? request.arguments() : Map.of();
		String toolCallId = this.ids.next(runId, RunIds.TOOL_CALL);
		this.jdbc.sql("""
				INSERT INTO tool_call (run_id, tool_call_id, agent_kind, server, tool, arguments)
				VALUES (?, ?, ?, ?, ?, ?::jsonb)""")
			.params(runId, toolCallId, principal.kind().name(), server, tool, this.json.writeValueAsString(arguments))
			.update();
		String calledEventId = this.events.publish(runId,
				new Event("TOOL_CALLED", principal.kind().name().toLowerCase(), Node.MCP, null, toolCallId, List.of(),
						Map.of("server", server, "tool", tool, "arguments", arguments, "agent_kind",
								principal.kind().name())));
		Responder responder = new Responder(runId, server, tool, toolCallId, calledEventId, startedAt);

		if (principal.kind() != allowed) {
			finish(runId, toolCallId, ToolErrorCode.PERMISSION_DENIED);
			return responder.error(ToolErrorCode.PERMISSION_DENIED, false);
		}

		ToolCall call = new ToolCall(principal, toolCallId, calledEventId, arguments);
		Future<Completed> task = this.executor.submit(() -> {
			try {
				Completed completed = execute(call, tool, calledEventId, body);
				finish(runId, toolCallId, null);
				return completed;
			}
			catch (ToolException ex) {
				finish(runId, toolCallId, ex.code());
				throw ex;
			}
			catch (RuntimeException ex) {
				log.error("Tool {} failed (run {}, call {})", tool, runId, toolCallId, ex);
				finish(runId, toolCallId, ToolErrorCode.INTERNAL_ERROR);
				throw new ToolException(ToolErrorCode.INTERNAL_ERROR);
			}
		});

		try {
			Completed completed = task.get(this.timeoutMillis, TimeUnit.MILLISECONDS);
			return responder.success(completed.result(), completed.replayed());
		}
		catch (TimeoutException ex) {
			// 응답은 지금 돌려주고, 작업은 계속 진행된다. 끝나면 status만 COMPLETED로 바뀐다.
			respond(runId, toolCallId, ToolErrorCode.TOOL_TIMEOUT);
			return responder.error(ToolErrorCode.TOOL_TIMEOUT, false);
		}
		catch (ExecutionException ex) {
			Throwable cause = ex.getCause();
			ToolErrorCode code = (cause instanceof ToolException toolEx) ? toolEx.code() : ToolErrorCode.INTERNAL_ERROR;
			return responder.error(code, cause instanceof FaultInjector.InjectedFault);
		}
		catch (InterruptedException ex) {
			Thread.currentThread().interrupt();
			respond(runId, toolCallId, ToolErrorCode.INTERNAL_ERROR);
			return responder.error(ToolErrorCode.INTERNAL_ERROR, false);
		}
	}

	/** 본문 실행. commit이면 근거 이벤트를 남기고 사고 규칙을 확인한다 (사고면 InjectedFault) */
	private Completed execute(ToolCall call, String tool, String calledEventId, ToolBody body) {
		Object result = body.call(call);
		String runId = call.principal().runId();
		if (result instanceof ToolOutcome.Committed committed) {
			String committedEventId = this.events.publish(runId,
					new Event("BUSINESS_COMMITTED", "business_server", Node.DB, calledEventId, call.toolCallId(),
							List.of(committed.commitEvidenceId()), committed.eventPayload()));
			this.faults.afterCommit(runId, tool, call.toolCallId(), committedEventId, committed.objectId(),
					committed.commitEvidenceId());
			return new Completed(committed.result(), false);
		}
		if (result instanceof ToolOutcome.Replayed replayed) {
			this.jdbc.sql("UPDATE tool_call SET idempotent_replay = true WHERE run_id = ? AND tool_call_id = ?")
				.params(runId, call.toolCallId())
				.update();
			return new Completed(replayed.result(), true);
		}
		return new Completed(result, false);
	}

	/** Agent 응답을 만들고 TOOL_RESPONDED 이벤트를 남긴다 */
	private final class Responder {

		private final String runId;

		private final String server;

		private final String tool;

		private final String toolCallId;

		private final String calledEventId;

		private final long startedAt;

		Responder(String runId, String server, String tool, String toolCallId, String calledEventId, long startedAt) {
			this.runId = runId;
			this.server = server;
			this.tool = tool;
			this.toolCallId = toolCallId;
			this.calledEventId = calledEventId;
			this.startedAt = startedAt;
		}

		CallToolResult success(Object result, boolean replayed) {
			responded(null, replayed, false);
			return ToolRunner.this.success(result);
		}

		CallToolResult error(ToolErrorCode code, boolean faultInjected) {
			responded(code, false, faultInjected);
			return ToolRunner.this.error(code);
		}

		private void responded(ToolErrorCode code, boolean replayed, boolean faultInjected) {
			Map<String, Object> payload = new LinkedHashMap<>();
			payload.put("server", this.server);
			payload.put("tool", this.tool);
			payload.put("is_error", code != null);
			payload.put("error_code", (code != null) ? code.name() : null);
			payload.put("idempotent_replay", replayed);
			payload.put("fault_injected", faultInjected);
			payload.put("duration_ms", (System.nanoTime() - this.startedAt) / 1_000_000);
			ToolRunner.this.events.publish(this.runId,
					new Event("TOOL_RESPONDED", "mcp_server", Node.MCP, this.calledEventId, this.toolCallId, List.of(),
							payload));
		}

	}

	/** Agent가 받은 결과를 기록한다. 먼저 기록된 응답(예: TOOL_TIMEOUT)이 있으면 덮어쓰지 않는다 */
	private void respond(String runId, String toolCallId, ToolErrorCode code) {
		this.jdbc.sql("""
				UPDATE tool_call SET is_error = ?, error_code = ?
				WHERE run_id = ? AND tool_call_id = ? AND is_error IS NULL""")
			.params(code != null, (code != null) ? code.name() : null, runId, toolCallId)
			.update();
	}

	/** 작업이 끝났음을 기록한다. finalize는 이 상태로 진행 중 호출 수를 센다 */
	private void finish(String runId, String toolCallId, ToolErrorCode code) {
		respond(runId, toolCallId, code);
		this.jdbc.sql("UPDATE tool_call SET status = 'COMPLETED', finished_at = now() WHERE run_id = ? AND tool_call_id = ?")
			.params(runId, toolCallId)
			.update();
	}

	@SuppressWarnings("unchecked")
	private CallToolResult success(Object result) {
		Map<String, Object> structured = this.json.convertValue(result, LinkedHashMap.class);
		return CallToolResult.builder()
			.addTextContent(this.json.writeValueAsString(structured))
			.structuredContent(structured)
			.isError(false)
			.build();
	}

	private CallToolResult error(ToolErrorCode code) {
		Map<String, Object> error = new LinkedHashMap<>();
		error.put("code", code.name());
		error.put("message", code.defaultMessage());
		error.put("retryable", code.retryable());
		return CallToolResult.builder()
			.addTextContent(this.json.writeValueAsString(Map.of("error", error)))
			.isError(true)
			.build();
	}

}
