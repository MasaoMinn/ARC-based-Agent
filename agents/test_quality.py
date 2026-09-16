from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app_type_handler.test_results import parse_test_results


ALLOWED_COVERAGE_PRIORITIES = {"MUST", "SHOULD"}
ALLOWED_COVERAGE_KINDS = {
    "happy",
    "negative",
    "boundary",
    "state",
    "persistence",
    "authorization",
    "error",
    "accessibility",
}
ALLOWED_TEST_LAYERS = {"Unit", "Integration", "E2E"}

_RISK_TERM_GROUPS = {
    "auth-or-ownership": (
        "auth",
        "login",
        "logout",
        "session",
        "password",
        "permission",
        "authorization",
        "current user",
        "ownership",
    ),
    "durable-state": (
        "database",
        "persist",
        "saved",
        "refresh",
        "cart",
        "checkout",
        "order",
        "inventory",
        "account",
    ),
    "input-boundary": (
        "validate",
        "validation",
        "invalid",
        "required",
        "minimum",
        "maximum",
        "duplicate",
    ),
}

_INFRASTRUCTURE_FAILURE_MARKERS = (
    "cannot find module",
    "module not found",
    "failed to resolve import",
    "failed to load url",
    "syntaxerror",
    "transform failed",
    "test suite failed to run",
    "unknown fixture",
    "no test files",
    "frontend build failed",
    "backend runtime failed",
    "backend startup failed",
    "failed to start grouped e2e",
    "command timed out",
    "execution failed:",
    "enoent",
    "npm error",
)

_JS_ENABLED_TEST_PATTERN = re.compile(
    r"(?<![\w.])(?:it|test)\s*(?:\.(?:each|concurrent))?\s*\(",
    re.IGNORECASE,
)
_PYTHON_ENABLED_TEST_PATTERN = re.compile(r"(?m)^\s*(?:async\s+)?def\s+test_[A-Za-z0-9_]+\s*\(")
_JVM_ENABLED_TEST_PATTERN = re.compile(r"(?m)^\s*@Test\b")
_DISABLED_TEST_PATTERN = re.compile(r"\b(?:it|test|describe)\.(?:skip|todo|only)\s*\(", re.IGNORECASE)
_ONLY_TEST_PATTERN = re.compile(r"\b(?:it|test|describe)\.only\s*\(", re.IGNORECASE)
_ASSERTION_PATTERNS = (
    re.compile(r"\bexpect\s*\(", re.IGNORECASE),
    re.compile(r"\bassert(?:ion)?\b", re.IGNORECASE),
    re.compile(r"\bassert[A-Z][A-Za-z0-9_]*\s*\("),
    re.compile(r"\bshould\s*(?:\.|\()", re.IGNORECASE),
)
_TRIVIAL_ASSERTION_PATTERNS = (
    re.compile(r"expect\s*\(\s*true\s*\)\s*\.toBe\s*\(\s*true\s*\)", re.IGNORECASE),
    re.compile(r"expect\s*\(\s*false\s*\)\s*\.toBe\s*\(\s*false\s*\)", re.IGNORECASE),
    re.compile(r"(?m)^\s*assert\s+(?:True|1\s*==\s*1)\s*$"),
)


def normalize_coverage_plan_payload(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize a model response into stable, JSON-serializable coverage obligations."""

    raw_items = (payload or {}).get("coverage_plan")
    if raw_items is None:
        raw_items = (payload or {}).get("obligations")
    if not isinstance(raw_items, list):
        return []

    normalized: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        obligation_id = str(raw.get("obligation_id") or raw.get("id") or "").strip()
        if not obligation_id:
            continue
        priority = str(raw.get("priority") or "MUST").strip().upper()
        kind = str(raw.get("kind") or "happy").strip().lower()
        layer = canonical_layer(raw.get("layer")) or str(raw.get("layer") or "").strip()
        normalized.append(
            {
                **raw,
                "obligation_id": obligation_id,
                "source": str(raw.get("source") or "requirement").strip(),
                "priority": priority,
                "kind": kind,
                "description": str(raw.get("description") or "").strip(),
                "preconditions": normalize_string_list(raw.get("preconditions")),
                "action": str(raw.get("action") or "").strip(),
                "oracle": str(raw.get("oracle") or raw.get("expected_outcome") or "").strip(),
                "layer": layer,
                "scenario_ids": normalize_string_list(raw.get("scenario_ids")),
                "interface_ids": normalize_string_list(raw.get("interface_ids")),
            }
        )
    return normalized


def validate_coverage_plan(
    *,
    node_id: str,
    requirement_data: dict[str, Any],
    interfaces: list[dict[str, Any]],
    tests: list[dict[str, Any]],
    coverage_plan: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return deterministic coverage-contract issues without consulting product code."""

    issues: list[dict[str, Any]] = []
    if not coverage_plan:
        return [quality_issue("coverage_plan_missing", "error", "Generated tests have no structured coverage plan.")]

    interface_ids = {
        str(item.get("interface_id") or "").strip()
        for item in interfaces
        if isinstance(item, dict) and str(item.get("interface_id") or "").strip()
    }
    scenario_ids = requirement_scenario_ids(requirement_data)
    obligation_by_id: dict[str, dict[str, Any]] = {}

    for obligation in coverage_plan:
        obligation_id = str(obligation.get("obligation_id") or "").strip()
        if not obligation_id:
            issues.append(quality_issue("obligation_id_missing", "error", "A coverage obligation has no id."))
            continue
        if obligation_id in obligation_by_id:
            issues.append(
                quality_issue(
                    "obligation_id_duplicate",
                    "error",
                    f"Coverage obligation id `{obligation_id}` is duplicated.",
                    obligation_ids=[obligation_id],
                )
            )
            continue
        obligation_by_id[obligation_id] = obligation
        if node_id and node_id not in obligation_id:
            issues.append(
                quality_issue(
                    "obligation_id_unstable",
                    "warning",
                    f"Coverage obligation `{obligation_id}` should include node id `{node_id}`.",
                    obligation_ids=[obligation_id],
                )
            )
        priority = str(obligation.get("priority") or "").strip().upper()
        if priority not in ALLOWED_COVERAGE_PRIORITIES:
            issues.append(
                quality_issue(
                    "obligation_priority_invalid",
                    "error",
                    f"Coverage obligation `{obligation_id}` has invalid priority `{priority}`.",
                    obligation_ids=[obligation_id],
                )
            )
        kind = str(obligation.get("kind") or "").strip().lower()
        if kind not in ALLOWED_COVERAGE_KINDS:
            issues.append(
                quality_issue(
                    "obligation_kind_invalid",
                    "error",
                    f"Coverage obligation `{obligation_id}` has invalid kind `{kind}`.",
                    obligation_ids=[obligation_id],
                )
            )
        layer = canonical_layer(obligation.get("layer"))
        if layer is None:
            issues.append(
                quality_issue(
                    "obligation_layer_invalid",
                    "error",
                    f"Coverage obligation `{obligation_id}` must select Unit, Integration, or E2E.",
                    obligation_ids=[obligation_id],
                )
            )
        if not str(obligation.get("description") or "").strip():
            issues.append(
                quality_issue(
                    "obligation_description_missing",
                    "error",
                    f"Coverage obligation `{obligation_id}` has no behavior description.",
                    obligation_ids=[obligation_id],
                )
            )
        if not str(obligation.get("oracle") or "").strip():
            issues.append(
                quality_issue(
                    "obligation_oracle_missing",
                    "error",
                    f"Coverage obligation `{obligation_id}` has no observable oracle.",
                    obligation_ids=[obligation_id],
                )
            )

        unknown_scenarios = sorted(set(normalize_string_list(obligation.get("scenario_ids"))) - scenario_ids)
        if unknown_scenarios:
            issues.append(
                quality_issue(
                    "obligation_scenario_unknown",
                    "error",
                    f"Coverage obligation `{obligation_id}` references unknown scenario(s): {', '.join(unknown_scenarios)}.",
                    obligation_ids=[obligation_id],
                )
            )
        unknown_interfaces = sorted(set(normalize_string_list(obligation.get("interface_ids"))) - interface_ids)
        if interface_ids and unknown_interfaces:
            issues.append(
                quality_issue(
                    "obligation_interface_unknown",
                    "error",
                    f"Coverage obligation `{obligation_id}` references unknown interface(s): {', '.join(unknown_interfaces)}.",
                    obligation_ids=[obligation_id],
                )
            )

    mapped_obligation_ids: set[str] = set()
    e2e_scenario_ids: set[str] = set()
    for test in tests:
        test_id = str(test.get("test_id") or "").strip() or "<unnamed>"
        mapped = normalize_string_list(test.get("obligation_ids"))
        if not mapped:
            issues.append(
                quality_issue(
                    "test_obligation_mapping_missing",
                    "error",
                    f"Generated test `{test_id}` does not map to any coverage obligation.",
                    test_ids=[test_id],
                )
            )
        unknown = sorted(set(mapped) - set(obligation_by_id))
        if unknown:
            issues.append(
                quality_issue(
                    "test_obligation_unknown",
                    "error",
                    f"Generated test `{test_id}` references unknown obligation(s): {', '.join(unknown)}.",
                    test_ids=[test_id],
                    obligation_ids=unknown,
                )
            )
        mapped_obligation_ids.update(item for item in mapped if item in obligation_by_id)
        if canonical_layer(test.get("type")) == "E2E":
            e2e_scenario_ids.update(normalize_string_list(test.get("scenario_ids")))
            for obligation_id in mapped:
                obligation = obligation_by_id.get(obligation_id) or {}
                e2e_scenario_ids.update(normalize_string_list(obligation.get("scenario_ids")))

    for obligation_id, obligation in obligation_by_id.items():
        if str(obligation.get("priority") or "").strip().upper() == "MUST" and obligation_id not in mapped_obligation_ids:
            issues.append(
                quality_issue(
                    "must_obligation_uncovered",
                    "error",
                    f"MUST coverage obligation `{obligation_id}` is not mapped to a generated test.",
                    obligation_ids=[obligation_id],
                )
            )
            continue
        matching_layers = {
            canonical_layer(test.get("type"))
            for test in tests
            if obligation_id in normalize_string_list(test.get("obligation_ids"))
        }
        obligation_layer = canonical_layer(obligation.get("layer"))
        if obligation_id in mapped_obligation_ids and obligation_layer not in matching_layers:
            issues.append(
                quality_issue(
                    "obligation_layer_uncovered",
                    "error",
                    f"Coverage obligation `{obligation_id}` requires {obligation_layer}, but no mapped test uses that layer.",
                    obligation_ids=[obligation_id],
                )
            )

    missing_scenarios = sorted(scenario_ids - e2e_scenario_ids)
    if missing_scenarios:
        issues.append(
            quality_issue(
                "scenario_e2e_coverage_missing",
                "error",
                "Declared scenario(s) have no mapped E2E coverage: " + ", ".join(missing_scenarios) + ".",
            )
        )
    return issues


def inspect_test_artifacts(workspace_path: str, tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Perform cheap static checks that reject vacuous or disabled test files."""

    workspace = Path(workspace_path).expanduser().resolve()
    issues: list[dict[str, Any]] = []
    inspected_paths: set[str] = set()
    for test in tests:
        test_id = str(test.get("test_id") or "").strip() or "<unnamed>"
        relative = str(test.get("file_path") or "").strip().replace("\\", "/")
        if not relative or relative in inspected_paths:
            continue
        inspected_paths.add(relative)
        candidate = (workspace / relative).resolve()
        try:
            candidate.relative_to(workspace)
        except ValueError:
            issues.append(
                quality_issue(
                    "test_file_outside_workspace",
                    "error",
                    f"Generated test `{test_id}` resolves outside the workspace: {relative}.",
                    test_ids=[test_id],
                )
            )
            continue
        if not candidate.is_file():
            issues.append(
                quality_issue(
                    "test_file_missing",
                    "error",
                    f"Generated test `{test_id}` points to a file that was not written: {relative}.",
                    test_ids=[test_id],
                )
            )
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            issues.append(
                quality_issue(
                    "test_file_unreadable",
                    "error",
                    f"Generated test `{test_id}` cannot be read: {exc}.",
                    test_ids=[test_id],
                )
            )
            continue
        if not content.strip():
            issues.append(
                quality_issue(
                    "test_file_empty",
                    "error",
                    f"Generated test file `{relative}` is empty.",
                    test_ids=[test_id],
                )
            )
            continue

        enabled_count = _enabled_test_count(candidate.suffix.lower(), content)
        if enabled_count == 0:
            issues.append(
                quality_issue(
                    "enabled_test_missing",
                    "error",
                    f"Generated test file `{relative}` contains no recognizable enabled test case.",
                    test_ids=[test_id],
                )
            )
        if _ONLY_TEST_PATTERN.search(content):
            issues.append(
                quality_issue(
                    "focused_test_committed",
                    "error",
                    f"Generated test file `{relative}` contains `.only`, which would suppress other coverage.",
                    test_ids=[test_id],
                )
            )

        assertion_count = sum(len(pattern.findall(content)) for pattern in _ASSERTION_PATTERNS)
        if assertion_count == 0:
            issues.append(
                quality_issue(
                    "assertion_missing",
                    "error",
                    f"Generated test file `{relative}` contains no recognizable behavioral assertion.",
                    test_ids=[test_id],
                )
            )
        elif assertion_count == 1 and any(pattern.search(content) for pattern in _TRIVIAL_ASSERTION_PATTERNS):
            issues.append(
                quality_issue(
                    "assertion_trivial",
                    "error",
                    f"Generated test file `{relative}` only contains an unconditional assertion.",
                    test_ids=[test_id],
                )
            )

        disabled_count = len(_DISABLED_TEST_PATTERN.findall(content))
        if enabled_count == 0 and disabled_count:
            issues.append(
                quality_issue(
                    "tests_disabled_only",
                    "error",
                    f"Generated test file `{relative}` contains only skipped, todo, or focused test declarations.",
                    test_ids=[test_id],
                )
            )
    return issues


def classify_red_gate_output(test_output: str) -> dict[str, Any]:
    """Classify whether a pre-implementation run is a useful red test or a broken gate."""

    parsed = parse_test_results(test_output)
    exit_code = int(parsed.get("exit_code", -1))
    if parsed.get("empty_run"):
        return {
            "status": "invalid",
            "exit_code": exit_code,
            "reason": str(parsed.get("empty_run_reason") or "No enabled tests executed."),
        }
    if exit_code == 0:
        return {
            "status": "unexpected_pass",
            "exit_code": exit_code,
            "reason": "The generated tests already pass before the node implementation stage.",
        }
    if exit_code < 0:
        return {
            "status": "invalid",
            "exit_code": exit_code,
            "reason": "The test runner did not return a parseable exit code.",
        }
    normalized = (test_output or "").casefold()
    marker = next((item for item in _INFRASTRUCTURE_FAILURE_MARKERS if item in normalized), "")
    if marker:
        return {
            "status": "invalid",
            "exit_code": exit_code,
            "reason": f"The red run failed in test infrastructure or collection (`{marker}`), not at a behavioral oracle.",
        }
    return {
        "status": "valid_red",
        "exit_code": exit_code,
        "reason": "At least one enabled test reached a behavioral failure before implementation.",
    }


def assess_requirement_risk(
    requirement_data: dict[str, Any],
    interfaces: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estimate when an adversarial critic is worth its additional model call."""

    score = 0
    reasons: list[str] = []
    scenarios = [item for item in requirement_data.get("scenarios") or [] if isinstance(item, dict)]
    if scenarios:
        scenario_points = min(4, len(scenarios) * 2)
        score += scenario_points
        reasons.append(f"{len(scenarios)} declared scenario(s)")
    dependencies = normalize_string_list(requirement_data.get("dependencies"))
    if dependencies:
        score += 2
        reasons.append("cross-node dependencies")
    interface_types = {
        str(item.get("type") or "").strip().upper()
        for item in interfaces
        if isinstance(item, dict) and str(item.get("type") or "").strip()
    }
    if len(interface_types) >= 3:
        score += 2
        reasons.append("three-or-more connected interface layers")
    elif len(interface_types) == 2:
        score += 1
        reasons.append("multi-layer interface contract")

    text = json.dumps(requirement_data, ensure_ascii=False, default=str).casefold()
    for label, terms in _RISK_TERM_GROUPS.items():
        if any(term in text for term in terms):
            score += 2
            reasons.append(label)
    tier = "high" if score >= 6 else "medium" if score >= 3 else "low"
    return {"score": score, "tier": tier, "reasons": reasons}


def has_error_issues(issues: list[dict[str, Any]]) -> bool:
    return any(str(item.get("severity") or "").lower() == "error" for item in issues)


def requirement_scenario_ids(requirement_data: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for scenario in requirement_data.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        key = str(scenario.get("scenario_id") or scenario.get("id") or scenario.get("name") or "").strip()
        if key:
            result.add(key)
    return result


def quality_issue(
    code: str,
    severity: str,
    message: str,
    *,
    test_ids: list[str] | None = None,
    obligation_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "test_ids": test_ids or [],
        "obligation_ids": obligation_ids or [],
    }


def canonical_layer(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    for layer in ALLOWED_TEST_LAYERS:
        if normalized == layer.lower():
            return layer
    return None


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _enabled_test_count(suffix: str, content: str) -> int:
    if suffix == ".py":
        return len(_PYTHON_ENABLED_TEST_PATTERN.findall(content))
    if suffix in {".java", ".kt", ".kts"}:
        return len(_JVM_ENABLED_TEST_PATTERN.findall(content))
    return len(_JS_ENABLED_TEST_PATTERN.findall(content))
