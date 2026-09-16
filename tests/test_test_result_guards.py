from __future__ import annotations

import unittest

from app_type_handler.test_results import enforce_non_empty_test_run, parse_test_results


class TestResultGuardTests(unittest.TestCase):
    def test_explicit_zero_test_success_is_rewritten_as_failure(self) -> None:
        guarded = enforce_non_empty_test_run("Exit Code: 0\nSTDOUT:\nRan 0 tests in 0.000s\nOK\n")

        self.assertEqual(parse_test_results(guarded)["exit_code"], 1)
        self.assertIn("ARC_EMPTY_TEST_GUARD", guarded)

    def test_vitest_skipped_only_success_is_rewritten_as_failure(self) -> None:
        guarded = enforce_non_empty_test_run("Exit Code: 0\nSTDOUT:\nTests  2 skipped (2)\n")

        parsed = parse_test_results(guarded)
        self.assertEqual(parsed["exit_code"], 1)
        self.assertTrue(parsed["empty_run"])

    def test_playwright_skipped_only_success_is_rewritten_as_failure(self) -> None:
        guarded = enforce_non_empty_test_run("Exit Code: 0\nSTDOUT:\n2 skipped\n")

        self.assertEqual(parse_test_results(guarded)["exit_code"], 1)

    def test_real_executed_test_success_is_preserved(self) -> None:
        output = "Exit Code: 0\nSTDOUT:\nTest Files  1 passed (1)\nTests  3 passed (3)\n"

        self.assertEqual(enforce_non_empty_test_run(output), output)
        parsed = parse_test_results(output)
        self.assertEqual(parsed["exit_code"], 0)
        self.assertFalse(parsed["empty_run"])


if __name__ == "__main__":
    unittest.main()
