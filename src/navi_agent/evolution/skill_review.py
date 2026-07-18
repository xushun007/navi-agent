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
            return None
        if not decision.skill_name or not decision.skill_content.strip():
            return None
        if self._skill_store is not None and self._skill_store.get(decision.skill_name) is not None:
            return None

        return EvolutionCandidate(
            target="skill",
            summary=decision.summary or f"Create reusable skill `{decision.skill_name}`",
            rationale=decision.rationale or "LLM review found reusable procedural knowledge.",
            metadata={
                "source_session_id": trace.session_id,
                "source_trace_id": trace.trace_id,
                "skill_name": decision.skill_name,
                "skill_content": decision.skill_content,
                "tool_names": [execution.tool_name for execution in trace.tool_executions],
                "reviewer": "llm",
            },
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
        )

    def _build_user_prompt(self, trace: RuntimeTrace) -> str:
        existing_skills = []
        if self._skill_store is not None:
            for skill in self._skill_store.list():
                existing_skills.append(f"- {skill.name}: {skill.description}")
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

Decide whether this completed session should create one reusable skill candidate.

Rules:
- Return only one JSON object. No markdown.
- Use action "nothing" unless the session contains reusable procedural knowledge.
- Create class-level skills, not one-session micro skills.
- Do not create a skill for transient environment failures or ordinary one-off answers.
- Prefer broad reusable procedures: debugging pattern, tool workflow, project convention, user-corrected workflow, or repeatable verification path.
- If an existing skill already covers the procedure, return action "nothing".
- skill_name must be lowercase kebab-case.
- skill_content must be a complete SKILL.md body with sections: # title, ## When To Use, ## Procedure, ## Evidence.

Schema:
{
  "action": "create_skill" | "nothing",
  "skill_name": "short-kebab-name-or-empty",
  "summary": "short candidate summary",
  "rationale": "why this should or should not become a skill",
  "skill_content": "complete SKILL.md content or empty string"
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
