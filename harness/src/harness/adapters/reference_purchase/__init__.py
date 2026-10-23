"""Purchase is one reference target with a concrete sandbox and code evaluator."""

import copy
import json

from jsonschema import Draft202012Validator


class ReferencePurchaseAdapter:
    adapter_id = "reference-purchase-v1"
    capabilities = {
        "state_observation",
        "tool_trace",
        "supply_source_state",
        "approval_control",
        "post_commit_response_loss",
    }
    tests = {
        "CONTROL_BASELINE": "S01",
        "APPROVAL_DENIED": "S02",
        "UNQUALIFIED_SUPPLIER": "S04",
        "POST_COMMIT_RESPONSE_LOSS": "S03",
    }

    def __init__(self, root, config):
        def read(reference):
            return json.loads((root / config["references"][reference]).read_text())

        profile = read("target_profiles")["agents"]["PURCHASE"]
        descriptor = copy.deepcopy(profile["target"])
        if (
            descriptor["policies"]["max_write_retries"]
            != config["execution"]["write_retries_after_ambiguous_error"]
        ):
            raise ValueError("Reference target policy and runtime retry limit must match")
        tools = read("tool_contracts")["tools"]
        target_tools = [
            {key: tool[key] for key in ("name", "effect", "input_schema")} for tool in tools
        ]
        if target_tools != descriptor["tools"]:
            raise ValueError("Purchase Agent profile and tool contract must match")
        self.target = descriptor
        self.sample = copy.deepcopy(profile["sample_data"])
        self.rules_by_test = {
            scenario["scenario_id"]: scenario["test_runner_only"]["oracle_rule_ids"]
            for scenario in read("scenarios")["base_scenarios"]
        }

    def supports_sample(self, sample):
        """Vary quantities/prices, keeping the registered business and authority model.

        This adapter covers shortage procurement only. New suppliers, permissions,
        pre-existing transactions and other business branches need their own checks.
        """
        try:
            request = sample["business_input"]
            state = sample["initial_state"]
            Draft202012Validator(self.target["business_input_schema"]).validate(request)
            if state["request"] != request:
                return False
            if (
                request["request_id"] != request["request_id"].strip()
                or len(request["request_id"]) > 128
            ):
                return False
            expected = copy.deepcopy(self.sample["initial_state"])
            for key in ("request_id", "request_version", "quantity", "unit_price_minor"):
                expected["request"][key] = request[key]
            for actual, original in zip(state["parts"], expected["parts"], strict=True):
                value = actual["inventory"]
                if type(value) is not int or not 0 <= value <= 2_147_483_647:
                    return False
                original["inventory"] = value
            for actual, original in zip(state["suppliers"], expected["suppliers"], strict=True):
                value = actual["unit_price_minor"]
                if type(value) is not int or not 0 <= value <= 2_147_483_647:
                    return False
                original["unit_price_minor"] = value
            source = self.selected_source(state, request)
            if type(source["allowed"]) is not bool:
                return False
            self.selected_source(expected, request)["allowed"] = source["allowed"]
            if any(
                type(request[k]) is not int or request[k] > 2_147_483_647
                for k in ("request_version", "quantity", "unit_price_minor")
            ):
                return False
            supplier = next(
                s for s in state["suppliers"] if s["supplier_id"] == request["supplier_id"]
            )
            part = next(p for p in state["parts"] if p["part_id"] == request["part_id"])
            return (
                json.dumps(state, sort_keys=True) == json.dumps(expected, sort_keys=True)
                and supplier["unit_price_minor"] == request["unit_price_minor"]
                and part["inventory"] < request["quantity"]
            )
        except (KeyError, TypeError, ValueError, StopIteration):
            return False

    @staticmethod
    def selected_source(state, request):
        fields = ("part_id", "supplier_id", "plant_id", "purchasing_org_id")
        return next(
            s for s in state["approved_supply_sources"] if all(s[k] == request[k] for k in fields)
        )

    def prepare_case(self, risk_id, sample):
        if risk_id == "UNQUALIFIED_SUPPLIER":
            return self.design_sample("UNAPPROVED_SOURCE", sample)
        if risk_id == "CONTROL_BASELINE":
            return self.design_sample("QUALIFIED_SOURCE", sample)
        return (
            copy.deepcopy(sample)
            if self.selected_source(sample["initial_state"], sample["business_input"])["allowed"]
            else None
        )

    def design_sample(self, strategy, sample):
        if strategy in {"UNAPPROVED_SOURCE", "QUALIFIED_SOURCE"}:
            if not self.supports_sample(sample):
                return None
            result = copy.deepcopy(sample)
            self.selected_source(result["initial_state"], result["business_input"])["allowed"] = (
                strategy == "QUALIFIED_SOURCE"
            )
            return result if self.supports_sample(result) else None
        if strategy != "SHORTAGE_BOUNDARY" or not self.supports_sample(sample):
            return None
        result = copy.deepcopy(sample)
        part = next(
            p
            for p in result["initial_state"]["parts"]
            if p["part_id"] == result["business_input"]["part_id"]
        )
        result["business_input"]["quantity"] = part["inventory"] + 1
        result["initial_state"]["request"] = copy.deepcopy(result["business_input"])
        return result if self.supports_sample(result) else None
