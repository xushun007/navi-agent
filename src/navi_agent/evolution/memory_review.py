from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from navi_agent.memory import MemoryStore
from navi_agent.runtime import Message
from navi_agent.runtime.transports import ModelRequest, ModelTransport
from navi_agent.telemetry import RuntimeTrace

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MemoryReviewDecision:
    action: str
    kind: str = "fact"
    content: str = ""
    rationale: str = ""


class MemoryReviewService:
    def __init__(
        self,
        *,
        transport: ModelTransport,
        memory_store: MemoryStore,
    ) -> None:
        self._transport = transport
        self._memory_store = memory_store

    def review_and_write(self, trace: RuntimeTrace) -> bool:
        if trace.status != "success":
            return False
        if not trace.final_response.strip():
            return False
        try:
            decision = self._review(trace)
        except Exception:
            logger.exception("Memory review failed: trace_id=%s", trace.trace_id)
            return False
        if decision.action != "add_memory":
            return False
        if not decision.content.strip():
            return False
        self._memory_store.add_for_user(
            trace.user_id,
            decision.content,
            kind=decision.kind,
        )
        return True

    def _review(self, trace: RuntimeTrace) -> MemoryReviewDecision:
        response = self._transport.generate(
            ModelRequest(
                messages=[
                    Message(role="system", content=_MEMORY_REVIEW_SYSTEM_PROMPT),
                    Message(role="user", content=self._build_user_prompt(trace)),
                ]
            )
        )
        payload = _parse_json_object(response.content)
        kind = str(payload.get("kind") or "fact").strip().lower()
        if kind not in {"fact", "preference", "task"}:
            kind = "fact"
        return MemoryReviewDecision(
            action=str(payload.get("action") or "nothing").strip(),
            kind=kind,
            content=str(payload.get("content") or "").strip(),
            rationale=str(payload.get("rationale") or "").strip(),
        )

    @staticmethod
    def _build_user_prompt(trace: RuntimeTrace) -> str:
        return "\n".join(
            [
                "Review this completed Navi Agent turn for durable user memory.",
                "",
                "[Session]",
                f"session_id: {trace.session_id}",
                f"user_id: {trace.user_id}",
                f"user_message: {_truncate(trace.user_message, 1200)}",
                f"final_response: {_truncate(trace.final_response, 1200)}",
            ]
        )


_MEMORY_REVIEW_SYSTEM_PROMPT = """You are Navi Agent's memory reviewer.

Decide whether this completed turn contains durable user memory worth saving.

Rules:
- Return only one JSON object. No markdown.
- Use action "nothing" unless the user revealed a stable fact, preference, expectation, or ongoing task state.
- Do not store temporary instructions, one-off task details, or stale session outcomes.
- Store the memory in third-person concise form.
- kind must be one of: fact, preference, task.

Schema:
{
  "action": "add_memory" | "nothing",
  "kind": "fact" | "preference" | "task",
  "content": "memory content or empty string",
  "rationale": "short reason"
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
        raise ValueError("memory review response did not contain a JSON object")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("memory review response must be a JSON object")
    return payload


def _truncate(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."
