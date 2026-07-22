from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from .approval import ApprovalDecision, ApprovalRequest


@dataclass(frozen=True, slots=True)
class PendingInteraction:
    interaction_id: str
    session_id: str
    user_id: str
    kind: str
    prompt: str
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    status: str = "pending"
    created_at: str = ""


class JsonPendingInteractionStore:
    def __init__(self, path: Path, *, ttl: timedelta = timedelta(hours=24)) -> None:
        self._path = path
        self._ttl = ttl
        self._lock = Lock()

    def create(
        self,
        *,
        session_id: str,
        user_id: str,
        kind: str,
        prompt: str,
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> PendingInteraction:
        with self._lock:
            items = self._load_active()
            for item in items:
                if (
                    item.session_id == session_id
                    and item.status == "pending"
                    and item.kind == kind
                    and item.tool_name == tool_name
                    and item.arguments == arguments
                ):
                    return item
            item = PendingInteraction(
                interaction_id=uuid4().hex,
                session_id=session_id,
                user_id=user_id,
                kind=kind,
                prompt=prompt,
                tool_name=tool_name,
                arguments=dict(arguments or {}) or None,
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            items.append(item)
            self._save(items)
            return item

    def get_pending(self, session_id: str) -> PendingInteraction | None:
        with self._lock:
            items = self._load_active()
            self._save(items)
            return next(
                (item for item in items if item.session_id == session_id and item.status == "pending"),
                None,
            )

    def resolve(self, session_id: str, *, approved: bool) -> PendingInteraction | None:
        with self._lock:
            items = self._load_active()
            target = next(
                (item for item in items if item.session_id == session_id and item.status == "pending"),
                None,
            )
            if target is None:
                return None
            items.remove(target)
            if approved and target.kind == "approval":
                target = PendingInteraction(**{**asdict(target), "status": "approved"})
                items.append(target)
            self._save(items)
            return target

    def consume_approval(
        self,
        *,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> PendingInteraction | None:
        with self._lock:
            items = self._load_active()
            target = next(
                (
                    item
                    for item in items
                    if item.session_id == session_id
                    and item.status == "approved"
                    and item.tool_name == tool_name
                    and item.arguments == arguments
                ),
                None,
            )
            if target is not None:
                items.remove(target)
                self._save(items)
            return target

    def resolve_clarification(self, session_id: str) -> PendingInteraction | None:
        with self._lock:
            items = self._load_active()
            target = next(
                (
                    item
                    for item in items
                    if item.session_id == session_id
                    and item.status == "pending"
                    and item.kind == "clarification"
                ),
                None,
            )
            if target is not None:
                items.remove(target)
                self._save(items)
            return target

    def discard_approved(self, session_id: str) -> None:
        with self._lock:
            items = self._load_active()
            remaining = [
                item
                for item in items
                if not (item.session_id == session_id and item.status == "approved")
            ]
            if len(remaining) != len(items):
                self._save(remaining)

    def _load_active(self) -> list[PendingInteraction]:
        if not self._path.exists():
            return []
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            items = [PendingInteraction(**item) for item in payload if isinstance(item, dict)]
        except Exception:
            return []
        cutoff = datetime.now(timezone.utc) - self._ttl
        return [item for item in items if _created_at(item) >= cutoff]

    def _save(self, items: list[PendingInteraction]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temporary.write_text(
            json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self._path)


class DeferredApprovalProvider:
    def __init__(self, store: JsonPendingInteractionStore) -> None:
        self._store = store

    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        context = request.context
        if context is None:
            return ApprovalDecision.deny(request.reason)
        approved = self._store.consume_approval(
            session_id=context.session_id,
            tool_name=request.tool_name,
            arguments=request.arguments,
        )
        if approved is not None:
            return ApprovalDecision.allow(
                reason=f"Approved by user for tool: {request.tool_name}",
                metadata={"interaction_id": approved.interaction_id},
            )
        prompt = f"工具 {request.tool_name} 需要授权。回复 /approve 或 /deny。"
        pending = self._store.create(
            session_id=context.session_id,
            user_id=context.user_id,
            kind="approval",
            prompt=prompt,
            tool_name=request.tool_name,
            arguments=request.arguments,
        )
        return ApprovalDecision.deny(
            prompt,
            metadata={
                "interaction_pending": True,
                "interaction_kind": "approval",
                "interaction_id": pending.interaction_id,
                "prompt": prompt,
            },
        )


def _created_at(item: PendingInteraction) -> datetime:
    try:
        return datetime.fromisoformat(item.created_at)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
