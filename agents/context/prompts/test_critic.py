from __future__ import annotations

import json
from typing import Any

from agents.context.prompts.common import (
    app_runtime_contract,
    compiler_background,
    reasoning_reflection_policy,
    response_contract,
    section,
    task_context_block,
    whole_app_policy,
    workspace_tool_policy,
)


def get_system_prompt() -> str:
    return "\n\n".join(
        [
            compiler_background(),
            reasoning_reflection_policy(),
            whole_app_policy(),
            section(
                "TestCritic Role",
                [
                    "Act as an adversarial, read-only reviewer of generated tests for one executable leaf requirement node.",
                    "Judge whether plausible incorrect implementations could still pass the suite; do not reward test count or implementation-shaped assertions.",
                    "Use the requirement, declared scenarios, interface contract, coverage plan, manifest, deterministic quality findings, and red-gate evidence as the complete authority.",
                    "You may read only the listed generated test files and directly relevant test harness files when needed. Do not inspect product implementation, edit files, run tests/builds, or invent hidden evaluator behavior.",
                    "Accept only when every explicit MUST behavior has a meaningful oracle and the suite would reject disconnected UI state, fake success responses, missing persistence, missing authorization, and omitted boundary behavior whenever those risks are requirement-owned.",
                    "Request revision for over-specified selectors, labels, routes, payload fields, fixtures, or behavior that the requirement and interface contract do not justify.",
                    "Treat a pre-implementation pass as suspicious. Accept it only when the supplied evidence clearly shows the requirement was already implemented in an evolution baseline and the assertions remain discriminating.",
                    "Return concise repair instructions rather than replacement test code.",
                ],
            ),
            app_runtime_contract(),
            workspace_tool_policy(),
            response_contract(),
        ]
    )


def get_user_prompt(
    *,
    node_id: str,
    requirement_data: dict[str, Any],
    dynamic_context: str,
    interface_contract: str,
    coverage_plan: list[dict[str, Any]],
    tests: list[dict[str, Any]],
    quality_report: dict[str, Any],
) -> str:
    extra_sections = []
    if interface_contract.strip():
        extra_sections.append(f"### Current Interface Contract\n{interface_contract.strip()}")
    extra_sections.extend(
        [
            "### Proposed Coverage Plan\n```json\n"
            + json.dumps(coverage_plan, ensure_ascii=False, indent=2, default=str)
            + "\n```",
            "### Generated Test Manifest\n```json\n"
            + json.dumps(tests, ensure_ascii=False, indent=2, default=str)
            + "\n```",
            "### Deterministic Quality and Red-Gate Report\n```json\n"
            + json.dumps(quality_report, ensure_ascii=False, indent=2, default=str)
            + "\n```",
            section(
                "Task",
                [
                    "Read the generated test files named in the manifest when needed, then identify realistic requirement-violating implementations that could still pass.",
                    "Check requirement-to-obligation-to-test traceability, oracle strength, negative/boundary/state coverage, and whether mocks bypass an owned runtime boundary.",
                    "Set `verdict` to `accept` only when no material repair is needed; otherwise use `revise` and give focused repair instructions tied to issue and obligation ids.",
                    "Do not propose unrelated extra product behavior and do not make tests brittle by asserting details absent from the requirement or interface contract.",
                    "Return `verdict`, `summary`, `issues`, and `repair_instructions`.",
                ],
            ),
        ]
    )
    return task_context_block(
        node_id=node_id,
        dynamic_context=dynamic_context,
        requirement_data=requirement_data,
        extra_sections=extra_sections,
    )
