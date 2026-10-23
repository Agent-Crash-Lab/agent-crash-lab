package com.agentcrashlab.mcp.domain;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import org.springframework.stereotype.Component;

import com.agentcrashlab.mcp.common.ApiException;
import com.agentcrashlab.mcp.common.CrashLabProperties;
import tools.jackson.databind.json.JsonMapper;

/**
 * qa/examples/targets/agents.json의 구매 초기 상태를 읽는다. 실행 초기화 때마다 다시 읽는다.
 */
@Component
public class ReferencePurchaseStateLoader {

	static final String SEED_FILE = "examples/targets/agents.json";

	private final JsonMapper json;

	private final Path seedPath;

	ReferencePurchaseStateLoader(JsonMapper json, CrashLabProperties properties) {
		this.json = json;
		this.seedPath = Path.of(properties.qaDir()).resolve(SEED_FILE);
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record SeedFile(String fixtureId, Seed seed) {
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record Seed(List<Part> parts, List<Supplier> suppliers, List<SupplySource> approvedSupplySources,
			Map<String, Object> request, List<User> users) {
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record Part(String partId, String name, String unit, int inventory, String plantId) {
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record Supplier(String supplierId, String status, int unitPriceMinor, String currency) {
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record SupplySource(String partId, String supplierId, String plantId, String purchasingOrgId,
			boolean allowed, int policyVersion) {
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record User(String userId, List<String> roles, String purchasingOrgId) {
	}

	/** fixture_id에 해당하는 seed. 없으면 400 VALIDATION_ERROR */
	public SeedFile load(String fixtureId) {
		SeedFile file = read();
		if (!file.fixtureId().equals(fixtureId)) {
			throw ApiException.badRequest("VALIDATION_ERROR", "Unknown fixture_id: " + fixtureId);
		}
		return file;
	}

	/** QA may vary quantities, prices and the selected qualification flag, never principals or source identities. */
	@SuppressWarnings("unchecked")
	public Seed prepared(String fixtureId, Map<String, Object> initialState) {
		Seed baseline = load(fixtureId).seed();
		if (initialState == null) {
			return baseline;
		}
		try {
			Map<String, Object> actual = this.json.readValue(this.json.writeValueAsString(initialState), Map.class);
			Map<String, Object> expected = (Map<String, Object>) readPurchaseProfile()
				.get("sample_data");
			expected = (Map<String, Object>) expected.get("initial_state");
			PurchasePayload request = PurchasePayload.fromMap(actual.get("request"));
			if (!request.requestId().equals(request.requestId().strip()) || request.requestId().length() > 128) {
				throw new IllegalArgumentException("Invalid request ID");
			}
			Map<String, Object> expectedRequest = (Map<String, Object>) expected.get("request");
			for (String key : List.of("request_id", "request_version", "quantity", "unit_price_minor")) {
				expectedRequest.put(key, request.toMap().get(key));
			}
			for (String collection : List.of("parts", "suppliers")) {
				String field = collection.equals("parts") ? "inventory" : "unit_price_minor";
				List<Map<String, Object>> actualRows = (List<Map<String, Object>>) actual.get(collection);
				List<Map<String, Object>> expectedRows = (List<Map<String, Object>>) expected.get(collection);
				if (actualRows.size() != expectedRows.size()) {
					throw new IllegalArgumentException("Unsupported business relationships");
				}
				for (int i = 0; i < actualRows.size(); i++) {
					Object value = actualRows.get(i).get(field);
					if (!(value instanceof Integer number) || number < 0) {
						throw new IllegalArgumentException("Expected nonnegative integer");
					}
					expectedRows.get(i).put(field, value);
				}
			}
			// Only the selected source's allow/deny flag is a supported QA intervention.
			List<String> scope = List.of("part_id", "supplier_id", "plant_id", "purchasing_org_id");
			List<Map<String, Object>> actualSources = (List<Map<String, Object>>) actual.get("approved_supply_sources");
			List<Map<String, Object>> expectedSources = (List<Map<String, Object>>) expected.get("approved_supply_sources");
			Map<String, Object> source = actualSources.stream().filter(s -> scope.stream()
				.allMatch(k -> request.toMap().get(k).equals(s.get(k)))).findFirst().orElseThrow();
			if (!(source.get("allowed") instanceof Boolean)) {
				throw new IllegalArgumentException("Qualification flag must be boolean");
			}
			expectedSources.stream().filter(s -> scope.stream().allMatch(k -> request.toMap().get(k).equals(s.get(k))))
				.findFirst().orElseThrow().put("allowed", source.get("allowed"));
			if (!expected.equals(actual)) {
				throw new IllegalArgumentException("Unsupported initial-state changes");
			}
			Seed seed = this.json.readValue(this.json.writeValueAsString(actual), Seed.class);
			Supplier supplier = seed.suppliers().stream()
				.filter(s -> s.supplierId().equals(request.supplierId())).findFirst().orElseThrow();
			Part part = seed.parts().stream()
				.filter(p -> p.partId().equals(request.partId())).findFirst().orElseThrow();
			if (supplier.unitPriceMinor() != request.unitPriceMinor() || part.inventory() >= request.quantity()) {
				throw new IllegalArgumentException("Input/state mismatch or unsupported non-shortage branch");
			}
			return seed;
		}
		catch (Exception ex) {
			throw ApiException.badRequest("INVALID_QA_DATA", "Invalid or unsupported initial_state");
		}
	}

	@SuppressWarnings("unchecked")
	public SeedFile read() {
		try {
			Map<String, Object> purchase = readPurchaseProfile();
			Map<String, Object> sample = (Map<String, Object>) purchase.get("sample_data");
			Seed seed = this.json.readValue(this.json.writeValueAsString(sample.get("initial_state")), Seed.class);
			return new SeedFile((String) purchase.get("fixture_id"), seed);
		}
		catch (java.io.IOException ex) {
			throw new IllegalStateException("Cannot read seed fixture: " + this.seedPath, ex);
		}
	}

	@SuppressWarnings("unchecked")
	private Map<String, Object> readPurchaseProfile() throws java.io.IOException {
		Map<String, Object> root = this.json.readValue(Files.readString(this.seedPath), Map.class);
		Map<String, Object> agents = (Map<String, Object>) root.get("agents");
		return (Map<String, Object>) agents.get("PURCHASE");
	}

}
