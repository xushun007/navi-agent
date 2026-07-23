from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from navi_agent.runtime import Message
from navi_agent.runtime.transports import ModelRequest, ModelTransport

from ..reviews.evidence import SkillReviewEvidence, render_skill_review_evidence
from ..core.models import EvolutionCandidate
from .store import FileSkillStore

logger = logging.getLogger(__name__)


_VALID_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class SkillReviewDecision:
    action: str
    skill_name: str = ""
    summary: str = ""
    rationale: str = ""
    skill_content: str = ""
    section: str = ""
    append_content: str = ""


class SkillReviewService:
    def __init__(
        self,
        *,
        transport: ModelTransport,
        skill_store: FileSkillStore | None = None,
    ) -> None:
        self._transport = transport
        self._skill_store = skill_store

    def propose_candidate(
        self,
        evidence: SkillReviewEvidence,
    ) -> EvolutionCandidate | None:
        if not evidence.messages_snapshot:
            return None

        try:
            decision = self._review_with_agent(evidence)
        except Exception:
            logger.exception("Skill review failed: trace_id=%s", evidence.trace_id)
            return None

        if decision.action != "create_skill":
            if decision.action != "update_skill":
                return None
        if not decision.skill_name:
            return None
        existing_skill = self._skill_store.get(decision.skill_name) if self._skill_store is not None else None
        if decision.action == "create_skill" and existing_skill is not None:
            return None
        if decision.action == "update_skill" and existing_skill is None:
            return None

        operation = "update" if decision.action == "update_skill" else "create"
        if operation == "create" and not decision.skill_content.strip():
            return None
        if operation == "update" and (
            not decision.section.strip() or not decision.append_content.strip()
        ):
            return None
        metadata = {
            "operation": operation,
            "source_session_id": evidence.session_id,
            "source_trace_id": evidence.trace_id,
            "skill_name": decision.skill_name,
            "tool_names": _tool_call_names(evidence),
            "reviewer": "llm",
        }
        if operation == "update":
            metadata["section"] = decision.section
            metadata["append_content"] = decision.append_content
        else:
            metadata["skill_content"] = decision.skill_content
        return EvolutionCandidate(
            target="skill",
            summary=decision.summary or f"{operation.title()} reusable skill `{decision.skill_name}`",
            rationale=decision.rationale or "LLM review found reusable procedural knowledge.",
            metadata=metadata,
        )

    def _review_with_agent(self, evidence: SkillReviewEvidence) -> SkillReviewDecision:
        plan = self._plan(evidence)
        if plan.action == "nothing":
            return plan
        if not plan.skill_name:
            return SkillReviewDecision(action="nothing", rationale="missing skill name")
        if plan.action == "update_skill":
            if self._skill_store is None:
                return SkillReviewDecision(action="nothing", rationale="no skill store available")
            target = self._skill_store.get(plan.skill_name)
            if target is None:
                return SkillReviewDecision(action="nothing", rationale="target skill not found")
            patch = self._build_update(evidence, plan=plan, existing_skill_content=target.content)
            return SkillReviewDecision(
                action="update_skill",
                skill_name=plan.skill_name,
                summary=patch.summary or plan.summary,
                rationale=patch.rationale or plan.rationale,
                section=patch.section,
                append_content=patch.append_content,
            )
        if plan.action == "create_skill":
            if self._skill_store is not None and self._skill_store.get(plan.skill_name) is not None:
                return SkillReviewDecision(action="nothing", rationale="target skill already exists")
            created = self._build_create(evidence, plan=plan)
            return SkillReviewDecision(
                action="create_skill",
                skill_name=plan.skill_name or created.skill_name,
                summary=created.summary or plan.summary,
                rationale=created.rationale or plan.rationale,
                skill_content=created.skill_content,
            )
        return SkillReviewDecision(action="nothing")

    def _plan(self, evidence: SkillReviewEvidence) -> SkillReviewDecision:
        response = self._transport.generate(
            ModelRequest(
                messages=[
                    Message(role="system", content=_PLAN_SYSTEM_PROMPT),
                    Message(role="user", content=self._build_planning_prompt(evidence)),
                ]
            )
        )
        payload = _parse_json_object(response.content)
        action = str(payload.get("action") or "nothing").strip()
        skill_name = _normalize_skill_name(str(payload.get("skill_name") or ""))
        return SkillReviewDecision(
            action=action,
            skill_name=skill_name,
            summary=str(payload.get("summary") or "").strip(),
            rationale=str(payload.get("rationale") or "").strip(),
        )

    def _build_update(
        self,
        evidence: SkillReviewEvidence,
        *,
        plan: SkillReviewDecision,
        existing_skill_content: str,
    ) -> SkillReviewDecision:
        response = self._transport.generate(
            ModelRequest(
                messages=[
                    Message(role="system", content=_UPDATE_SYSTEM_PROMPT),
                    Message(
                        role="user",
                        content=self._build_update_prompt(
                            evidence,
                            plan=plan,
                            existing_skill_content=existing_skill_content,
                        ),
                    ),
                ]
            )
        )
        payload = _parse_json_object(response.content)
        return SkillReviewDecision(
            action="update_skill",
            summary=str(payload.get("summary") or "").strip(),
            rationale=str(payload.get("rationale") or "").strip(),
            section=str(payload.get("section") or "").strip(),
            append_content=str(payload.get("append_content") or "").strip(),
        )

    def _build_create(
        self,
        evidence: SkillReviewEvidence,
        *,
        plan: SkillReviewDecision,
    ) -> SkillReviewDecision:
        response = self._transport.generate(
            ModelRequest(
                messages=[
                    Message(role="system", content=_CREATE_SYSTEM_PROMPT),
                    Message(role="user", content=self._build_create_prompt(evidence, plan=plan)),
                ]
            )
        )
        payload = _parse_json_object(response.content)
        return SkillReviewDecision(
            action="create_skill",
            skill_name=_normalize_skill_name(str(payload.get("skill_name") or plan.skill_name)),
            summary=str(payload.get("summary") or "").strip(),
            rationale=str(payload.get("rationale") or "").strip(),
            skill_content=str(payload.get("skill_content") or "").strip(),
        )

    def _build_planning_prompt(self, evidence: SkillReviewEvidence) -> str:
        existing_skills = []
        if self._skill_store is not None:
            for skill in self._skill_store.list():
                existing_skills.append(f"- {skill.name}: {skill.description}")
        existing_block = "\n".join(existing_skills) if existing_skills else "- none"
        return "\n".join(
            [
                "Review this completed Navi Agent session evidence for reusable skill knowledge.",
                "",
                "[Existing Skills]",
                existing_block,
                "",
                "[Evidence Window]",
                render_skill_review_evidence(evidence),
            ]
        )

    def _build_update_prompt(
        self,
        evidence: SkillReviewEvidence,
        *,
        plan: SkillReviewDecision,
        existing_skill_content: str,
    ) -> str:
        return "\n".join(
            [
                "Build an append-only update for the selected skill.",
                "",
                "[Plan]",
                f"skill_name: {plan.skill_name}",
                f"summary: {plan.summary}",
                f"rationale: {plan.rationale}",
                "",
                "[Existing SKILL.md]",
                existing_skill_content,
                "",
                "[Evidence Window]",
                render_skill_review_evidence(evidence),
            ]
        )

    def _build_create_prompt(
        self,
        evidence: SkillReviewEvidence,
        *,
        plan: SkillReviewDecision,
    ) -> str:
        return "\n".join(
            [
                "Create a class-level SKILL.md for the planned reusable skill.",
                "",
                "[Plan]",
                f"skill_name: {plan.skill_name}",
                f"summary: {plan.summary}",
                f"rationale: {plan.rationale}",
                "",
                "[Evidence Window]",
                render_skill_review_evidence(evidence),
            ]
        )


_PLAN_SYSTEM_PROMPT = """You are Navi Agent's skill review planning agent.

Decide whether this completed session should update an existing skill, create one new skill, or do nothing.

Rules:
- Return only one JSON object. No markdown.
- Use action "nothing" unless the session contains reusable procedural knowledge.
- Prefer action "update_skill" when an existing skill covers the same class of work.
- Use action "create_skill" only when no existing class-level skill fits.
- Keep skills class-level, not one-session micro skills. A skill name must describe a reusable task class, not today's request.
- Do not create skills named after one PR, one session, one exact error string, one temporary feature branch, or one user's one-off wording.
- If a learning only adds a pitfall, verification step, user workflow preference, or provider/tool quirk to an existing workflow, update the existing skill.
- If multiple existing skills overlap, update the broadest one and mention the consolidation need in rationale; do not create another sibling.
- Do not create or update a skill for transient environment failures or ordinary one-off answers.
- Do not encode negative claims like "tool X does not work" from a setup failure. Encode the reproducible fix or troubleshooting condition only.
- User corrections about style, sequence, approval, verification, or tool choice are valid skill updates when they affect a class of future tasks.
- Prefer broad reusable procedures: debugging pattern, tool workflow, project convention, user-corrected workflow, or repeatable verification path.
- skill_name must be lowercase kebab-case.

Schema:
{
  "action": "update_skill" | "create_skill" | "nothing",
  "skill_name": "short-kebab-name-or-empty",
  "summary": "short candidate summary",
  "rationale": "why this should or should not become a skill"
}
"""


_UPDATE_SYSTEM_PROMPT = """You are Navi Agent's append-only skill patch agent.

Return only one JSON object. No markdown outside JSON.

Rules:
- Never rewrite the full SKILL.md.
- Never use placeholders like "... keep existing content".
- Return a target section and append_content only.
- append_content must be concise Markdown bullets or paragraphs.
- Preserve all existing content by construction.
- Prefer sections like ## Procedure, ## Pitfalls, ## Verification, or ## Evidence.

Schema:
{
  "summary": "short update summary",
  "rationale": "why this append belongs in the target skill",
  "section": "target section heading for update_skill, for example ## Pitfalls",
  "append_content": "append-only Markdown for update_skill"
}
"""


_CREATE_SYSTEM_PROMPT = """You are Navi Agent's skill creation agent.

Return only one JSON object. No markdown outside JSON.

Rules:
- Create one class-level SKILL.md, not a one-session micro skill.
- skill_name must be lowercase kebab-case.
- skill_content must be complete and start with YAML frontmatter containing name, description, and category.
- The frontmatter name must exactly match skill_name.
- After frontmatter, include: # title, ## When To Use, ## Procedure, ## Evidence.
- Do not create skills for transient setup failures or one-off answers.

Schema:
{
  "skill_name": "short-kebab-name",
  "summary": "short creation summary",
  "rationale": "why this reusable skill should exist",
  "skill_content": "complete SKILL.md content"
}
"""


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("skill review response did not contain a JSON object")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("skill review response must be a JSON object")
    return payload


def _tool_call_names(evidence: SkillReviewEvidence) -> list[str]:
    names: list[str] = []
    for message in evidence.messages_snapshot:
        for tool_call in message.tool_calls:
            if tool_call.name not in names:
                names.append(tool_call.name)
    return names


def _normalize_skill_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not normalized:
        return ""
    if len(normalized) > 64:
        normalized = normalized[:64].rstrip("-")
    if not _VALID_SKILL_NAME.match(normalized):
        return ""
    return normalized
