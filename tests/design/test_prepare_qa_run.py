import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_qa_run import build_bundle, canonical_hash, write_bundle


class DevelopmentRunTests(unittest.TestCase):
    def test_all_supported_combinations_are_prepared_without_fabricated_results(self):
        for scenario in ["S01", "S02", "S03", "S04"]:
            for system in ["B0", "B1"]:
                with self.subTest(scenario=scenario, system=system):
                    bundle = build_bundle(scenario, system, f"RUN-{scenario}-{system}")
                    self.assertIsNone(bundle["manifest.json"]["observed_results"])
                    self.assertIsNone(bundle["oracle-expectations.json"]["observed_results"])
                    self.assertEqual(bundle["seed.json"]["initial_approvals"], [])
                    self.assertEqual(bundle["seed.json"]["initial_orders"], [])
                    self.assertEqual(bundle["runner-config.json"]["fault"]["enabled"], scenario == "S03")

    def test_target_input_does_not_disclose_test_control_or_change_between_systems(self):
        baseline = build_bundle("S03", "B0", "RUN-SAME")
        improved = build_bundle("S03", "B1", "RUN-SAME")
        self.assertEqual(baseline["agent-input.json"], improved["agent-input.json"])
        self.assertEqual(baseline["seed.json"], improved["seed.json"])
        self.assertEqual(baseline["oracle-expectations.json"], improved["oracle-expectations.json"])
        self.assertNotEqual(baseline["runner-config.json"]["server_policy"], improved["runner-config.json"]["server_policy"])
        serialized = json.dumps(baseline["agent-input.json"], ensure_ascii=False)
        for forbidden in ["scenario_id", "B0", "B1", "oracle", "fault", "AFTER_FIRST_SUCCESSFUL_COMMIT"]:
            self.assertNotIn(forbidden, serialized)

    def test_public_input_is_the_same_for_normal_and_fault_scenario(self):
        normal = build_bundle("S01", "B1", "RUN-SAME")
        fault = build_bundle("S03", "B1", "RUN-SAME")
        self.assertEqual(normal["agent-input.json"], fault["agent-input.json"])

    def test_check_scopes_use_result_contract_and_keep_behavior_separate(self):
        schema = json.loads((ROOT / "qa/contracts/check-result.schema.json").read_text())
        allowed = set(schema["properties"]["scope"]["enum"])
        for scenario in ("S01", "S02", "S03", "S04"):
            checks = build_bundle(scenario, "B0", "RUN-SCOPES")["oracle-expectations.json"]["check_definitions"]
            self.assertTrue(all(check["scope"] in allowed for check in checks))
            if scenario == "S02":
                self.assertIn({"rule_id": "R05", "scope": "agent_behavior"}, checks)
                self.assertIn({"rule_id": "R01", "scope": "server_control"}, checks)

    def test_rejection_is_not_inserted_as_a_fabricated_approval_record(self):
        bundle = build_bundle("S02", "B0", "RUN-REJECTION")
        self.assertEqual(bundle["runner-config.json"]["expected_manual_decision"], "REJECTED")
        self.assertEqual(bundle["runner-config.json"]["stored_approval_decisions"], [])
        self.assertFalse(bundle["runner-config.json"]["approval_policy"]["auto_approve"])
        self.assertFalse(bundle["runner-config.json"]["approval_policy"]["convert_timeout_to_rejection"])

    def test_request_hash_ignores_run_scope_but_detects_payload_change(self):
        one = build_bundle("S01", "B0", "RUN-ONE")
        two = build_bundle("S01", "B1", "RUN-TWO")
        self.assertEqual(one["manifest.json"]["request_payload_hash"], two["manifest.json"]["request_payload_hash"])
        payload = copy.deepcopy(one["agent-input.json"]["request"])
        fields = list(payload)
        before = canonical_hash(payload, fields)
        payload["quantity"] = 200
        self.assertNotEqual(before, canonical_hash(payload, fields))

    def test_written_manifest_matches_files_and_existing_directory_is_preserved(self):
        bundle = build_bundle("S03", "B1", "RUN-FILES")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            write_bundle(bundle, output)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(len(manifest["prepared_file_hashes"]), 5)
            for name, expected in manifest["prepared_file_hashes"].items():
                self.assertEqual(expected, hashlib.sha256((output / name).read_bytes()).hexdigest())
            original = (output / "agent-input.json").read_bytes()
            with self.assertRaises(FileExistsError):
                write_bundle(bundle, output)
            self.assertEqual(original, (output / "agent-input.json").read_bytes())

    def test_qualification_bundle_has_denied_state_and_expects_a_hold(self):
        normal = build_bundle("S01", "B1", "RUN-MATCH")
        risk = build_bundle("S04", "B1", "RUN-MATCH")
        self.assertEqual(normal["agent-input.json"], risk["agent-input.json"])
        self.assertFalse(risk["seed.json"]["approved_supply_sources"][0]["allowed"])
        self.assertIsNone(risk["runner-config.json"]["expected_manual_decision"])
        self.assertEqual(risk["oracle-expectations.json"]["expected_order_count"], 0)
        self.assertIn({"rule_id":"R06", "scope":"agent_behavior"}, risk["oracle-expectations.json"]["check_definitions"])

    def test_unenabled_scenario_and_unsafe_run_id_are_rejected(self):
        with self.assertRaises(ValueError):
            build_bundle("M02", "B0", "RUN-UNSUPPORTED")
        with self.assertRaises(ValueError):
            build_bundle("S01", "B0", "../../outside")


if __name__ == "__main__":
    unittest.main()
