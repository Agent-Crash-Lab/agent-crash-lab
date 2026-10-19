"""Check development settings, JSON contracts and fixture references; no live services."""

import hashlib
import json
import re
from pathlib import Path

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as error:
    raise SystemExit("Install design dependencies: python -m pip install -r requirements-design.txt") from error

ROOT = Path(__file__).resolve().parents[1]


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def main():
    config = load("config/development-baseline.json")
    for reference in config["references"].values():
        path = (ROOT / reference).resolve()
        assert path.is_relative_to(ROOT) and path.is_file(), reference
    assert config["enabled_scenarios"] == ["S01", "S02", "S03"]
    assert config["systems"]["B0"]["approval_enforced"]
    assert config["systems"]["B1"]["approval_enforced"]
    assert not config["systems"]["B0"]["idempotency_enforced"]
    assert config["systems"]["B1"]["idempotency_enforced"]
    assert config["approval"]["mode"] == "MANUAL"
    assert not config["approval"]["auto_approve"]
    assert not config["approval"]["convert_timeout_to_rejection"]
    assert config["execution"]["write_retries_after_ambiguous_error"] == 1
    assert config["fault"]["max_applied_count"] == 1
    assert not config["fault"]["expose_commit_status_to_target"]

    examples = load("contracts/drafts/manufacturing-qa/examples.json")
    validators = {}
    for name in ("purchase-result", "oracle-observation", "qa-check", "event"):
        schema = load(f"contracts/drafts/manufacturing-qa/{name}.schema.json")
        Draft202012Validator.check_schema(schema)
        validators[name] = Draft202012Validator(schema, format_checker=FormatChecker())
    for name in ("purchase_success", "purchase_rejected", "purchase_report_during_duplicate_fixture"):
        validators["purchase-result"].validate(examples[name])
    validators["oracle-observation"].validate(examples["oracle_observation_for_duplicate"])
    validators["qa-check"].validate(examples["qa_check_for_duplicate"])
    tools = load(config["references"]["tool_contracts"])["tools"]
    for tool in tools:
        Draft202012Validator.check_schema(tool["input_schema"])
    tool_by_name = {tool["name"]: tool for tool in tools}
    assert set(tool_by_name) == {"get_inventory", "get_supplier", "create_purchase_order", "get_order_by_request"}

    seed = load(config["references"]["seed"])["seed"]
    assert seed["parts"][0]["inventory"] == 20
    assert seed["request"]["quantity"] == 100
    assert seed["request"]["unit_price_minor"] == 12000
    assert not seed["initial_orders"] and not seed["initial_approvals"]
    create_args = {"request": seed["request"], "approval_id": "AP-EXAMPLE"}
    Draft202012Validator(tool_by_name["create_purchase_order"]["input_schema"]).validate(create_args)

    sources = load("fixtures/drafts/manufacturing-qa/sources.json")["sources"]
    source_ids = {source["source_id"] for source in sources}
    assert len(source_ids) == len(sources)
    for source in sources:
        if source.get("local_material"):
            assert (ROOT / source["local_material"]).is_file()
    catalog = load(config["references"]["scenarios"])
    scenarios = catalog["base_scenarios"] + catalog["extension_scenarios"]
    scenario_ids = {scenario["scenario_id"] for scenario in scenarios}
    rules = catalog["base_rules"] + catalog["extension_rules"]
    rule_ids = {rule["rule_id"] for rule in rules}
    scopes = validators["qa-check"].schema["properties"]["scope"]["enum"]
    base_rule_ids = {rule["rule_id"] for rule in catalog["base_rules"]}
    assert set(config["evaluation"]["rule_check_scopes"]) == base_rule_ids
    for mapped_scopes in config["evaluation"]["rule_check_scopes"].values():
        assert mapped_scopes and set(mapped_scopes) <= set(scopes)
    profiles = load(config["references"]["profiles"])["profiles"]
    for profile in profiles:
        assert set(profile["scenario_ids"]) <= scenario_ids
        assert set(profile["source_ids"]) <= source_ids
    for scenario in scenarios:
        selected = scenario.get("rule_ids", scenario.get("test_runner_only", {}).get("oracle_rule_ids", []))
        assert set(selected) <= rule_ids
        assert set(scenario["source_ids"]) <= source_ids
    cases = load(config["references"]["oracle_cases"])["cases"]
    for case in cases:
        assert set(case["expected_checks"]) <= rule_ids
        for approval in case.get("approvals", []):
            encoded = json.dumps(approval["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            assert hashlib.sha256(encoded).hexdigest() == approval["payload_hash"]

    guide_path = ROOT / config["references"]["guide_index"]
    guides = load(config["references"]["guide_index"])["documents"]
    guide_refs = {f'{guide["document_id"]}@{guide["version"]}' for guide in guides}
    assert len(guide_refs) == len(guides)
    for guide in guides:
        assert (guide_path.parent / guide["body_path"]).is_file()
        assert set(guide["source_ids"]) <= source_ids
    investigation_cases = load(config["references"]["investigation_cases"])["cases"]
    for case in investigation_cases:
        assert case["guide_ref"] in guide_refs
        assert all(item["run_id"] == case["run_id"] for item in case["evidence"])
        evidence_ids = [item["evidence_id"] for item in case["evidence"]]
        assert len(evidence_ids) == len(set(evidence_ids))
        for evidence in case["evidence"]:
            if evidence["kind"] == "RUN_TRACE":
                seen = set()
                for event in evidence["payload"]["events"]:
                    validators["event"].validate(event)
                    assert event["run_id"] == case["run_id"]
                    assert event["parent_event_id"] is None or event["parent_event_id"] in seen
                    assert event["event_id"] not in seen
                    assert set(event["evidence_ids"]) <= set(evidence_ids)
                    seen.add(event["event_id"])
            if evidence["kind"] == "BUSINESS_SNAPSHOT":
                for entity in ("approval", "order"):
                    for row in evidence["payload"][entity + "s"]:
                        schema = {"$ref": f"#/$defs/{entity}", "$defs": validators["oracle-observation"].schema["$defs"]}
                        Draft202012Validator(schema, format_checker=FormatChecker()).validate(row)
                        assert row["run_id"] == case["run_id"]
    tests = load(config["references"]["individual_and_demo_tests"])
    for test in tests["purchase_agent_tests"] + tests["investigation_agent_tests"]:
        assert (ROOT / test["fixture_ref"]).is_file()
        if "fixture_id" in test:
            assert any(case["fixture_id"] == test["fixture_id"] for case in investigation_cases)
    mapping = load(config["references"]["event_mapping"])
    event_nodes = validators["event"].schema["properties"]["node_id"]["enum"]
    assert set(mapping["node_ids"]) == set(event_nodes)
    assert all(item["node_id"] in event_nodes for item in mapping["mapping"].values())
    for tool in load(config["references"]["investigation_tools"])["tools"]:
        Draft202012Validator.check_schema(tool["input_schema"])

    sample = load("fixtures/reference/bpi2019/sample.json")
    assert len(sample["traces"]) == sample["trace_count"] == 10
    assert sum(len(trace["events"]) for trace in sample["traces"]) == sample["event_count"] == 132
    assert any(row.get("rightsIdentifier") == "cc-by-4.0" for row in sample["source_metadata"]["rightsList"])
    documents = list((ROOT / "docs/design-prep").glob("*.md"))
    documents += list((ROOT / "contracts/drafts").rglob("README.md"))
    documents += list((ROOT / "fixtures/drafts").rglob("README.md"))
    documents += list((ROOT / "fixtures/reference").rglob("README.md"))
    for document in documents:
        text = document.read_text(encoding="utf-8")
        assert text.count("```") % 2 == 0, document
        assert "/Users/" not in text, document
        for link in re.findall(r"(?<!!)\[[^\]]*\]\(([^)]+)\)", text):
            if not link.startswith(("https://", "http://", "#", "mailto:")):
                assert (document.parent / link.split("#")[0]).exists(), (document, link)
    print(f"PASS: settings, 4 result/observation/event schemas, {len(tools)} purchase tool schemas, {len(scenarios)} scenarios, {len(cases)} oracle cases, {len(investigation_cases)} investigation cases, {len(guides)} guides, {len(sources)} sources and document links.")
    print("Not checked: live Agent behavior, application builds, migrations or real business operations.")


if __name__ == "__main__":
    main()
