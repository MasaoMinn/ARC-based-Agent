from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from core.workflow import ARCWorkflowManager


class WorkflowTaskErrorBoundaryTests(unittest.TestCase):
    def test_agent_exception_becomes_failed_task_result(self) -> None:
        messages: list[tuple[str, str, str | None, str | None]] = []

        async def log_cb(
            agent_name: str,
            message: str,
            status: str | None = None,
            node_id: str | None = None,
        ) -> None:
            messages.append((agent_name, message, status, node_id))

        async def raise_from_agent(_task: dict[str, str]) -> bool:
            raise RuntimeError("synthetic model failure")

        with tempfile.TemporaryDirectory() as workspace:
            manager = object.__new__(ARCWorkflowManager)
            manager.workspace_path = str(Path(workspace))
            manager.log_cb = log_cb
            manager._run_task = raise_from_agent  # type: ignore[method-assign]

            result = asyncio.run(
                manager._run_task_with_error_boundary(
                    {"node_id": "REQ-1", "phase": "DESIGN"}
                )
            )

            self.assertFalse(result)
            self.assertTrue(
                any(
                    agent == "Compiler"
                    and status == "error"
                    and node_id == "REQ-1"
                    and "synthetic model failure" in message
                    for agent, message, status, node_id in messages
                )
            )

    def test_system_exit_is_not_swallowed(self) -> None:
        async def raise_system_exit(_task: dict[str, str]) -> bool:
            raise SystemExit(7)

        manager = object.__new__(ARCWorkflowManager)
        manager.workspace_path = "."
        manager.log_cb = None
        manager._run_task = raise_system_exit  # type: ignore[method-assign]

        with self.assertRaises(SystemExit) as raised:
            asyncio.run(
                manager._run_task_with_error_boundary(
                    {"node_id": "REQ-1", "phase": "DESIGN"}
                )
            )
        self.assertEqual(raised.exception.code, 7)


if __name__ == "__main__":
    unittest.main()
