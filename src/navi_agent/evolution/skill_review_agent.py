from __future__ import annotations

from navi_agent.runtime import AgentRuntime, InMemorySessionStore, ModelTransport
from navi_agent.runtime.tool_policy import AllowAllToolPolicy
from navi_agent.runtime.tools import ToolRegistry, ToolsetDefinition
from navi_agent.telemetry import InMemoryTraceStore
from navi_agent.tools.skill_manage_tool import SkillManageTool

from .evidence import SkillReviewEvidence, render_skill_review_evidence
from .skills import FileSkillStore


class SkillReviewAgentService:
    def __init__(
        self,
        *,
        transport: ModelTransport,
        skill_store: FileSkillStore,
        max_iterations: int = 6,
    ) -> None:
        self._runtime = AgentRuntime(
            transport=transport,
            session_store=InMemorySessionStore(),
            trace_store=InMemoryTraceStore(),
            tool_registry=ToolRegistry(
                registered_tools=[
                    ("skills", SkillManageTool(skill_store=skill_store)),
                ],
                toolsets=[
                    ToolsetDefinition(name="skills", tools=["skill_manage"]),
                ],
                policy=AllowAllToolPolicy(),
            ),
            max_iterations=max_iterations,
            enabled_toolsets=["skills"],
        )

    def review_and_write(self, evidence: SkillReviewEvidence):
        return self._runtime.run_conversation(
            session_id=f"skill-review:{evidence.session_id}:{evidence.trace_id}",
            user_id=evidence.user_id,
            user_message=_build_review_prompt(evidence),
            system_prompt=_SKILL_REVIEW_AGENT_SYSTEM_PROMPT,
        )


_SKILL_REVIEW_AGENT_SYSTEM_PROMPT = """You are Navi Agent's background skill review agent.

You run after the user's task is already complete. Your only job is to improve
the skill library when the evidence contains reusable procedural knowledge.

You may only use the `skill_manage` tool.

Process:
1. Call skill_manage action=list to inspect existing skills.
2. If an existing skill may fit, call skill_manage action=view for that skill.
3. Prefer appending to an existing class-level skill.
4. Create a new class-level skill only when no existing skill fits.
5. If nothing durable was learned, do not call create/append; answer "Nothing to save."

Rules:
- Keep skills class-level, not one-session micro skills.
- Never create skills named after one session, one error string, one temporary branch, or one user's one-off wording.
- Never rewrite full existing skills. Use skill_manage action=append for updates.
- Do not persist transient setup failures or negative claims like "tool X does not work".
- Capture durable workflow corrections, tool-use patterns, pitfalls, verification steps, and user-corrected procedures.
"""


def _build_review_prompt(evidence: SkillReviewEvidence) -> str:
    return "\n".join(
        [
            "Review the session evidence below and update the skill library if warranted.",
            "",
            "[Evidence Window]",
            render_skill_review_evidence(evidence),
        ]
    )
