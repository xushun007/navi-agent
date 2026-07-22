from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol

from navi_agent.events import RuntimeEvent


@dataclass(frozen=True, slots=True)
class UiEvent:
    event_id: str
    run_id: str
    sequence: int
    kind: str
    state: str
    title: str
    item_id: str | None = None
    detail: str | None = None
    severity: str = "info"
    replaceable: bool = False


class UiEventSink(Protocol):
    def handle(self, event: UiEvent) -> None: ...


class CallableUiEventSink:
    def __init__(self, callback: Callable[[UiEvent], None]) -> None:
        self._callback = callback

    def handle(self, event: UiEvent) -> None:
        self._callback(event)


class UiEventEmitter:
    def __init__(self, sink: UiEventSink) -> None:
        self._sink = sink
        self._mapper = UiEventMapper()

    def handle(self, event: RuntimeEvent) -> None:
        ui_event = self._mapper.map(event)
        if ui_event is not None:
            self._sink.handle(ui_event)


class UiEventMapper:
    def map(self, event: RuntimeEvent) -> UiEvent | None:
        if event.name == "tool.call":
            return self._tool_started(event)
        if event.name == "tool.result":
            return self._tool_completed(event)
        if event.name == "tool.progress":
            return self._tool_progress(event)
        if event.name == "background_task.completed":
            return self._background_completed(event)
        if event.name == "runtime.cancelled":
            return UiEvent(
                event_id=event.event_id,
                run_id=event.run_id,
                sequence=event.sequence,
                kind="runtime",
                state="cancelled",
                title="任务已停止",
                severity="info",
            )
        if event.name == "runtime.completed" and event.metadata.get("status") != "success":
            if event.metadata.get("status") == "cancelled":
                return None
            return UiEvent(
                event_id=event.event_id,
                run_id=event.run_id,
                sequence=event.sequence,
                kind="error",
                state="failed",
                title="任务未能完成",
                item_id=event.item_id,
                detail=_safe_error_detail(event.metadata),
                severity="error",
            )
        return None

    def _tool_started(self, event: RuntimeEvent) -> UiEvent:
        tool_name = _tool_name(event)
        return UiEvent(
            event_id=event.event_id,
            run_id=event.run_id,
            sequence=event.sequence,
            kind="tool",
            state="started",
            title=_tool_title(tool_name, event.metadata, completed=False),
            item_id=event.item_id,
            replaceable=True,
        )

    def _tool_completed(self, event: RuntimeEvent) -> UiEvent:
        tool_name = _tool_name(event)
        failed = event.metadata.get("status") == "error"
        return UiEvent(
            event_id=event.event_id,
            run_id=event.run_id,
            sequence=event.sequence,
            kind="tool",
            state="failed" if failed else "completed",
            title=(
                f"{_tool_label(tool_name)}失败"
                if failed
                else _tool_title(tool_name, event.metadata, completed=True)
            ),
            item_id=event.item_id,
            detail=_safe_error_detail(event.metadata) if failed else None,
            severity="error" if failed else "info",
            replaceable=True,
        )

    def _tool_progress(self, event: RuntimeEvent) -> UiEvent | None:
        chunk = event.metadata.get("chunk")
        if not isinstance(chunk, str) or not chunk.strip():
            return None
        tool_name = _tool_name(event)
        return UiEvent(
            event_id=event.event_id,
            run_id=event.run_id,
            sequence=event.sequence,
            kind="tool",
            state="progress",
            title="命令仍在执行" if tool_name == "bash" else f"{_tool_label(tool_name)}中",
            item_id=event.item_id,
            detail=_compact(_redact(chunk), limit=160),
            replaceable=True,
        )

    def _background_completed(self, event: RuntimeEvent) -> UiEvent:
        failed = event.metadata.get("status") == "failed"
        return UiEvent(
            event_id=event.event_id,
            run_id=event.run_id,
            sequence=event.sequence,
            kind="tool",
            state="failed" if failed else "completed",
            title="后台任务失败" if failed else "后台任务已完成",
            item_id=event.item_id,
            severity="error" if failed else "info",
        )


_TOOL_LABELS = {
    "bash": "命令执行",
    "delegate_task": "子任务",
    "patch": "文件修改",
    "read_file": "文件读取",
    "search_files": "文件搜索",
    "write_file": "文件写入",
}

_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|authorization|cookie|password|secret|token)\b"
        r"(\s*[:=]\s*)([^\s,;]+)"
    ),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
)


def _tool_name(event: RuntimeEvent) -> str:
    value = event.metadata.get("tool_name")
    return value if isinstance(value, str) and value else "tool"


def _tool_label(tool_name: str) -> str:
    return _TOOL_LABELS.get(tool_name, "工具执行")


def _tool_title(tool_name: str, metadata: dict[str, object], *, completed: bool) -> str:
    verb = "已" if completed else "正在"
    arguments = metadata.get("arguments")
    path = _safe_path(arguments.get("path")) if isinstance(arguments, dict) else None
    if tool_name == "read_file":
        return f"{verb}读取{f' {path}' if path else '文件'}"
    if tool_name in {"write_file", "patch"}:
        return f"{verb}修改{f' {path}' if path else '文件'}"
    if tool_name == "search_files":
        return f"{verb}搜索文件"
    if tool_name == "bash":
        return "已运行命令" if completed else "正在执行命令"
    if tool_name == "delegate_task":
        return "子任务已完成" if completed else "正在处理子任务"
    return f"{_tool_label(tool_name)}{'已完成' if completed else '中'}"


def _safe_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    name = Path(value.strip()).name
    return _compact(name, limit=80) or None


def _safe_error_detail(metadata: dict[str, object]) -> str | None:
    candidates = [metadata.get("error_message"), metadata.get("content")]
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        candidates.insert(0, nested.get("error_message"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return _compact(_redact(candidate), limit=160)
    error_type = metadata.get("error_type")
    if isinstance(error_type, str) and error_type:
        return error_type
    return None


def _redact(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        if "bearer" in pattern.pattern.lower():
            redacted = pattern.sub("Bearer <redacted>", redacted)
        else:
            redacted = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", redacted)
    return redacted


def _compact(text: str, *, limit: int) -> str:
    compacted = " ".join(text.split())
    if len(compacted) <= limit:
        return compacted
    return f"{compacted[: limit - 1]}…"
