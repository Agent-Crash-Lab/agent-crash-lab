package com.agentcrashlab.mcp.event;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import com.agentcrashlab.mcp.domain.RunIds;
import com.agentcrashlab.mcp.harness.HarnessClient;

/**
 * MCP가 만드는 이벤트 (MCP_SPEC 2장). event_id는 MCP가 발급하고 sequence는 Harness가 발급한다.
 * Harness 전송이 실패해도 업무 처리는 되돌리지 않는다 (4.2). 판정용 원본 근거는 업무 DB에 따로 남아 있다.
 * 트랜잭션이 끝난 뒤(commit 이후)에만 호출한다.
 */
@Component
public class EventPublisher {

	private static final Logger log = LoggerFactory.getLogger(EventPublisher.class);

	private final RunIds ids;

	private final HarnessClient harness;

	EventPublisher(RunIds ids, HarnessClient harness) {
		this.ids = ids;
		this.harness = harness;
	}

	/** drafts event-ui-mapping.json의 node_id */
	public enum Node {

		AGENT("agent"), INVESTIGATOR("investigator"), MCP("mcp"), GUIDE("guide"), DB("db"), FAULT("fault");

		private final String id;

		Node(String id) {
			this.id = id;
		}

	}

	public record Event(String type, String actorId, Node node, String parentEventId, String toolCallId,
			List<String> evidenceIds, Map<String, Object> payload) {
	}

	/** @return 발급한 event_id. 다음 이벤트의 parent_event_id로 쓴다 */
	public String publish(String runId, Event event) {
		String eventId = this.ids.next(runId, RunIds.EVENT);
		// drafts event.schema.json: 12개 필드 모두 필수, 추가 필드 없음 (sequence는 Harness가 붙인다)
		Map<String, Object> body = new LinkedHashMap<>();
		body.put("run_id", runId);
		body.put("event_id", eventId);
		body.put("event_type", event.type());
		body.put("actor_id", event.actorId());
		body.put("node_id", event.node().id);
		body.put("producer", "mcp-server");
		body.put("occurred_at", Instant.now().toString());
		body.put("parent_event_id", event.parentEventId());
		body.put("tool_call_id", event.toolCallId());
		body.put("evidence_ids", event.evidenceIds());
		body.put("payload", event.payload());
		try {
			this.harness.submitEvent(runId, body);
		}
		catch (RuntimeException ex) {
			log.warn("Event {} {} for run {} was not delivered to Harness: {}", eventId, event.type(), runId,
					ex.getMessage());
		}
		return eventId;
	}

}
