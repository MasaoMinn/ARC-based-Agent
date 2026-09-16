from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agents.test_quality import (
    assess_requirement_risk,
    classify_red_gate_output,
    has_error_issues,
    inspect_test_artifacts,
    normalize_coverage_plan_payload,
    validate_coverage_plan,
)


def _obligation(**overrides):
    value = {
        "obligation_id": "REQ-1.OBL.SC-1",
        "source": "scenario:SC-1",
        "priority": "MUST",
        "kind": "state",
        "description": "Submitting the form persists the requested value.",
        "preconditions": ["The form is visible."],
        "action": "Submit a valid value.",
        "oracle": "The persisted value remains visible after reload.",
        "layer": "E2E",
        "scenario_ids": ["SC-1"],
        "interface_ids": ["REQ-1.UI"],
    }
    value.update(overrides)
    return value


def _test_manifest(**overrides):
    value = {
        "test_id": "REQ-1.TEST.SC-1",
        "req_id": "REQ-1",
        "obligation_ids": ["REQ-1.OBL.SC-1"],
        "scenario_ids": ["SC-1"],
        "interface_ids": ["REQ-1.UI"],
        "type": "E2E",
        "file_path": "backend/test-e2e/req-1.spec.ts",
        "first_line": "import { test, expect } from '@playwright/test';",
    }
    value.update(overrides)
    return value


class CoveragePlanTests(unittest.TestCase):
    def test_normalizes_structured_coverage_plan(self) -> None:
        plan = normalize_coverage_plan_payload({"coverage_plan": [_obligation(priority="must", layer="e2e")]})

        self.assertEqual(plan[0]["priority"], "MUST")
        self.assertEqual(plan[0]["layer"], "E2E")
        self.assertEqual(plan[0]["scenario_ids"], ["SC-1"])

    def test_complete_scenario_plan_has_no_errors(self) -> None:
        issues = validate_coverage_plan(
            node_id="REQ-1",
            requirement_data={"scenarios": [{"id": "SC-1", "name": "Persist value"}]},
            interfaces=[{"interface_id": "REQ-1.UI", "type": "UI"}],
            tests=[_test_manifest()],
            coverage_plan=[_obligation()],
        )

        self.assertFalse(has_error_issues(issues), issues)

    def test_missing_e2e_scenario_mapping_is_blocking(self) -> None:
        issues = validate_coverage_plan(
            node_id="REQ-1",
            requirement_data={"scenarios": [{"id": "SC-1"}]},
            interfaces=[{"interface_id": "REQ-1.UI", "type": "UI"}],
            tests=[_test_manifest(type="Integration", scenario_ids=[])],
            coverage_plan=[_obligation(layer="Integration", scenario_ids=[])],
        )

        self.assertTrue(has_error_issues(issues))
        self.assertIn("scenario_e2e_coverage_missing", {item["code"] for item in issues})

    def test_unmapped_must_obligation_is_blocking(self) -> None:
        issues = validate_coverage_plan(
            node_id="REQ-1",
            requirement_data={"scenarios": []},
            interfaces=[{"interface_id": "REQ-1.UI", "type": "UI"}],
            tests=[_test_manifest(obligation_ids=["REQ-1.OBL.OTHER"], scenario_ids=[], type="Unit")],
            coverage_plan=[_obligation(scenario_ids=[], layer="Unit")],
        )

        codes = {item["code"] for item in issues}
        self.assertIn("test_obligation_unknown", codes)
        self.assertIn("must_obligation_uncovered", codes)


class StaticArtifactTests(unittest.TestCase):
    def test_accepts_enabled_test_with_behavioral_assertion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frontend" / "tests" / "value.test.ts"
            path.parent.mkdir(parents=True)
            path.write_text(
                "import { expect, test } from 'vitest';\n"
                "test('persists value', () => { expect(loadValue()).toBe('saved'); });\n",
                encoding="utf-8",
            )

            issues = inspect_test_artifacts(
                directory,
                [_test_manifest(file_path="frontend/tests/value.test.ts", type="Integration")],
            )

        self.assertFalse(has_error_issues(issues), issues)

    def test_rejects_skipped_only_test_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frontend" / "tests" / "value.test.ts"
            path.parent.mkdir(parents=True)
            path.write_text(
                "import { expect, test } from 'vitest';\n"
                "test.skip('persists value', () => { expect(true).toBe(true); });\n",
                encoding="utf-8",
            )

            issues = inspect_test_artifacts(
                directory,
                [_test_manifest(file_path="frontend/tests/value.test.ts", type="Integration")],
            )

        codes = {item["code"] for item in issues}
        self.assertIn("enabled_test_missing", codes)
        self.assertIn("tests_disabled_only", codes)


class RedGateTests(unittest.TestCase):
    def test_behavioral_failure_is_a_valid_red_test(self) -> None:
        result = classify_red_gate_output(
            "Exit Code: 1\nSTDOUT:\nFAIL tests/value.test.ts\nAssertionError: expected 501 to be 200\n"
        )

        self.assertEqual(result["status"], "valid_red")

    def test_preimplementation_success_is_suspicious(self) -> None:
        result = classify_red_gate_output(
            "Exit Code: 0\nSTDOUT:\nTest Files  1 passed (1)\nTests  2 passed (2)\n"
        )

        self.assertEqual(result["status"], "unexpected_pass")

    def test_collection_failure_is_not_a_valid_red_test(self) -> None:
        result = classify_red_gate_output(
            "Exit Code: 1\nSTDERR:\nError: Cannot find module '../src/service'\n"
        )

        self.assertEqual(result["status"], "invalid")


class RiskAssessmentTests(unittest.TestCase):
    def test_cross_layer_auth_persistence_node_is_high_risk(self) -> None:
        result = assess_requirement_risk(
            {
                "description": "An authenticated user saves an order and restores the session after refresh.",
                "scenarios": [{"id": "SC-1"}],
                "dependencies": ["REQ-AUTH"],
            },
            [{"type": "UI"}, {"type": "API"}, {"type": "DB"}],
        )

        self.assertEqual(result["tier"], "high")


if __name__ == "__main__":
    unittest.main()
