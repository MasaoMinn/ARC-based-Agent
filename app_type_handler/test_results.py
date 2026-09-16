from __future__ import annotations

import re
from typing import Any


def parse_test_results(test_output: str) -> dict[str, Any]:
    """Parse ARC test-run output into a compact status structure."""

    result: dict[str, Any] = {
        "passed": [],
        "failed": [],
        "exit_code": -1,
        "sub_batches": [],
        "empty_run": False,
        "empty_run_reason": "",
    }
    output = test_output or ""
    for line in output.splitlines():
        if "Exit Code:" not in line:
            continue
        try:
            result["exit_code"] = int(line.split("Exit Code:", 1)[1].strip())
        except ValueError:
            result["exit_code"] = -1
        break

    test_file_sections = re.findall(
        r"Test File:\s*(.+?)\r?\nTest Results:\r?\n(.*?)(?=\r?\nTest File: |\Z)",
        output,
        re.DOTALL,
    )
    for file_path, raw_section in test_file_sections:
        result["sub_batches"].append(
            {
                "requested_files": [file_path.strip().replace("\\", "/")],
                "exit_code": _extract_exit_code(raw_section),
                "raw_output": raw_section.strip(),
            }
        )

    if not result["sub_batches"]:
        requested_files = [
            line.split("-", 1)[1].strip().replace("\\", "/")
            for line in output.splitlines()
            if line.startswith("- ")
        ]
        for label in ("Backend Vitest Batch", "Frontend Vitest Batch", "Playwright E2E Batch"):
            section = _extract_labeled_section(output, label)
            if not section:
                continue
            result["sub_batches"].append(
                {
                    "requested_files": requested_files,
                    "exit_code": _extract_exit_code(section),
                    "raw_output": section.strip(),
                }
            )

    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(("PASS ", "✓", "√", "✔")):
            result["passed"].append(stripped)
        elif stripped.startswith(("FAIL ", "✗", "×", "✕")) or " FAILED" in stripped:
            result["failed"].append(stripped)
    empty_run_reason = detect_empty_test_run(output)
    result["empty_run"] = bool(empty_run_reason)
    result["empty_run_reason"] = empty_run_reason
    return result


def detect_empty_test_run(test_output: str) -> str:
    """Return a reason when a runner completed without executing an enabled test."""

    output = test_output or ""
    explicit_empty_patterns = (
        r"(?im)^\s*(?:error:\s*)?no tests?(?: files?| suites?)? (?:found|collected|executed|were run)[^\r\n]*$",
        r"(?im)^\s*ran\s+0\s+tests?\b[^\r\n]*$",
        r"(?im)^\s*0\s+tests?\s+(?:completed|executed|run)\b[^\r\n]*$",
        r"(?im)^\s*tests?\s+0(?:\s|$)[^\r\n]*$",
    )
    for pattern in explicit_empty_patterns:
        match = re.search(pattern, output)
        if match:
            return match.group(0).strip()

    # Vitest summarizes enabled outcomes on a line beginning with `Tests`.
    # A non-zero total containing only skipped/todo cases is still an empty gate.
    for line in output.splitlines():
        stripped = line.strip()
        if not re.match(r"^Tests?\s+", stripped, re.IGNORECASE):
            continue
        total_match = re.search(r"\((\d+)\)\s*$", stripped)
        if not total_match or int(total_match.group(1)) <= 0:
            continue
        enabled_outcomes = re.findall(r"\b(\d+)\s+(?:passed|failed)\b", stripped, re.IGNORECASE)
        if not enabled_outcomes or sum(int(value) for value in enabled_outcomes) == 0:
            return stripped

    # Playwright's list reporter can finish successfully with only skipped tests.
    summary_lines = [line.strip() for line in output.splitlines() if line.strip()]
    skipped_only = any(re.match(r"^\d+\s+skipped\b", line, re.IGNORECASE) for line in summary_lines)
    enabled_summary = any(re.match(r"^\d+\s+(?:passed|failed)\b", line, re.IGNORECASE) for line in summary_lines)
    if skipped_only and not enabled_summary:
        return "The test runner reported only skipped tests."
    return ""


def enforce_non_empty_test_run(test_output: str) -> str:
    """Convert an exit-0 empty run into a hard failure understood by all callers."""

    parsed = parse_test_results(test_output)
    if parsed.get("exit_code") != 0 or not parsed.get("empty_run"):
        return test_output

    guarded_output, replacements = re.subn(
        r"(?m)^(\s*Exit Code:\s*)0\s*$",
        r"\g<1>1",
        test_output or "",
        count=1,
    )
    if not replacements:
        guarded_output = f"Exit Code: 1\n{guarded_output}"
    reason = str(parsed.get("empty_run_reason") or "No enabled tests were executed.").strip()
    return (
        f"{guarded_output.rstrip()}\n\n"
        "ARC_EMPTY_TEST_GUARD:\n"
        f"{reason}\n"
        "A successful test gate requires at least one enabled test to execute.\n"
    )


def _extract_exit_code(output: str) -> int:
    for line in (output or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("Exit Code:"):
            continue
        try:
            return int(stripped.split("Exit Code:", 1)[1].strip())
        except ValueError:
            return -1
    return -1


def _extract_labeled_section(output: str, label: str) -> str:
    pattern = rf"=== {re.escape(label)} ===\r?\n(.*?)(?=\r?\n=== |\Z)"
    match = re.search(pattern, output or "", re.DOTALL)
    return match.group(1).strip() if match else ""
