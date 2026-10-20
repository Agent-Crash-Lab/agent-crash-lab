package com.agentcrashlab.mcp.event;

import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.DisposableBean;
import org.springframework.stereotype.Component;

import com.agentcrashlab.mcp.domain.RunIds;
import com.agentcrashlab.mcp.harness.HarnessClient;

/**
 * MCP가 만드는 이벤트 (MCP_SPEC 2장). event_id는 MCP가 발급하고 sequence는 Harness가 발급한다.
 * <p>
 * Harness 전송은 비동기다. publish()는 대기열에 넣고 바로 돌아오고, 전송 전용 스레드 하나가 넣은 순서대로 보낸다.
 * 그래서 Harness가 느려도 도구 응답 시간(10초 제한)에 영향을 주지 않고, 발생 순서도 그대로 유지된다.
 * 전송이 실패해도 업무 처리는 되돌리지 않는다 (4.2). 판정용 원본 근거는 업무 DB에 따로 남아 있다.
 * 트랜잭션이 끝난 뒤(commit 이후)에만 호출한다.
 */
@Component
public class EventPublisher implements DisposableBean {

	private static final Logger log = LoggerFactory.getLogger(EventPublisher.class);

	/** 대기열 상한. Harness가 오래 내려가 있어도 메모리를 다 쓰지 않게 한다. 넘치면 버리고 경고를 남긴다 */
	static final int QUEUE_CAPACITY = 10_000;

	private static final Duration SHUTDOWN_DRAIN = Duration.ofSeconds(5);

	private final RunIds ids;

	private final HarnessClient harness;

	private final BlockingQueue<Delivery> queue = new LinkedBlockingQueue<>(QUEUE_CAPACITY);

	/** 대기열에 있거나 전송 중인 이벤트 수 */
	private final AtomicInteger undelivered = new AtomicInteger();

	private final Thread sender;

	private volatile boolean running = true;

	EventPublisher(RunIds ids, HarnessClient harness) {
		this.ids = ids;
		this.harness = harness;
		this.sender = Thread.ofPlatform().daemon().name("event-sender").start(this::sendLoop);
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

	private record Delivery(String runId, Map<String, Object> body) {
	}

	/** @return 발급한 event_id. 다음 이벤트의 parent_event_id로 쓴다. 전송 완료를 기다리지 않는다 */
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

		this.undelivered.incrementAndGet();
		if (!this.queue.offer(new Delivery(runId, body))) {
			this.undelivered.decrementAndGet();
			log.warn("Event queue is full; event {} {} for run {} was dropped", eventId, event.type(), runId);
		}
		return eventId;
	}

	/**
	 * 대기 중인 이벤트가 모두 전송될 때까지 기다린다 (실패한 전송도 '처리됨'으로 센다).
	 * @return 시간 안에 모두 처리됐으면 true
	 */
	public boolean awaitDelivered(Duration timeout) {
		long deadline = System.nanoTime() + timeout.toNanos();
		while (this.undelivered.get() > 0) {
			if (System.nanoTime() >= deadline) {
				return false;
			}
			try {
				Thread.sleep(10);
			}
			catch (InterruptedException ex) {
				Thread.currentThread().interrupt();
				return false;
			}
		}
		return true;
	}

	private void sendLoop() {
		while (this.running || !this.queue.isEmpty()) {
			Delivery delivery;
			try {
				delivery = this.queue.poll(200, TimeUnit.MILLISECONDS);
			}
			catch (InterruptedException ex) {
				if (!this.running) {
					return;
				}
				continue;
			}
			if (delivery == null) {
				continue;
			}
			try {
				this.harness.submitEvent(delivery.runId(), delivery.body());
			}
			catch (RuntimeException ex) {
				log.warn("Event {} {} for run {} was not delivered to Harness: {}", delivery.body().get("event_id"),
						delivery.body().get("event_type"), delivery.runId(), ex.getMessage());
			}
			finally {
				this.undelivered.decrementAndGet();
			}
		}
	}

	/** 종료 시 남은 이벤트를 잠깐 보내 본 뒤 전송 스레드를 멈춘다 */
	@Override
	public void destroy() {
		if (!awaitDelivered(SHUTDOWN_DRAIN)) {
			log.warn("{} events were not delivered before shutdown", this.undelivered.get());
		}
		this.running = false;
		this.sender.interrupt();
	}

}
