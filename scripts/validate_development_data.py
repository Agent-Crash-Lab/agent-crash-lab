"""Check development settings, JSON contracts and fixture references; no live services."""

import hashlib
import json
import re
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
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
    for name in ("purchase-result", "oracle-observation", "qa-check"):
        schema = load(f"contracts/drafts/manufacturing-qa/{name}.schema.json")
        Draft202012Validator.check_schema(schema)
        validators[name] = Draft202012Validator(schema)
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
    print(f"PASS: settings, 3 result/observation schemas, {len(tools)} tool schemas, {len(scenarios)} scenarios, {len(cases)} oracle cases, {len(sources)} sources and document links.")
    print("Not checked: live Agent behavior, application builds, migrations or real business operations.")


if __name__ == "__main__":
    main()
