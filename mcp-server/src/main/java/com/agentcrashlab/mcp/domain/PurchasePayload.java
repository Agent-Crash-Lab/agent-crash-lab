package com.agentcrashlab.mcp.domain;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

import com.agentcrashlab.mcp.common.Hashing;
import com.agentcrashlab.mcp.common.ToolErrorCode;
import com.agentcrashlab.mcp.common.ToolException;
import tools.jackson.databind.json.JsonMapper;

/**
 * 구매 요청·승인·발주가 공유하는 9개 필드 payload (MCP_SPEC 0.1).
 */
public record PurchasePayload(String requestId, int requestVersion, String partId, int quantity, int unitPriceMinor,
		String currency, String supplierId, String plantId, String purchasingOrgId) {

	static final Set<String> FIELDS = Set.of("request_id", "request_version", "part_id", "quantity", "unit_price_minor",
			"currency", "supplier_id", "plant_id", "purchasing_org_id");

	private static final JsonMapper CANONICAL = JsonMapper.builder().build();

	/**
	 * snake_case 키의 Map(도구 인자, jsonb, seed)에서 만든다. 필드 9개가 정확히 있어야 하고 값도 유효해야 한다.
	 * @throws ToolException VALIDATION_ERROR
	 */
	public static PurchasePayload fromMap(Object value) {
		if (!(value instanceof Map<?, ?> map) || !map.keySet().equals(FIELDS)) {
			throw new ToolException(ToolErrorCode.VALIDATION_ERROR);
		}
		PurchasePayload payload = new PurchasePayload(text(map, "request_id"), integer(map, "request_version"),
				text(map, "part_id"), integer(map, "quantity"), integer(map, "unit_price_minor"), text(map, "currency"),
				text(map, "supplier_id"), text(map, "plant_id"), text(map, "purchasing_org_id"));
		if (payload.requestVersion < 1 || payload.quantity < 1 || payload.unitPriceMinor < 0
				|| !"KRW".equals(payload.currency)) {
			throw new ToolException(ToolErrorCode.VALIDATION_ERROR);
		}
		return payload;
	}

	/** JSON 출력용. 필드 순서는 0.1의 예시 순서 */
	public Map<String, Object> toMap() {
		Map<String, Object> map = new LinkedHashMap<>();
		map.put("request_id", this.requestId);
		map.put("request_version", this.requestVersion);
		map.put("part_id", this.partId);
		map.put("quantity", this.quantity);
		map.put("unit_price_minor", this.unitPriceMinor);
		map.put("currency", this.currency);
		map.put("supplier_id", this.supplierId);
		map.put("plant_id", this.plantId);
		map.put("purchasing_org_id", this.purchasingOrgId);
		return map;
	}

	/** 키 정렬·공백 없는 UTF-8 JSON (Python json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"))) */
	public String canonicalJson() {
		return CANONICAL.writeValueAsString(new TreeMap<>(toMap()));
	}

	public String hash() {
		return Hashing.sha256(canonicalJson());
	}

	private static String text(Map<?, ?> map, String key) {
		if (map.get(key) instanceof String value && !value.isBlank()) {
			return value;
		}
		throw new ToolException(ToolErrorCode.VALIDATION_ERROR);
	}

	private static int integer(Map<?, ?> map, String key) {
		Object value = map.get(key);
		if ((value instanceof Integer || value instanceof Long) && ((Number) value).longValue() == ((Number) value).intValue()) {
			return ((Number) value).intValue();
		}
		throw new ToolException(ToolErrorCode.VALIDATION_ERROR);
	}

}
