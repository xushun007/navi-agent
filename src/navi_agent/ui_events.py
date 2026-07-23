from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from threading import Lock
from typing import Protocol, TextIO

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


class ConsoleUiEventSink:
    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout
        self._interactive = bool(getattr(self._stream, "isatty", lambda: False)())
        self._seen_event_ids: set[str] = set()
        self._active_item_id: str | None = None
        self._streaming_item_id: str | None = None
        self._streamed_content: list[str] = []
        self._stream_ends_with_newline = True
        self._lock = Lock()

    def handle(self, event: UiEvent) -> None:
        with self._lock:
            if event.event_id in self._seen_event_ids:
                return
            self._seen_event_ids.add(event.event_id)

            if event.kind == "assistant" and event.state == "delta":
                self._handle_assistant_delta(event)
                return
            if event.kind == "assistant" and event.state == "completed":
                self._finish_stream()
                return

            if event.state == "started":
                self._finish_stream()
                self._active_item_id = event.item_id or event.run_id
                if self._interactive:
                    self._replace_line(render_ui_event(event))
                else:
                    self._write_line(render_ui_event(event))
                return

            if event.state == "progress":
                self._finish_stream()
                self._active_item_id = event.item_id or event.run_id
                if self._interactive:
                    self._replace_line(render_ui_event(event))
                return

            self._finish_stream()
            if self._active_item_id == (event.item_id or event.run_id):
                self._clear_line()
                self._active_item_id = None
            self._write_line(render_ui_event(event))

    def finish(self) -> None:
        with self._lock:
            self._finish_stream()
            self._clear_line()
            self._active_item_id = None

    def rendered_response(self, content: str) -> bool:
        with self._lock:
            return bool(self._streamed_content) and "".join(self._streamed_content) == content

    def _handle_assistant_delta(self, event: UiEvent) -> None:
        delta = event.detail or ""
        if not delta:
            return
        item_id = event.item_id or event.run_id
        if self._streaming_item_id != item_id:
            self._finish_stream()
            self._streaming_item_id = item_id
            self._streamed_content = []
        self._clear_line()
        self._active_item_id = None
        self._stream.write(delta)
        self._stream.flush()
        self._streamed_content.append(delta)
        self._stream_ends_with_newline = delta.endswith("\n")

    def _finish_stream(self) -> None:
        if self._streaming_item_id is None:
            return
        if not self._stream_ends_with_newline:
            self._stream.write("\n")
            self._stream.flush()
        self._streaming_item_id = None
        self._stream_ends_with_newline = True

    def _replace_line(self, text: str) -> None:
        self._stream.write(f"\r\x1b[2K{text}")
        self._stream.flush()

    def _clear_line(self) -> None:
        if not self._interactive or self._active_item_id is None:
            return
        self._stream.write("\r\x1b[2K")
        self._stream.flush()

    def _write_line(self, text: str) -> None:
        self._stream.write(f"{text}\n")
        self._stream.flush()


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
        if event.name == "iteration.started":
            return UiEvent(
                event_id=event.event_id,
                run_id=event.run_id,
                sequence=event.sequence,
                kind="activity",
                state="started",
                title="正在分析请求",
                item_id=f"iteration:{event.iteration or 0}",
                replaceable=True,
            )
        if event.name == "model.plan":
            return UiEvent(
                event_id=event.event_id,
                run_id=event.run_id,
                sequence=event.sequence,
                kind="reasoning",
                state="completed",
                title="执行计划",
                item_id=event.item_id,
                detail=_plan_detail(event.metadata),
            )
        if event.name == "model.delta":
            delta = event.metadata.get("delta")
            if not isinstance(delta, str) or not delta:
                return None
            return UiEvent(
                event_id=event.event_id,
                run_id=event.run_id,
                sequence=event.sequence,
                kind="assistant",
                state="delta",
                title="",
                item_id=event.item_id,
                detail=delta,
            )
        if event.name == "model.response":
            return UiEvent(
                event_id=event.event_id,
                run_id=event.run_id,
                sequence=event.sequence,
                kind="assistant",
                state="completed",
                title="",
                item_id=event.item_id,
            )
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
        if event.name == "runtime.waiting":
            if event.metadata.get("interaction_kind") == "approval":
                return None
            return UiEvent(
                event_id=event.event_id,
                run_id=event.run_id,
                sequence=event.sequence,
                kind="runtime",
                state="waiting",
                title="需要你的输入",
                item_id=event.item_id,
                detail=_safe_prompt(event.metadata.get("prompt")),
                severity="info",
            )
        if event.name == "runtime.interaction_expired":
            return UiEvent(
                event_id=event.event_id,
                run_id=event.run_id,
                sequence=event.sequence,
                kind="runtime",
                state="expired",
                title="请求已过期",
                item_id=event.item_id,
                severity="info",
            )
        if event.name == "runtime.completed" and event.metadata.get("status") != "success":
            if event.metadata.get("status") in {"cancelled", "awaiting_input"}:
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
            detail=_tool_call_detail(tool_name, event.metadata),
            replaceable=True,
        )

    def _tool_completed(self, event: RuntimeEvent) -> UiEvent:
        tool_name = _tool_name(event)
        structured = event.metadata.get("structured_content")
        if isinstance(structured, dict) and structured.get("approval_required") is True:
            return UiEvent(
                event_id=event.event_id,
                run_id=event.run_id,
                sequence=event.sequence,
                kind="approval",
                state="waiting",
                title=f"需要授权 · {_tool_label(tool_name)}",
                item_id=event.item_id,
                detail=_tool_call_detail(tool_name, event.metadata),
                severity="warning",
            )
        failed = event.metadata.get("status") == "error"
        title = (
            f"{_tool_label(tool_name)}失败"
            if failed
            else _tool_title(tool_name, event.metadata, completed=True)
        )
        title = f"{title}{_duration_suffix(event.metadata.get('duration_ms'))}"
        return UiEvent(
            event_id=event.event_id,
            run_id=event.run_id,
            sequence=event.sequence,
            kind="tool",
            state="failed" if failed else "completed",
            title=title,
            item_id=event.item_id,
            detail=(
                _safe_error_detail(event.metadata)
                if failed
                else _tool_result_detail(tool_name, event.metadata)
            ),
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
    "ask_user": "用户确认",
    "background_task": "后台任务",
    "bash": "Bash",
    "code_executor": "代码执行",
    "cron": "定时任务",
    "delegate_task": "子任务",
    "memory": "记忆",
    "patch": "文件修改",
    "read_file": "文件读取",
    "search_files": "文件搜索",
    "session_search": "会话搜索",
    "skill_list": "技能列表",
    "skill_manage": "技能管理",
    "skill_view": "技能读取",
    "todo": "任务清单",
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
        return "Bash 已完成" if completed else "正在执行 Bash"
    if tool_name == "delegate_task":
        return "子任务已完成" if completed else "正在处理子任务"
    return f"{_tool_label(tool_name)}{'已完成' if completed else '中'}"


def _tool_call_detail(tool_name: str, metadata: dict[str, object]) -> str | None:
    arguments = metadata.get("arguments")
    if not isinstance(arguments, dict):
        return None

    if tool_name == "bash":
        command = arguments.get("command")
        return _safe_prefixed("$ ", command, limit=240)
    if tool_name in {"read_file", "write_file", "patch"}:
        return _safe_prefixed("path: ", arguments.get("path"), limit=180)
    if tool_name == "search_files":
        query = _safe_text(arguments.get("query"), limit=140)
        path = _safe_text(arguments.get("path"), limit=80)
        parts = [f"query: {query}" if query else "", f"path: {path}" if path else ""]
        return " · ".join(part for part in parts if part) or None
    if tool_name == "delegate_task":
        return _safe_prefixed("goal: ", arguments.get("goal"), limit=200)
    if tool_name in {"memory", "todo", "cron", "background_task", "skill_manage"}:
        return _safe_prefixed("action: ", arguments.get("action"), limit=80)
    if tool_name == "session_search":
        return _safe_prefixed("query: ", arguments.get("query"), limit=160)
    if tool_name == "skill_view":
        return _safe_prefixed("skill: ", arguments.get("skill_name"), limit=120)
    return None


def _tool_result_detail(tool_name: str, metadata: dict[str, object]) -> str | None:
    structured = metadata.get("structured_content")
    structured = structured if isinstance(structured, dict) else {}

    if tool_name == "bash":
        stdout = _safe_text(structured.get("stdout"), limit=240)
        stderr = _safe_text(structured.get("stderr"), limit=180)
        if stdout:
            return stdout
        if stderr:
            return f"stderr: {stderr}"
        exit_code = structured.get("exit_code")
        return f"exit code: {exit_code}" if isinstance(exit_code, int) else None
    if tool_name == "read_file":
        line_count = structured.get("line_count")
        path = _safe_text(structured.get("path"), limit=120)
        if isinstance(line_count, int):
            return f"{line_count} lines{f' · {path}' if path else ''}"
    if tool_name == "search_files":
        count = structured.get("match_count")
        if isinstance(count, int):
            return f"{count} matches"
    if tool_name == "write_file":
        count = structured.get("bytes_written")
        if isinstance(count, int):
            return f"{count} bytes written"
    if tool_name == "patch":
        count = structured.get("replacements")
        if isinstance(count, int):
            return f"{count} replacement{'s' if count != 1 else ''}"

    return _safe_text(metadata.get("content"), limit=240)


def _plan_detail(metadata: dict[str, object]) -> str | None:
    tool_calls = metadata.get("tool_calls")
    if not isinstance(tool_calls, list):
        return None
    labels: list[str] = []
    for item in tool_calls:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name:
            labels.append(_tool_label(name))
    if not labels:
        return None
    return " → ".join(labels)


def _duration_suffix(value: object) -> str:
    if not isinstance(value, int) or value < 0:
        return ""
    if value < 1000:
        return f" · {value} ms"
    return f" · {value / 1000:.1f} s"


def _safe_prefixed(prefix: str, value: object, *, limit: int) -> str | None:
    text = _safe_text(value, limit=max(1, limit - len(prefix)))
    return f"{prefix}{text}" if text else None


def _safe_text(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return _compact(_redact(value), limit=limit)


def _safe_prompt(value: object) -> str | None:
    return _safe_text(value, limit=240)


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


def render_ui_event(event: UiEvent) -> str:
    marker = {
        "started": "›",
        "progress": "·",
        "completed": "✓",
        "failed": "✗",
        "cancelled": "■",
        "waiting": "›",
    }.get(event.state, "·")
    if event.kind == "reasoning":
        marker = "◇"
    elif event.kind == "approval":
        marker = "!"
    text = f"{marker} {event.title}"
    if event.detail:
        text = f"{text} — {event.detail}"
    return text
