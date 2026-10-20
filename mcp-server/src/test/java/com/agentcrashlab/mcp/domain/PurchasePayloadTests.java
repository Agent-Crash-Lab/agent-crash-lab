package com.agentcrashlab.mcp.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import com.agentcrashlab.mcp.common.ToolErrorCode;
import com.agentcrashlab.mcp.common.ToolException;

class PurchasePayloadTests {

	static Map<String, Object> seedRequest() {
		Map<String, Object> map = new HashMap<>();
		map.put("request_id", "REQ-001");
		map.put("request_version", 1);
		map.put("part_id", "PART-A");
		map.put("quantity", 100);
		map.put("unit_price_minor", 12000);
		map.put("currency", "KRW");
		map.put("supplier_id", "SUP-01");
		map.put("plant_id", "PLANT-A");
		map.put("purchasing_org_id", "PUR-A");
		return map;
	}

	@Test
	void hashMatchesDraftFixtures() {
		// drafts oracle-cases.json, investigation-cases.json, examples.json의 payload_hash
		assertThat(PurchasePayload.fromMap(seedRequest()).hash())
			.isEqualTo("44f349414b0973935825d379579a30cf137ec3ab49c2b28bc9923f46d4e8bf26");
	}

	@Test
	void nonAsciiIsNotEscapedLikePython() {
		Map<String, Object> map = seedRequest();
		map.put("request_id", "요청-1");
		// python: json.dumps(p, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
		assertThat(PurchasePayload.fromMap(map).hash())
			.isEqualTo("b88c8a4d00a85a6a6f4427483b0b54528feae94d4853e739ee0a554e84217a66");
	}

	@Test
	void rejectsMissingOrExtraFields() {
		Map<String, Object> missing = seedRequest();
		missing.remove("plant_id");
		Map<String, Object> extra = seedRequest();
		extra.put("run_id", "RUN-001");

		assertThatThrownBy(() -> PurchasePayload.fromMap(missing)).isInstanceOf(ToolException.class);
		assertThatThrownBy(() -> PurchasePayload.fromMap(extra)).isInstanceOf(ToolException.class);
	}

	@Test
	void rejectsInvalidValues() {
		Map<String, Object> zeroQuantity = seedRequest();
		zeroQuantity.put("quantity", 0);
		Map<String, Object> textQuantity = seedRequest();
		textQuantity.put("quantity", "100");
		Map<String, Object> usd = seedRequest();
		usd.put("currency", "USD");

		for (Map<String, Object> invalid : List.of(zeroQuantity, textQuantity, usd)) {
			assertThatThrownBy(() -> PurchasePayload.fromMap(invalid)).isInstanceOf(ToolException.class)
				.extracting(e -> ((ToolException) e).code())
				.isEqualTo(ToolErrorCode.VALIDATION_ERROR);
		}
	}

}
