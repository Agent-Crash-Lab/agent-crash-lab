"""Prepare isolated development inputs. This does not run an Agent or business API."""

import argparse
import copy
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def canonical_hash(payload, fields):
    selected = {name: payload[name] for name in fields}
    encoded = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def repository_file(root, relative):
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError(f"Invalid repository reference: {relative}")
    return resolved


def build_bundle(scenario_id, system_id, run_id, root=ROOT):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}", run_id):
        raise ValueError("run_id must contain 2-64 letters, digits, underscores or hyphens")
    config_path = root / "config/development-baseline.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if scenario_id not in config["enabled_scenarios"]:
        raise ValueError(f"Scenario is not enabled in this baseline: {scenario_id}")
    if system_id not in config["systems"]:
        raise ValueError(f"Unknown system: {system_id}")

    paths = {name: repository_file(root, value) for name, value in config["references"].items()}
    catalog = json.loads(paths["scenarios"].read_text(encoding="utf-8"))
    scenario = next(row for row in catalog["base_scenarios"] if row["scenario_id"] == scenario_id)
    profile_document = json.loads(paths["profiles"].read_text(encoding="utf-8"))
    profile = next(row for row in profile_document["profiles"] if row["agent_id"] == config["target"]["profile_id"])
    seed = copy.deepcopy(json.loads(paths["seed"].read_text(encoding="utf-8"))["seed"])
    tool_contracts = json.loads(paths["tool_contracts"].read_text(encoding="utf-8"))
    seed["run_id"] = run_id
    for key in ("parts", "suppliers", "approved_supply_sources", "users"):
        for row in seed[key]:
            row["run_id"] = run_id
    seed["request"]["run_id"] = run_id
    if seed["initial_orders"] or seed["initial_approvals"]:
        raise ValueError("Baseline seed must start without stored orders or approvals")

    fields = config["canonical_payload"]["fields"]
    request = {name: seed["request"][name] for name in fields}
    request_hash = canonical_hash(request, fields)
    selected_ids = scenario["test_runner_only"]["oracle_rule_ids"]
    rules = [row for row in catalog["base_rules"] if row["rule_id"] in selected_ids]
    if len(rules) != len(selected_ids):
        raise ValueError("Scenario references missing or duplicate rules")

    # The target projection deliberately omits scenario, fault, system and expected results.
    agent_input = {
        "contract_version": config["config_version"],
        "execution_context": {"run_id": run_id, "requester_id": "requester-01"},
        "target_profile_id": profile["agent_id"],
        "task": config["target"]["task"],
        "request": request,
        "business_policy": {
            "quantity_rule": seed["business_rule"],
            "approval_required_before_create": True,
            "approved_payload_must_match": True,
            "preserve_request_id_and_payload_on_retry": True,
            "report_only_confirmed_success": True,
        },
        "execution_policy": {
            name: config["execution"][name]
            for name in (
                "max_agent_turns", "max_tool_calls", "max_active_seconds_per_agent",
                "tool_timeout_seconds", "write_retries_after_ambiguous_error",
                "read_retries_after_transient_error", "implicit_sdk_write_retries",
            )
        },
        "tools": tool_contracts["tools"],
    }
    expected_decision = "REJECTED" if scenario_id == "S02" else "APPROVED"
    runner_config = {
        "status": "PREPARED_NOT_EXECUTED",
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_version": scenario["version"],
        "system_id": system_id,
        "server_policy": config["systems"][system_id],
        "execution": config["execution"],
        "approval_policy": config["approval"],
        "expected_manual_decision": expected_decision,
        "expected_approval_payload_hash": request_hash,
        "stored_approval_decisions": [],
        "fault": {**config["fault"], "enabled": scenario_id in config["fault"]["enabled_in_scenarios"]},
        "interventions": scenario["test_runner_only"]["interventions"],
        "integration_status": config["live_integration_status"],
    }
    expectations = {
        "status": "EXPECTED_CRITERIA_NOT_OBSERVED_RESULTS",
        "run_id": run_id,
        "request_id": request["request_id"],
        "scenario_id": scenario_id,
        "rule_version": config["evaluation"]["rule_version"],
        "rules": rules,
        "expected_order_count": 0 if scenario_id == "S02" else 1,
        "fault_application_required": scenario_id == "S03",
        "required_evidence": scenario["required_evidence"],
        "evaluation_policy": config["evaluation"],
        "observed_results": None,
    }
    inputs = {"config/development-baseline.json": hashlib.sha256(config_path.read_bytes()).hexdigest()}
    inputs.update({config["references"][name]: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()})
    manifest = {
        "manifest_version": config["config_version"],
        "status": "PREPARED_NOT_EXECUTED",
        "run_id": run_id,
        "scenario_id": scenario_id,
        "system_id": system_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reference_hashes": inputs,
        "request_payload_hash": request_hash,
        "requires_live_model_environment": config["llm"]["model_environment"],
        "observed_results": None,
    }
    return {
        "agent-input.json": agent_input,
        "seed.json": seed,
        "runner-config.json": runner_config,
        "oracle-expectations.json": expectations,
        "manifest.json": manifest,
    }


def write_bundle(bundle, destination):
    destination = Path(destination)
    # Exclusive directory creation makes accidental overwrite, including concurrent use, fail.
    destination.mkdir(parents=True, exist_ok=False)
    manifest = copy.deepcopy(bundle["manifest.json"])
    manifest["prepared_file_hashes"] = {}
    for name, value in bundle.items():
        if name == "manifest.json":
            continue
        encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (destination / name).write_bytes(encoded)
        manifest["prepared_file_hashes"][name] = hashlib.sha256(encoded).hexdigest()
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, choices=["S01", "S02", "S03"])
    parser.add_argument("--system", required=True, choices=["B0", "B1"])
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    run_id = args.run_id or "RUN-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    try:
        bundle = build_bundle(args.scenario, args.system, run_id)
        output = args.output_dir or ROOT / "artifacts/local-runs" / run_id
        write_bundle(bundle, output)
    except (ValueError, FileExistsError) as error:
        parser.exit(2, str(error) + "\n")
    print(f"Prepared {output}; no Agent, API or database was executed.")


if __name__ == "__main__":
    main()
