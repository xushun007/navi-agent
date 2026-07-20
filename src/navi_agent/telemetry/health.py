from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .events import RuntimeEventStore


@dataclass(frozen=True, slots=True)
class RuntimeHealthSummary:
    session_id: str | None
    run_count: int
    event_count: int
    completed_count: int
    failed_count: int
    tool_call_count: int
    tool_error_count: int
    approval_required_count: int
    timeout_count: int
    retryable_error_count: int
    http_status_counts: dict[int, int] = field(default_factory=dict)
    error_type_counts: dict[str, int] = field(default_factory=dict)


class RuntimeHealthService:
    def __init__(self, event_store: RuntimeEventStore) -> None:
        self._event_store = event_store

    def summarize(self, *, session_id: str | None = None) -> RuntimeHealthSummary:
        events = self._event_store.list_events(session_id=session_id)
        run_ids = {event.run_id for event in events}
        completed_count = 0
        failed_count = 0
        tool_call_count = 0
        tool_error_count = 0
        approval_required_count = 0
        timeout_count = 0
        retryable_error_count = 0
        http_status_counts: Counter[int] = Counter()
        error_type_counts: Counter[str] = Counter()

        for event in events:
            payload = event.payload
            if event.name == "runtime.completed":
                completed_count += 1
                if payload.get("status") not in {"success", None}:
                    failed_count += 1
            if event.name == "model.failed":
                failed_count += 1
            if event.name == "tool.call":
                tool_call_count += 1
            if event.name == "tool.result" and payload.get("status") == "error":
                tool_error_count += 1
                structured_content = payload.get("structured_content")
                if isinstance(structured_content, dict):
                    if structured_content.get("approval_required") is True:
                        approval_required_count += 1
                    if structured_content.get("timed_out") is True:
                        timeout_count += 1
                metadata = payload.get("metadata")
                if isinstance(metadata, dict):
                    if metadata.get("retryable") is True:
                        retryable_error_count += 1
                    if metadata.get("timed_out") is True:
                        timeout_count += 1
                    http_status = metadata.get("http_status")
                    if isinstance(http_status, int):
                        http_status_counts[http_status] += 1
                    error_type = metadata.get("error_type")
                    if isinstance(error_type, str) and error_type:
                        error_type_counts[error_type] += 1
            if event.name.endswith(".failed"):
                if payload.get("retryable") is True:
                    retryable_error_count += 1
                http_status = payload.get("http_status")
                if isinstance(http_status, int):
                    http_status_counts[http_status] += 1
                error_type = payload.get("error_type")
                if isinstance(error_type, str) and error_type:
                    error_type_counts[error_type] += 1

        return RuntimeHealthSummary(
            session_id=session_id,
            run_count=len(run_ids),
            event_count=len(events),
            completed_count=completed_count,
            failed_count=failed_count,
            tool_call_count=tool_call_count,
            tool_error_count=tool_error_count,
            approval_required_count=approval_required_count,
            timeout_count=timeout_count,
            retryable_error_count=retryable_error_count,
            http_status_counts=dict(sorted(http_status_counts.items())),
            error_type_counts=dict(sorted(error_type_counts.items())),
        )

    def render(self, *, session_id: str | None = None) -> str:
        summary = self.summarize(session_id=session_id)
        lines = [
            "runtime_health:",
            f"session_id: {summary.session_id or '*'}",
            f"run_count: {summary.run_count}",
            f"event_count: {summary.event_count}",
            f"completed_count: {summary.completed_count}",
            f"failed_count: {summary.failed_count}",
            f"tool_call_count: {summary.tool_call_count}",
            f"tool_error_count: {summary.tool_error_count}",
            f"approval_required_count: {summary.approval_required_count}",
            f"timeout_count: {summary.timeout_count}",
            f"retryable_error_count: {summary.retryable_error_count}",
        ]
        if summary.http_status_counts:
            lines.append("http_status_counts:")
            for status, count in summary.http_status_counts.items():
                lines.append(f"- {status}: {count}")
        if summary.error_type_counts:
            lines.append("error_type_counts:")
            for error_type, count in summary.error_type_counts.items():
                lines.append(f"- {error_type}: {count}")
        return "\n".join(lines)
