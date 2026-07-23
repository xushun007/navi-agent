from __future__ import annotations

from navi_agent.memory import MemoryStore
from navi_agent.runtime import AgentRuntime, InMemorySessionStore, ModelTransport
from navi_agent.runtime.tools.policy import AllowAllToolPolicy
from navi_agent.runtime.tools.registry import ToolRegistry, ToolsetDefinition
from navi_agent.telemetry import InMemoryTraceStore
from navi_agent.tools.memory_tool import MemoryTool
from navi_agent.tools.skill_manage_tool import SkillManageTool

from .evidence import SkillReviewEvidence, render_skill_review_evidence
from ..skills.store import FileSkillStore


class ReviewAgentService:
    def __init__(
        self,
        *,
        transport: ModelTransport,
        memory_store: MemoryStore,
        skill_store: FileSkillStore,
        max_iterations: int = 8,
    ) -> None:
        self._runtime = AgentRuntime(
            transport=transport,
            session_store=InMemorySessionStore(),
            trace_store=InMemoryTraceStore(),
            tool_registry=ToolRegistry(
                registered_tools=[
                    ("memory", MemoryTool(memory_store=memory_store)),
                    ("skills", SkillManageTool(skill_store=skill_store)),
                ],
                toolsets=[
                    ToolsetDefinition(name="memory", tools=["memory"]),
                    ToolsetDefinition(name="skills", tools=["skill_manage"]),
                    ToolsetDefinition(name="review", includes=["memory", "skills"]),
                ],
                policy=AllowAllToolPolicy(),
            ),
            max_iterations=max_iterations,
            enabled_toolsets=["review"],
        )

    def review_and_write(
        self,
        evidence: SkillReviewEvidence,
        *,
        review_memory: bool,
        review_skill: bool,
    ):
        return self._runtime.run_conversation(
            session_id=f"review:{evidence.session_id}:{evidence.trace_id}",
            user_id=evidence.user_id,
            user_message=_build_review_prompt(
                evidence,
                review_memory=review_memory,
                review_skill=review_skill,
            ),
            system_prompt=_REVIEW_AGENT_SYSTEM_PROMPT,
        )


_REVIEW_AGENT_SYSTEM_PROMPT = """You are Navi Agent's background review agent.

You run after the user's task is already complete. Read the raw session evidence
once, then persist only durable improvements.

You may use:
- memory: store, update, list, or remove durable user facts, preferences, and ongoing task state.
- skill_manage: maintain reusable procedural skills and supporting attachments.

Decision boundary:
- Use memory target=user for stable user identity, preferences, communication style, constraints, and long-running personal goals.
- Use memory target=memory for stable project facts, environment facts, conventions, and lightweight ongoing task state.
- Use skill_manage for reusable procedures: tool-use sequences, debugging playbooks, verification checklists, migration steps, templates, scripts, and repeated pitfalls.
- If the learned item starts with "the user prefers", "the user wants", or "the user is working on", it is usually memory, not a skill.
- If the learned item starts with "when doing X, run/check/verify Y", it is usually a skill, not memory.
- If both apply, write both: memory captures who/what matters; skill captures how to execute.

Process:
1. First inspect existing state with memory action=list when memory review is requested.
2. First inspect existing skills with skill_manage action=list when skill review is requested.
3. Store user-level facts/preferences/tasks with memory.
4. Store class-level workflows, tool-use patterns, pitfalls, verification steps, and corrected procedures with skill_manage.
5. Use skill_manage action=append for existing skills. Do not rewrite full existing skills.
6. Use skill_manage action=write_attachment for long logs, templates, scripts, or references; keep SKILL.md concise.
7. If nothing durable was learned, do not write anything; answer "Nothing to save."

Rules:
- Do not store temporary instructions, one-off task details, or stale session outcomes as memory.
- Do not store tool logs, stack traces, command output, or implementation recipes in memory.
- Store memory in third-person concise form.
- Prefer updating an existing memory when it contradicts or refines an old memory; do not add duplicates.
- Keep skills class-level, not one-session micro skills.
- Never create skills named after one session, one error string, one temporary branch, or one user's one-off wording.
- Do not persist transient setup failures or negative claims like "tool X does not work".
- Do not store user preferences inside SKILL.md unless they materially affect a reusable procedure.
- Do not store reusable tool procedures as memory.
- VERY IMPORTANT: When creating a new skill, skill_content MUST use this structure:
  ---
  name: lowercase-kebab-name
  description: one concise routing description
  category: short-category
  ---

  # Title

  ## When To Use
  ...

  ## Procedure
  ...
"""


def _build_review_prompt(
    evidence: SkillReviewEvidence,
    *,
    review_memory: bool,
    review_skill: bool,
) -> str:
    objectives = []
    if review_memory:
        objectives.append("- Memory: extract durable user facts, preferences, and ongoing task state.")
    if review_skill:
        objectives.append("- Skills: extract reusable procedures, tool patterns, pitfalls, and artifacts.")
    return "\n".join(
        [
            "Review the session evidence below and update persistent learning state if warranted.",
            "",
            "[Requested Objectives]",
            "\n".join(objectives) or "- None",
            "",
            "[Evidence Window]",
            render_skill_review_evidence(evidence),
        ]
    )
