package com.agentcrashlab.mcp.domain;

import java.util.List;
import java.util.Map;
import java.util.Set;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.agentcrashlab.mcp.auth.AgentKind;
import com.agentcrashlab.mcp.auth.AgentTokens;
import com.agentcrashlab.mcp.common.ApiException;
import com.agentcrashlab.mcp.common.CrashLabProperties;
import com.agentcrashlab.mcp.common.ToolException;

/**
 * 실행 초기화 (MCP_SPEC 3.1). seed를 run_id로 복제하고, 서버 정책과 사고 규칙을 등록하고, Agent 토큰을 발급한다.
 */
@Service
public class ReferencePurchaseSimulation {

	static final Set<String> POLICIES = Set.of("baseline-v1", "idempotent-v1");

	private final JdbcClient jdbc;

	private final ReferencePurchaseStateLoader fixtures;

	private final AgentTokens tokens;

	private final CrashLabProperties properties;

	ReferencePurchaseSimulation(JdbcClient jdbc, ReferencePurchaseStateLoader fixtures, AgentTokens tokens, CrashLabProperties properties) {
		this.jdbc = jdbc;
		this.fixtures = fixtures;
		this.tokens = tokens;
		this.properties = properties;
	}

	public record FaultRule(String faultId, String toolName, String trigger, int maxAppliedCount,
			String targetErrorCode) {
	}

	public record Command(String runId, String scenarioId, String serverPolicyVersion, String fixtureId,
			String requestedBy, List<FaultRule> faults, Map<String, Object> initialState) {
		public Command(String runId, String scenarioId, String serverPolicyVersion, String fixtureId,
				String requestedBy, List<FaultRule> faults) {
			this(runId, scenarioId, serverPolicyVersion, fixtureId, requestedBy, faults, null);
		}
	}

	public record Result(String runId, String serverPolicyVersion, String mcpUrl, Map<String, String> agentTokens,
			Map<String, Object> request) {
	}

	@Transactional
	public Result initialize(Command command) {
		validate(command);
		ReferencePurchaseStateLoader.Seed seed = this.fixtures.prepared(command.fixtureId(), command.initialState());
		PurchasePayload request = payload(seed.request());
		String runId = command.runId();

		try {
			this.jdbc.sql("""
					INSERT INTO run_context (run_id, scenario_id, server_policy_version, fixture_id, requested_by)
					VALUES (?, ?, ?, ?, ?)""")
				.params(runId, command.scenarioId(), command.serverPolicyVersion(), command.fixtureId(),
						command.requestedBy())
				.update();
		}
		catch (DuplicateKeyException ex) {
			throw ApiException.conflict("Run already exists: " + runId);
		}

		for (ReferencePurchaseStateLoader.Part part : seed.parts()) {
			this.jdbc.sql("INSERT INTO part (run_id, part_id, name, unit) VALUES (?, ?, ?, ?)")
				.params(runId, part.partId(), part.name(), part.unit())
				.update();
			this.jdbc.sql("""
					INSERT INTO inventory (run_id, part_id, plant_id, available_quantity, unit)
					VALUES (?, ?, ?, ?, ?)""")
				.params(runId, part.partId(), part.plantId(), part.inventory(), part.unit())
				.update();
		}
		for (ReferencePurchaseStateLoader.Supplier supplier : seed.suppliers()) {
			this.jdbc.sql("""
					INSERT INTO supplier (run_id, supplier_id, status, unit_price_minor, currency)
					VALUES (?, ?, ?, ?, ?)""")
				.params(runId, supplier.supplierId(), supplier.status(), supplier.unitPriceMinor(), supplier.currency())
				.update();
		}
		for (ReferencePurchaseStateLoader.SupplySource source : seed.approvedSupplySources()) {
			this.jdbc.sql("""
					INSERT INTO approved_supply_source
					    (run_id, part_id, supplier_id, plant_id, purchasing_org_id, allowed, policy_version)
					VALUES (?, ?, ?, ?, ?, ?, ?)""")
				.params(runId, source.partId(), source.supplierId(), source.plantId(), source.purchasingOrgId(),
						source.allowed(), source.policyVersion())
				.update();
		}
		this.jdbc.sql("""
				INSERT INTO purchase_request (run_id, request_id, request_version, payload, payload_hash)
				VALUES (?, ?, ?, ?::jsonb, ?)""")
			.params(runId, request.requestId(), request.requestVersion(), request.canonicalJson(), request.hash())
			.update();
		for (FaultRule fault : command.faults()) {
			this.jdbc.sql("""
					INSERT INTO fault_rule (run_id, fault_id, tool_name, trigger, target_error_code, max_applied_count)
					VALUES (?, ?, ?, ?, ?, ?)""")
				.params(runId, fault.faultId(), fault.toolName(), fault.trigger(), fault.targetErrorCode(),
						fault.maxAppliedCount())
				.update();
		}

		Map<String, String> agentTokens = Map.of("purchase_agent", this.tokens.issue(runId, AgentKind.PURCHASE_AGENT),
				"investigation_agent", this.tokens.issue(runId, AgentKind.INVESTIGATION_AGENT));
		return new Result(runId, command.serverPolicyVersion(), this.properties.mcpUrl(), agentTokens, request.toMap());
	}

	private static void validate(Command command) {
		if (!POLICIES.contains(command.serverPolicyVersion())) {
			throw ApiException.badRequest("VALIDATION_ERROR", "Unknown server_policy_version");
		}
		// MCP_SPEC 3.5: MVP는 create_purchase_order의 첫 성공 commit 후 1회 TOOL_TIMEOUT만 지원
		for (FaultRule fault : command.faults()) {
			if (!"create_purchase_order".equals(fault.toolName())
					|| !"AFTER_FIRST_SUCCESSFUL_COMMIT_BEFORE_RESPONSE".equals(fault.trigger())
					|| !"TOOL_TIMEOUT".equals(fault.targetErrorCode()) || fault.maxAppliedCount() != 1) {
				throw ApiException.badRequest("VALIDATION_ERROR", "Unsupported fault rule: " + fault.faultId());
			}
		}
	}

	private static PurchasePayload payload(Map<String, Object> seedRequest) {
		try {
			return PurchasePayload.fromMap(seedRequest);
		}
		catch (ToolException ex) {
			throw new IllegalStateException("Seed request is not a valid purchase payload", ex);
		}
	}

}
