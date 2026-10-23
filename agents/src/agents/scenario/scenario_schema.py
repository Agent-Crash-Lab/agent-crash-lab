"""Constrain generated sandbox facts, while code still checks business relationships."""

import copy


def obj(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def fixed(value):
    if isinstance(value, dict):
        return obj({k: fixed(v) for k, v in value.items()})
    if isinstance(value, list):
        return {"type": "array", "items": {"type": "string"}, "maxItems": 0}
    kind = (
        "null"
        if value is None
        else "boolean"
        if isinstance(value, bool)
        else "integer"
        if isinstance(value, int)
        else "string"
    )
    return {"type": kind, "enum": [value]}


def strict(schema):
    schema = copy.deepcopy(schema)
    if "const" in schema:
        schema["enum"] = [schema.pop("const")]
    if schema.get("type") == "object":
        return obj({k: strict(v) for k, v in schema.get("properties", {}).items()})
    if "items" in schema:
        schema["items"] = strict(schema["items"])
    if "anyOf" in schema:
        schema["anyOf"] = [strict(s) for s in schema["anyOf"]]
    return schema


def output_schema(target, sample, contract):
    kind = target.get("agent_type")
    if target["simulation_adapter"] not in {
        "reference-purchase-v1",
        "reference-production-v1",
        "reference-quality-v1",
    }:
        return None
    request, state = sample["business_input"], sample["initial_state"]
    fields = target["business_input_schema"].get("properties", {})
    business = obj(
        {
            key: fixed(value)
            if key.endswith("_id") and key != "request_id"
            else strict(fields.get(key, fixed(value)))
            for key, value in request.items()
        }
    )
    if kind == "PURCHASE":
        mutable = {}
        for name, variable in (
            ("parts", "inventory"),
            ("suppliers", "unit_price_minor"),
            ("approved_supply_sources", "allowed"),
        ):
            rows = []
            for row in state[name]:
                properties = {k: fixed(v) for k, v in row.items()}
                properties[variable] = (
                    {"type": "boolean"}
                    if variable == "allowed"
                    else {"type": "integer", "minimum": 0, "maximum": 2147483647}
                )
                rows.append(obj(properties))
            mutable[name] = {
                "type": "array",
                "items": {"anyOf": rows},
                "minItems": len(rows),
                "maxItems": len(rows),
            }
        initial = obj(mutable)
    else:
        state_schema = contract["$defs"][kind.lower() + "_state"]["properties"]
        keys = (
            ("machine_status", "scheduled_jobs", "predecessor_end_min")
            if kind == "PRODUCTION"
            else ("certificate_result", "required_test_record")
        )
        initial = obj({key: strict(state_schema[key]) for key in keys})
        if kind == "QUALITY":
            record = state.get("required_test_record")
            if record:
                for branch in initial["properties"]["required_test_record"]["anyOf"]:
                    if branch.get("type") == "object":
                        for key in ("lot_id", "inspection_id"):
                            branch["properties"][key] = fixed(record[key])
    return obj(
        {
            "business_input_patch": business,
            "initial_state_patch": initial,
            "approval_decision": {"type": "string", "enum": ["APPROVED", "REJECTED"]},
            "fault": {"type": "string", "enum": ["NONE", "RESPONSE_LOSS"]},
            "interventions": {
                "type": "array",
                "maxItems": 0 if kind == "PURCHASE" else 1,
                "items": obj(
                    {
                        "phase": {"type": "string", "enum": ["AFTER_APPROVAL_BEFORE_WRITE"]},
                        "state_patch": initial,
                    }
                ),
            },
        }
    )
