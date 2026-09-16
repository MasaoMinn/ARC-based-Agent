from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.phases import WorkflowPhaseRunner


class _TraceabilityStub:
    def __init__(self, *, tests=None, interfaces=None) -> None:
        self.tests = list(tests or [])
        self.interfaces = list(interfaces or [])
        self.pass_status_updates = []

    def get_interface(self, interface_id: str):
        del interface_id
        return None

    def get_requirement(self, req_id: str):
        del req_id
        return None

    def list_interfaces(self, *, req_id: str | None = None):
        del req_id
        return list(self.interfaces)

    def list_tests(self, *, req_id: str | None = None):
        del req_id
        return list(self.tests)

    def set_test_pass_statuses(self, statuses):
        self.pass_status_updates.append(dict(statuses))


class _InterfaceDesignerStub:
    async def run(self, **kwargs):
        del kwargs
        return {"interfaces": [], "files_written": []}


class _TestGeneratorStub:
    def __init__(self, tests=None) -> None:
        self.tests = list(tests or [])

    async def run(self, **kwargs):
        del kwargs
        return list(self.tests), '{"tests": []}'


class _TestDrivenDeveloperStub:
    def __init__(self) -> None:
        self.last_result = ""

    async def run(self, *, run_tests_executor, test_type, **kwargs):
        del kwargs
        self.last_result = await run_tests_executor(test_type, None)
        return self.last_result

    def get_last_verifier_report(self) -> str:
        return self.last_result


def _make_runner(traceability: _TraceabilityStub):
    logs = []
    session_updates = []

    def log_cb(agent, message, status=None, node_id=None):
        logs.append((agent, message, status, node_id))

    runner = WorkflowPhaseRunner.__new__(WorkflowPhaseRunner)
    runner.workspace_path = "."
    runner.requirement_path = "requirements.yaml"
    runner.app_type = "web"
    runner.interface_designer = _InterfaceDesignerStub()
    runner.test_generator = _TestGeneratorStub()
    runner.test_driven_developer = SimpleNamespace()
    runner.log_cb = log_cb
    runner.app_handler = SimpleNamespace()
    runner._update_node_session = lambda node_id, payload: session_updates.append((node_id, payload))
    runtime = SimpleNamespace(traceability=traceability)
    return runner, runtime, logs, session_updates


class EmptyTestGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_design_fails_when_leaf_test_manifest_is_empty(self) -> None:
        runner, runtime, logs, session_updates = _make_runner(_TraceabilityStub())

        async def passthrough_visual_analysis(**kwargs):
            return kwargs["requirement_data"]

        with (
            patch("core.phases.get_runtime", return_value=runtime),
            patch("core.phases.analyze_and_attach_visual_references", side_effect=passthrough_visual_analysis),
        ):
            result = await runner.run_design_phase(
                "REQ-LEAF",
                {"id": "REQ-LEAF", "name": "Leaf", "children_ids": []},
            )

        self.assertFalse(result)
        self.assertTrue(any(status == "error" and "empty test manifest" in message for _, message, status, _ in logs))
        self.assertEqual(session_updates[-1][1]["phase_status"], {"design": "failed", "test": "failed"})

    async def test_design_fails_when_manifest_contains_no_valid_artifacts(self) -> None:
        runner, runtime, logs, session_updates = _make_runner(_TraceabilityStub())
        runner.test_generator = _TestGeneratorStub([{"type": "Unit", "file_path": "frontend/tests/leaf.test.ts"}])

        async def passthrough_visual_analysis(**kwargs):
            return kwargs["requirement_data"]

        with (
            patch("core.phases.get_runtime", return_value=runtime),
            patch("core.phases.analyze_and_attach_visual_references", side_effect=passthrough_visual_analysis),
        ):
            result = await runner.run_design_phase(
                "REQ-LEAF",
                {"id": "REQ-LEAF", "name": "Leaf", "children_ids": []},
            )

        self.assertFalse(result)
        self.assertTrue(any(status == "error" and "no valid test artifacts" in message for _, message, status, _ in logs))
        self.assertEqual(session_updates[-1][1]["phase_status"], {"design": "failed", "test": "failed"})

    async def test_intent_based_test_generation_rejects_an_empty_manifest(self) -> None:
        runner, runtime, logs, _ = _make_runner(_TraceabilityStub())

        with patch("core.phases.get_runtime", return_value=runtime):
            result = await runner.run_test_generation_phase(
                "REQ-LEAF",
                {"id": "REQ-LEAF", "name": "Leaf", "children_ids": []},
                intent="Add edge-case coverage",
            )

        self.assertFalse(result)
        self.assertTrue(any(status == "error" and "empty manifest" in message for _, message, status, _ in logs))

    async def test_implementation_fails_when_leaf_has_no_registered_tests(self) -> None:
        runner, runtime, logs, session_updates = _make_runner(
            _TraceabilityStub(interfaces=[{"interface_id": "REQ-LEAF.UI"}])
        )

        with patch("core.phases.get_runtime", return_value=runtime):
            result = await runner.run_implement_phase(
                "REQ-LEAF",
                {"id": "REQ-LEAF", "children_ids": []},
            )

        self.assertFalse(result)
        self.assertTrue(any(status == "error" and "No node-local tests" in message for _, message, status, _ in logs))
        self.assertEqual(session_updates[-1][1]["phase_status"], {"implement": "failed"})
        self.assertEqual(session_updates[-1][1]["result_state"], "FAILED")

    async def test_implementation_fails_when_registered_tests_have_no_supported_layer(self) -> None:
        runner, runtime, logs, session_updates = _make_runner(
            _TraceabilityStub(
                tests=[{"test_id": "REQ-LEAF.TEST", "type": "Unknown", "file_path": "tests/leaf.test.ts"}]
            )
        )

        with patch("core.phases.get_runtime", return_value=runtime):
            result = await runner.run_implement_phase(
                "REQ-LEAF",
                {"id": "REQ-LEAF", "children_ids": []},
            )

        self.assertFalse(result)
        self.assertTrue(any(status == "error" and "No executable" in message for _, message, status, _ in logs))
        self.assertEqual(session_updates[-1][1]["phase_status"], {"implement": "failed"})

    async def test_supported_layer_without_an_executable_file_cannot_pass(self) -> None:
        runner, runtime, logs, session_updates = _make_runner(
            _TraceabilityStub(tests=[{"test_id": "REQ-LEAF.TEST", "type": "Unit", "file_path": ""}])
        )
        runner.test_driven_developer = _TestDrivenDeveloperStub()

        with (
            patch("core.phases.get_runtime", return_value=runtime),
            patch("core.phases.sessions.load_node_session", return_value={}),
        ):
            result = await runner.run_implement_phase(
                "REQ-LEAF",
                {"id": "REQ-LEAF", "children_ids": []},
            )

        self.assertFalse(result)
        self.assertIn("No executable test files", runner.test_driven_developer.last_result)
        self.assertTrue(any(status == "error" and "did not pass" in message for _, message, status, _ in logs))
        self.assertEqual(session_updates[-1][1]["phase_status"], {"implement": "failed"})

    async def test_non_leaf_implementation_keeps_its_existing_test_exemption(self) -> None:
        runner, runtime, _, session_updates = _make_runner(_TraceabilityStub())

        with patch("core.phases.get_runtime", return_value=runtime):
            result = await runner.run_implement_phase(
                "REQ-PARENT",
                {"id": "REQ-PARENT", "children_ids": ["REQ-LEAF"]},
            )

        self.assertTrue(result)
        self.assertEqual(session_updates[-1][1]["phase_status"], {"implement": "completed"})


if __name__ == "__main__":
    unittest.main()
