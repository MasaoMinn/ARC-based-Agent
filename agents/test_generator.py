from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field

from agents.context.pipeline import context_pipeline
from agents.context.prompts.common import stage_skill_activation_policy
from agents.context.prompts.test_critic import get_system_prompt as get_critic_system_prompt
from agents.context.prompts.test_critic import get_user_prompt as get_critic_user_prompt
from agents.context.prompts.test_generator import get_system_prompt, get_user_prompt
from agents.results import normalize_test_manifest_payload
from agents.runtime.contracts import AgentRuntimeContext
from agents.runtime.factory import build_stage_agent
from agents.runtime.runners import ainvoke_stage_agent
from agents.skills.selection import SKILLS_SOURCE, test_generation_skills
from agents.test_quality import normalize_coverage_plan_payload, normalize_string_list
from agents.tools.traceability import build_traceability_tools


LogCallback = Callable[[str, str, str | None, str | None], Awaitable[None] | None]


class CoverageObligation(BaseModel):
    obligation_id: str = Field(description="Stable id including the current requirement node id.")
    source: str = Field(description="Requirement, scenario, or interface evidence that created this obligation.")
    priority: Literal["MUST", "SHOULD"] = Field(description="MUST for explicit behavior; SHOULD for optional resilience coverage.")
    kind: Literal[
        "happy",
        "negative",
        "boundary",
        "state",
        "persistence",
        "authorization",
        "error",
        "accessibility",
    ] = Field(description="Behavioral risk dimension exercised by the obligation.")
    description: str = Field(description="Requirement-owned behavior under test.")
    preconditions: list[str] = Field(default_factory=list, description="Required GIVEN state.")
    action: str = Field(description="User or runtime action under test.")
    oracle: str = Field(description="Observable outcome that distinguishes correct from incorrect behavior.")
    layer: Literal["Unit", "Integration", "E2E"] = Field(description="Required execution layer.")
    scenario_ids: list[str] = Field(default_factory=list, description="Declared scenarios covered by this obligation.")
    interface_ids: list[str] = Field(default_factory=list, description="Owned or reused interfaces exercised by this obligation.")


class TestManifestItem(BaseModel):
    test_id: str = Field(description="Stable test artifact id.")
    req_id: str = Field(description="Requirement node id covered by this test.")
    obligation_ids: list[str] = Field(min_length=1, description="Coverage obligations executed by this test artifact.")
    scenario_ids: list[str] = Field(default_factory=list, description="Declared scenarios exercised by this test artifact.")
    interface_ids: list[str] = Field(default_factory=list, description="Covered interface ids.")
    type: str = Field(description="Unit, Integration, or E2E.")
    file_path: str = Field(description="Workspace-relative test file path.")
    first_line: str = Field(default="", description="Exact first line in the written test file.")


class TestGenerationResponse(BaseModel):
    summary: str = Field(default="", description="Short test-design summary.")
    coverage_plan: list[CoverageObligation] = Field(
        min_length=1,
        description="Machine-checkable requirement-to-test coverage obligations.",
    )
    tests: list[TestManifestItem] = Field(
        default_factory=list,
        min_length=1,
        description="Non-empty generated test manifest for the executable leaf requirement node.",
    )
    files_written: list[str] = Field(default_factory=list, description="Workspace-relative files written or edited.")


class TestCritiqueIssue(BaseModel):
    issue_id: str = Field(description="Stable short issue identifier.")
    severity: Literal["error", "warning"] = Field(description="Whether the suite must be revised.")
    description: str = Field(description="Concrete weakness or over-constraint in the proposed suite.")
    obligation_ids: list[str] = Field(default_factory=list, description="Affected coverage obligations.")


class TestCritiqueResponse(BaseModel):
    verdict: Literal["accept", "revise"] = Field(description="Whether the generated suite is strong enough to keep.")
    summary: str = Field(default="", description="Concise adversarial review conclusion.")
    issues: list[TestCritiqueIssue] = Field(default_factory=list, description="Material test-quality findings.")
    repair_instructions: list[str] = Field(default_factory=list, description="Focused instructions for one bounded repair pass.")


class TestGenerator:
    """Deep-agents based test-generation stage adapter."""

    agent_name = "TestGenerator"

    def __init__(
        self,
        log_cb: LogCallback | None = None,
        *,
        model: str | object | None = None,
        workspace_root: str | None = None,
        requirement_path: str | None = None,
        app_type: str | None = None,
    ) -> None:
        self.log_cb = log_cb
        self.model = model or os.environ.get("MODEL", "openai:gpt-5.4")
        self.workspace_root = workspace_root
        self.requirement_path = requirement_path or ""
        self.app_type = app_type
        self.critic_model = os.environ.get("ARC_TEST_CRITIC_MODEL", "").strip() or self.model
        self._last_coverage_plan: list[dict[str, Any]] = []
        self._last_generation_payload: dict[str, Any] = {}

    async def run(
        self,
        node_id: str,
        requirement_data: dict[str, Any],
        *,
        preloaded_source: str | None = None,
        test_intent: str = "",
        replace_test_id: str | None = None,
        quality_feedback: str = "",
        prior_manifest: list[dict[str, Any]] | None = None,
        prior_coverage_plan: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]] | None, str]:
        workspace_root = str(Path(
            self.workspace_root
            or context_pipeline.config.workspace_dir
            or os.environ.get("ARC_WORKSPACE_ROOT")
            or os.getcwd()
        ).expanduser().resolve())
        app_type = (self.app_type or context_pipeline.config.app_type or os.environ.get("ARC_APP_TYPE") or "web").strip().lower()
        selected_skill_names = test_generation_skills(requirement_data)
        context_pipeline.configure(
            workspace_dir=workspace_root,
            app_type=app_type,
        )
        static_context, dynamic_context = context_pipeline.build_agent_context_split(
            node_id=node_id,
            agent_type=self.agent_name,
            preloaded_source=preloaded_source,
        )
        interface_contract = context_pipeline.get_interface_contract_context(node_id)
        context_text = "\n\n".join(part.strip() for part in (static_context, dynamic_context) if part.strip())
        agent = build_stage_agent(
            name="test_generator",
            stage="test_generation",
            model=self.model,
            system_prompt="\n\n".join(
                [get_system_prompt(), stage_skill_activation_policy(selected_skill_names)]
            ),
            response_format=TestGenerationResponse,
            workspace_root=workspace_root,
            writable_roots=[workspace_root],
            skills=[SKILLS_SOURCE] if selected_skill_names else [],
            permitted_skill_names=selected_skill_names,
            memory=[],
            tools=build_traceability_tools(node_id=node_id, log_cb=self.log_cb),
        )

        message = get_user_prompt(
            node_id=node_id,
            requirement_data=requirement_data,
            dynamic_context=context_text,
            interface_contract=interface_contract,
            test_intent=test_intent,
            replace_test_id=replace_test_id,
            quality_feedback=quality_feedback,
            prior_manifest=prior_manifest,
            prior_coverage_plan=prior_coverage_plan,
        )
        await self._log(f"skill-permitted: {', '.join(selected_skill_names) or 'none'}", node_id=node_id)
        await self._log("Invoking test generation.", node_id=node_id)
        raw_payload = await ainvoke_stage_agent(
            agent,
            message=message,
            context=AgentRuntimeContext(
                node_id=node_id,
                phase="DESIGN",
                app_type=app_type,
                workspace_root=workspace_root,
                requirement_path=self.requirement_path,
            ),
            thread_id=f"{node_id}:DESIGN:TestGenerator" + (":quality-repair" if quality_feedback.strip() else ""),
            label=self.agent_name,
            log_cb=self.log_cb,
        )
        tests = normalize_test_manifest_payload(raw_payload)
        self._last_coverage_plan = normalize_coverage_plan_payload(raw_payload)
        self._last_generation_payload = dict(raw_payload or {})
        output_text = json.dumps(raw_payload or {"tests": tests}, ensure_ascii=False)
        await self._log(
            f"Test generation returned {len(tests)} test artifact(s) and "
            f"{len(self._last_coverage_plan)} coverage obligation(s).",
            node_id=node_id,
        )
        return tests, output_text

    def get_last_coverage_plan(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._last_coverage_plan]

    def get_last_generation_payload(self) -> dict[str, Any]:
        return dict(self._last_generation_payload)

    async def review(
        self,
        *,
        node_id: str,
        requirement_data: dict[str, Any],
        coverage_plan: list[dict[str, Any]],
        tests: list[dict[str, Any]],
        quality_report: dict[str, Any],
    ) -> dict[str, Any]:
        """Run one read-only adversarial review of a generated suite."""

        workspace_root = str(Path(
            self.workspace_root
            or context_pipeline.config.workspace_dir
            or os.environ.get("ARC_WORKSPACE_ROOT")
            or os.getcwd()
        ).expanduser().resolve())
        app_type = (self.app_type or context_pipeline.config.app_type or os.environ.get("ARC_APP_TYPE") or "web").strip().lower()
        selected_skill_names = test_generation_skills(requirement_data)
        context_pipeline.configure(workspace_dir=workspace_root, app_type=app_type)
        static_context, dynamic_context = context_pipeline.build_agent_context_split(
            node_id=node_id,
            agent_type="TestCritic",
        )
        interface_contract = context_pipeline.get_interface_contract_context(node_id)
        context_text = "\n\n".join(part.strip() for part in (static_context, dynamic_context) if part.strip())
        agent = build_stage_agent(
            name="test_critic",
            stage="test_generation",
            model=self.critic_model,
            system_prompt="\n\n".join(
                [get_critic_system_prompt(), stage_skill_activation_policy(selected_skill_names)]
            ),
            response_format=TestCritiqueResponse,
            workspace_root=workspace_root,
            writable_roots=[],
            skills=[SKILLS_SOURCE] if selected_skill_names else [],
            permitted_skill_names=selected_skill_names,
            memory=[],
            tools=[],
        )
        message = get_critic_user_prompt(
            node_id=node_id,
            requirement_data=requirement_data,
            dynamic_context=context_text,
            interface_contract=interface_contract,
            coverage_plan=coverage_plan,
            tests=tests,
            quality_report=quality_report,
        )
        await self._log("Invoking conditional read-only test critic.", node_id=node_id)
        raw_payload = await ainvoke_stage_agent(
            agent,
            message=message,
            context=AgentRuntimeContext(
                node_id=node_id,
                phase="DESIGN",
                app_type=app_type,
                workspace_root=workspace_root,
                requirement_path=self.requirement_path,
            ),
            thread_id=f"{node_id}:DESIGN:TestCritic",
            label="TestCritic",
            log_cb=self.log_cb,
        )
        verdict = str(raw_payload.get("verdict") or "revise").strip().lower()
        if verdict not in {"accept", "revise"}:
            verdict = "revise"
        issues = [dict(item) for item in raw_payload.get("issues") or [] if isinstance(item, dict)]
        repair_instructions = normalize_string_list(raw_payload.get("repair_instructions"))
        result = {
            "verdict": verdict,
            "summary": str(raw_payload.get("summary") or "").strip(),
            "issues": issues,
            "repair_instructions": repair_instructions,
        }
        await self._log(
            f"Test critic verdict={verdict}; issues={len(issues)}; repairs={len(repair_instructions)}.",
            status="warning" if verdict == "revise" else "ok",
            node_id=node_id,
        )
        return result

    async def _log(self, message: str, status: str | None = None, node_id: str | None = None) -> None:
        if self.log_cb is None:
            return
        result = self.log_cb(self.agent_name, message, status, node_id)
        if inspect.isawaitable(result):
            await result
