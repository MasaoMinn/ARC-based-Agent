from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.phases import WorkflowPhaseRunner


def _coverage_plan() -> list[dict[str, object]]:
    return [
        {
            "obligation_id": "REQ-1.OBL.GREETING",
            "source": "requirement",
            "priority": "MUST",
            "kind": "happy",
            "description": "The greeting service returns the requested name.",
            "preconditions": [],
            "action": "Request a greeting for Ada.",
            "oracle": "The returned greeting contains Ada.",
            "layer": "Unit",
            "scenario_ids": [],
            "interface_ids": ["REQ-1.FUNC.GREETING"],
        }
    ]


def _tests() -> list[dict[str, object]]:
    return [
        {
            "test_id": "REQ-1.TEST.GREETING",
            "req_id": "REQ-1",
            "type": "Unit",
            "file_path": "frontend/tests/greeting.test.ts",
            "obligation_ids": ["REQ-1.OBL.GREETING"],
            "scenario_ids": [],
            "interface_ids": ["REQ-1.FUNC.GREETING"],
        }
    ]


def _interfaces() -> list[dict[str, str]]:
    return [{"interface_id": "REQ-1.FUNC.GREETING", "type": "FUNC"}]


def _make_runner(workspace: str, output: str) -> tuple[WorkflowPhaseRunner, list[tuple[object, ...]], AsyncMock]:
    logs: list[tuple[object, ...]] = []
    run_test_group = AsyncMock(return_value=output)
    runner = WorkflowPhaseRunner.__new__(WorkflowPhaseRunner)
    runner.workspace_path = workspace
    runner.log_cb = lambda *args: logs.append(args)
    runner.app_handler = SimpleNamespace(run_test_group=run_test_group)
    return runner, logs, run_test_group


def _write_behavioral_test(workspace: str) -> None:
    test_file = Path(workspace) / "frontend" / "tests" / "greeting.test.ts"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "import { expect, test } from 'vitest';\n"
        "test('greets the requested user', () => { expect(greet('Ada')).toBe('Hello Ada'); });\n",
        encoding="utf-8",
    )


class PhaseTestQualityTests(unittest.IsolatedAsyncioTestCase):
    async def test_behavioral_red_run_passes_deterministic_gate(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            _write_behavioral_test(workspace)
            runner, _, run_test_group = _make_runner(
                workspace,
                "Exit Code: 1\nSTDOUT:\nFAIL greeting.test.ts\nAssertionError: expected undefined to be 'Hello Ada'\n",
            )

            report = await runner._assess_generated_test_suite(
                node_id="REQ-1",
                requirement_data={"id": "REQ-1", "description": "Show a greeting."},
                interfaces=_interfaces(),
                tests=_tests(),
                coverage_plan=_coverage_plan(),
            )

        self.assertFalse(report["blocking"], report)
        self.assertFalse(report["critic_required"], report)
        self.assertEqual(report["red_gate"]["batches"][0]["status"], "valid_red")
        run_test_group.assert_awaited_once_with("Unit", ["frontend/tests/greeting.test.ts"])

    async def test_unexpected_preimplementation_pass_blocks_fresh_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            _write_behavioral_test(workspace)
            runner, _, _ = _make_runner(
                workspace,
                "Exit Code: 0\nSTDOUT:\nTest Files 1 passed (1)\nTests 1 passed (1)\n",
            )

            with patch.dict(os.environ, {"ARC_WORKSPACE_MODE": "scaffold"}):
                report = await runner._assess_generated_test_suite(
                    node_id="REQ-1",
                    requirement_data={"id": "REQ-1", "description": "Show a greeting."},
                    interfaces=_interfaces(),
                    tests=_tests(),
                    coverage_plan=_coverage_plan(),
                )

        self.assertTrue(report["blocking"], report)
        self.assertTrue(report["critic_required"], report)
        issue = next(item for item in report["issues"] if item["code"] == "red_gate_unexpected_pass")
        self.assertEqual(issue["severity"], "error")

    async def test_unexpected_pass_in_evolution_mode_requires_critic_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            _write_behavioral_test(workspace)
            runner, _, _ = _make_runner(
                workspace,
                "Exit Code: 0\nSTDOUT:\nTest Files 1 passed (1)\nTests 1 passed (1)\n",
            )

            with patch.dict(os.environ, {"ARC_WORKSPACE_MODE": "evolution"}):
                report = await runner._assess_generated_test_suite(
                    node_id="REQ-1",
                    requirement_data={"id": "REQ-1", "description": "Show a greeting."},
                    interfaces=_interfaces(),
                    tests=_tests(),
                    coverage_plan=_coverage_plan(),
                )

        self.assertFalse(report["blocking"], report)
        self.assertTrue(report["critic_required"], report)
        issue = next(item for item in report["issues"] if item["code"] == "red_gate_unexpected_pass")
        self.assertEqual(issue["severity"], "warning")

    async def test_red_gate_without_any_executable_batch_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            _write_behavioral_test(workspace)
            runner, _, _ = _make_runner(workspace, "")
            runner._run_preimplementation_red_gate = AsyncMock(
                return_value={
                    "status": "invalid",
                    "reason": "No supported test layer was available.",
                    "batches": [],
                }
            )

            report = await runner._assess_generated_test_suite(
                node_id="REQ-1",
                requirement_data={"id": "REQ-1", "description": "Show a greeting."},
                interfaces=_interfaces(),
                tests=_tests(),
                coverage_plan=_coverage_plan(),
            )

        self.assertTrue(report["blocking"], report)
        self.assertIn("red_gate_no_executable_batches", {item["code"] for item in report["issues"]})


class _TraceabilityStoreStub:
    def __init__(self, requirement: dict[str, object]) -> None:
        self.requirement = requirement
        self.interfaces: list[dict[str, object]] = []
        self.tests: list[dict[str, object]] = []
        self.contracts: dict[str, dict[str, object]] = {}

    def get_requirement(self, req_id: str) -> dict[str, object] | None:
        return self.requirement if req_id == self.requirement.get("id") else None

    def get_interface(self, interface_id: str) -> dict[str, object] | None:
        return next((item for item in self.interfaces if item.get("interface_id") == interface_id), None)

    def clear_node_design_artifacts(self, req_id: str) -> None:
        self.interfaces = [item for item in self.interfaces if req_id not in item.get("req_ids", [])]
        self.tests = [item for item in self.tests if item.get("req_id") != req_id]

    def upsert_interface(self, **item: object) -> None:
        self.interfaces.append(dict(item))

    def upsert_test(self, **item: object) -> None:
        self.tests.append(dict(item))

    def insert_call_edge(self, **item: object) -> None:
        del item

    def upsert_node_contract(self, req_id: str, content: dict[str, object]) -> None:
        self.contracts[req_id] = content


class _InterfaceDesigner:
    async def run(self, **kwargs: object) -> dict[str, object]:
        del kwargs
        return {
            "interfaces": [
                {
                    "interface_id": "REQ-1.FUNC.GREETING",
                    "type": "FUNC",
                    "responsibility": "Return a greeting for the supplied name.",
                    "callers": [],
                    "callees": [],
                }
            ],
            "files_written": [],
        }


class _OrchestrationGenerator:
    def __init__(self, workspace: str, *, repair_needed: bool, review_verdict: str) -> None:
        self.workspace = workspace
        self.repair_needed = repair_needed
        self.review_verdict = review_verdict
        self.run_calls: list[dict[str, object]] = []
        self.review_calls: list[dict[str, object]] = []

    async def run(self, **kwargs: object) -> tuple[list[dict[str, object]], str]:
        self.run_calls.append(dict(kwargs))
        test_file = Path(self.workspace) / "frontend" / "tests" / "greeting.test.ts"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        if self.repair_needed and len(self.run_calls) == 1:
            test_file.write_text(
                "import { expect, test } from 'vitest';\n"
                "test.skip('greets the requested user', () => { expect(true).toBe(true); });\n",
                encoding="utf-8",
            )
        else:
            test_file.write_text(
                "import { expect, test } from 'vitest';\n"
                "test('greets the requested user', () => { expect(greet('Ada')).toBe('Hello Ada'); });\n",
                encoding="utf-8",
            )
        return _tests(), '{"tests": 1}'

    def get_last_coverage_plan(self) -> list[dict[str, object]]:
        return _coverage_plan()

    async def review(self, **kwargs: object) -> dict[str, object]:
        self.review_calls.append(dict(kwargs))
        return {
            "verdict": self.review_verdict,
            "summary": "Adversarial review completed.",
            "issues": [],
            "repair_instructions": ["Replace the disabled test with an enabled behavioral assertion."],
        }


def _make_design_runner(
    workspace: str,
    generator: _OrchestrationGenerator,
) -> tuple[WorkflowPhaseRunner, list[tuple[object, ...]], list[tuple[str, dict[str, object]]]]:
    logs: list[tuple[object, ...]] = []
    session_updates: list[tuple[str, dict[str, object]]] = []
    runner = WorkflowPhaseRunner.__new__(WorkflowPhaseRunner)
    runner.workspace_path = workspace
    runner.requirement_path = str(Path(workspace) / "requirements.yaml")
    runner.app_type = "web"
    runner.interface_designer = _InterfaceDesigner()
    runner.test_generator = generator
    runner.test_driven_developer = SimpleNamespace()
    runner.log_cb = lambda *args: logs.append(args)
    runner.app_handler = SimpleNamespace(
        validate_test_path=lambda test_type, file_path: None,
        run_test_group=AsyncMock(
            return_value=(
                "Exit Code: 1\nSTDOUT:\nFAIL greeting.test.ts\n"
                "AssertionError: expected undefined to be 'Hello Ada'\n"
            )
        ),
    )
    runner._update_node_session = lambda node_id, payload: session_updates.append((node_id, payload))
    return runner, logs, session_updates


class TestQualityOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_high_risk_suite_runs_one_critic_without_repair_when_accepted(self) -> None:
        requirement = {
            "id": "REQ-1",
            "name": "Durable greeting",
            "description": "An authenticated user saves a greeting that persists after refresh.",
            "dependencies": ["REQ-AUTH"],
            "children_ids": [],
        }
        with tempfile.TemporaryDirectory() as workspace:
            generator = _OrchestrationGenerator(workspace, repair_needed=False, review_verdict="accept")
            runner, _, _ = _make_design_runner(workspace, generator)
            traceability = _TraceabilityStoreStub(requirement)

            async def passthrough_visual_analysis(**kwargs: object) -> dict[str, object]:
                return dict(kwargs["requirement_data"])

            with (
                patch("core.phases.get_runtime", return_value=SimpleNamespace(traceability=traceability)),
                patch(
                    "core.phases.analyze_and_attach_visual_references",
                    side_effect=passthrough_visual_analysis,
                ),
                patch.dict(os.environ, {"ARC_WORKSPACE_MODE": "scaffold"}),
            ):
                result = await runner.run_design_phase("REQ-1", requirement)

        self.assertTrue(result)
        self.assertEqual(len(generator.run_calls), 1)
        self.assertEqual(len(generator.review_calls), 1)
        self.assertEqual(traceability.contracts["REQ-1"]["test_critique"]["verdict"], "accept")
        self.assertEqual(traceability.contracts["REQ-1"]["test_quality"]["risk"]["tier"], "high")

    async def test_blocking_static_failure_gets_exactly_one_repair_pass(self) -> None:
        requirement = {
            "id": "REQ-1",
            "name": "Greeting",
            "description": "Show a greeting for the requested name.",
            "children_ids": [],
        }
        with tempfile.TemporaryDirectory() as workspace:
            generator = _OrchestrationGenerator(workspace, repair_needed=True, review_verdict="revise")
            runner, _, _ = _make_design_runner(workspace, generator)
            traceability = _TraceabilityStoreStub(requirement)

            async def passthrough_visual_analysis(**kwargs: object) -> dict[str, object]:
                return dict(kwargs["requirement_data"])

            with (
                patch("core.phases.get_runtime", return_value=SimpleNamespace(traceability=traceability)),
                patch(
                    "core.phases.analyze_and_attach_visual_references",
                    side_effect=passthrough_visual_analysis,
                ),
                patch.dict(os.environ, {"ARC_WORKSPACE_MODE": "scaffold"}),
            ):
                result = await runner.run_design_phase("REQ-1", requirement)

        self.assertTrue(result)
        self.assertEqual(len(generator.run_calls), 2)
        self.assertEqual(len(generator.review_calls), 1)
        self.assertIn("quality_feedback", generator.run_calls[1])
        self.assertTrue(traceability.contracts["REQ-1"]["test_quality"]["repair_attempted"])
        self.assertEqual(len(traceability.tests), 1)


if __name__ == "__main__":
    unittest.main()
