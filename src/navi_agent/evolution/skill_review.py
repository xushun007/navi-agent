from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from navi_agent.runtime import Message
from navi_agent.runtime.transports import ModelRequest, ModelTransport
from navi_agent.telemetry import RuntimeTrace

from .models import EvolutionCandidate
from .skills import FileSkillStore

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

    def propose_candidate(self, trace: RuntimeTrace) -> EvolutionCandidate | None:
        if trace.status != "success":
            return None
        if not trace.final_response.strip():
            return None
        if not trace.tool_executions:
            return None

        try:
            decision = self._review(trace)
        except Exception:
            logger.exception("Skill review failed: trace_id=%s", trace.trace_id)
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
            "source_session_id": trace.session_id,
            "source_trace_id": trace.trace_id,
            "skill_name": decision.skill_name,
            "tool_names": [execution.tool_name for execution in trace.tool_executions],
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

    def _review(self, trace: RuntimeTrace) -> SkillReviewDecision:
        response = self._transport.generate(
            ModelRequest(
                messages=[
                    Message(role="system", content=_REVIEW_SYSTEM_PROMPT),
                    Message(role="user", content=self._build_user_prompt(trace)),
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
            skill_content=str(payload.get("skill_content") or "").strip(),
            section=str(payload.get("section") or "").strip(),
            append_content=str(payload.get("append_content") or "").strip(),
        )

    def _build_user_prompt(self, trace: RuntimeTrace) -> str:
        existing_skills = []
        if self._skill_store is not None:
            for skill in self._skill_store.list():
                existing_skills.append(
                    "\n".join(
                        [
                            f"## {skill.name}",
                            f"description: {skill.description}",
                            "content:",
                            _truncate(skill.content, 1600),
                        ]
                    )
                )
        existing_block = "\n".join(existing_skills) if existing_skills else "- none"
        tool_lines = "\n".join(
            f"- {execution.tool_name}: status={execution.status} output={_truncate(execution.content, 500)}"
            for execution in trace.tool_executions
        )
        return "\n".join(
            [
                "Review this completed Navi Agent session for reusable skill knowledge.",
                "",
                "[Existing Skills]",
                existing_block,
                "",
                "[Session]",
                f"session_id: {trace.session_id}",
                f"user_message: {_truncate(trace.user_message, 1200)}",
                f"final_response: {_truncate(trace.final_response, 1200)}",
                "",
                "[Tool Executions]",
                tool_lines or "- none",
            ]
        )


_REVIEW_SYSTEM_PROMPT = """You are Navi Agent's skill reviewer.

Decide whether this completed session should update or create one reusable skill.

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
- For create_skill, skill_content must be the complete SKILL.md body with sections: # title, ## When To Use, ## Procedure, ## Evidence.
- For update_skill, do not rewrite the full SKILL.md. Return a target section and append_content only.
- update_skill must be append-only. append_content should be concise Markdown bullets or paragraphs that preserve existing content.

Schema:
{
  "action": "update_skill" | "create_skill" | "nothing",
  "skill_name": "short-kebab-name-or-empty",
  "summary": "short candidate summary",
  "rationale": "why this should or should not become a skill",
  "skill_content": "complete SKILL.md content for create_skill, otherwise empty string",
  "section": "target section heading for update_skill, for example ## Pitfalls",
  "append_content": "append-only Markdown for update_skill"
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


def _normalize_skill_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not normalized:
        return ""
    if len(normalized) > 64:
        normalized = normalized[:64].rstrip("-")
    if not _VALID_SKILL_NAME.match(normalized):
        return ""
    return normalized


def _truncate(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."
