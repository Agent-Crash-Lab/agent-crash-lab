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
 * fixtures/drafts/manufacturing-qa/purchase-seed.json을 읽는다. 실행 초기화 때마다 다시 읽는다.
 */
@Component
public class SeedFixtures {

	static final String SEED_FILE = "drafts/manufacturing-qa/purchase-seed.json";

	private final JsonMapper json;

	private final Path seedPath;

	SeedFixtures(JsonMapper json, CrashLabProperties properties) {
		this.json = json;
		this.seedPath = Path.of(properties.fixturesDir()).resolve(SEED_FILE);
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

	public SeedFile read() {
		try {
			return this.json.readValue(Files.readString(this.seedPath), SeedFile.class);
		}
		catch (java.io.IOException ex) {
			throw new IllegalStateException("Cannot read seed fixture: " + this.seedPath, ex);
		}
	}

}
