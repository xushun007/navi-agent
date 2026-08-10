from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import quote

from navi_agent.events import RuntimeEvent
from navi_agent.logging import redact_sensitive_data

from .events import RuntimeEventStore
from .models import ModelCallTrace, RuntimeTrace
from .store import TraceStore


_SKILL_LINE = re.compile(r"^\s+-\s+([a-z0-9][a-z0-9._-]*)(?::|$)")


@dataclass(frozen=True, slots=True)
class TraceViewerRecord:
    trace: RuntimeTrace
    events: tuple[RuntimeEvent, ...]
    available_skill_names: tuple[str, ...]
    loaded_skill_names: tuple[str, ...]
    loaded_skill_references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SessionViewerRecord:
    session_id: str
    traces: tuple[RuntimeTrace, ...]
    loaded_skill_names: tuple[str, ...]

    @property
    def latest_trace(self) -> RuntimeTrace:
        return self.traces[0]


@dataclass(frozen=True, slots=True)
class _UsageSummary:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    cost_usd: float | None


class TraceViewerService:
    """Read existing telemetry and render a local, self-contained trace view."""

    def __init__(
        self,
        *,
        trace_store: TraceStore,
        event_store: RuntimeEventStore,
    ) -> None:
        self._trace_store = trace_store
        self._event_store = event_store

    def get_trace(self, trace_id: str) -> TraceViewerRecord | None:
        trace = next(
            (
                item
                for item in self._trace_store.list_traces(limit=None)
                if item.trace_id == trace_id
            ),
            None,
        )
        if trace is None:
            return None
        events = tuple(self._event_store.list_events(run_id=trace_id))
        return TraceViewerRecord(
            trace=trace,
            events=events,
            available_skill_names=_available_skill_names(trace.system_prompt),
            loaded_skill_names=_loaded_skill_names(trace),
            loaded_skill_references=_loaded_skill_references(trace),
        )

    def write_trace(self, trace_id: str, output_path: Path) -> Path:
        record = self.get_trace(trace_id)
        if record is None:
            raise ValueError(f"trace not found: {trace_id}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render_trace_html(record), encoding="utf-8")
        return output_path

    def list_sessions(self, *, limit: int = 100) -> list[SessionViewerRecord]:
        grouped: dict[str, list[RuntimeTrace]] = {}
        for trace in self._trace_store.list_traces(limit=None):
            grouped.setdefault(trace.session_id, []).append(trace)
        sessions = [
            SessionViewerRecord(
                session_id=session_id,
                traces=tuple(traces),
                loaded_skill_names=tuple(
                    dict.fromkeys(
                        name
                        for trace in traces
                        for name in _loaded_skill_names(trace)
                    )
                ),
            )
            for session_id, traces in grouped.items()
        ]
        return sessions[:limit]

    def get_session(self, session_id: str) -> SessionViewerRecord | None:
        traces = list(reversed(self._trace_store.get_session_traces(session_id)))
        if not traces:
            return None
        return SessionViewerRecord(
            session_id=session_id,
            traces=tuple(traces),
            loaded_skill_names=tuple(
                dict.fromkeys(
                    name
                    for trace in traces
                    for name in _loaded_skill_names(trace)
                )
            ),
        )


def render_trace_html(record: TraceViewerRecord) -> str:
    trace = record.trace
    usage = _summarize_usage(trace.model_calls)
    event_cards = "".join(_render_event(event) for event in record.events)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(trace.trace_id)} · Navi Trace</title>
<style>
:root {{ color-scheme:light dark; --bg:#f5f7fb; --panel:#fff; --text:#172033; --muted:#667085; --line:#d8dee9; --model:#3157d5; --tool:#087f5b; --error:#c92a2a }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.5 ui-sans-serif,system-ui,sans-serif }}
main {{ width:min(1180px,95vw); margin:28px auto 60px }}
h1,h2,h3,p {{ margin-top:0 }}
.panel,.event {{ background:var(--panel); border:1px solid var(--line); border-radius:13px; box-shadow:0 8px 24px #1018280d }}
.panel {{ padding:16px; margin-bottom:12px }}
.meta,.skills {{ display:flex; flex-wrap:wrap; gap:8px; color:var(--muted) }}
.pill {{ border:1px solid var(--line); border-radius:999px; padding:3px 9px }}
.usage-summary {{ display:flex; flex-wrap:wrap; gap:4px 16px; margin-top:10px; color:var(--muted) }}
.usage-stat {{ white-space:nowrap }} .usage-stat strong {{ color:var(--text); margin-right:4px }}
.message {{ margin-top:10px }}
.event {{ display:grid; grid-template-columns:64px 1fr; margin:6px 0; overflow:hidden }}
.seq {{ padding:10px; color:var(--muted); border-right:1px solid var(--line); text-align:center }}
.event-body {{ padding:10px 13px; min-width:0 }}
.event-head {{ display:flex; justify-content:space-between; gap:12px; align-items:start }}
.event-model {{ border-left:4px solid var(--model) }} .event-tool {{ border-left:4px solid var(--tool) }} .event-error {{ border-left:4px solid var(--error) }}
.summary {{ color:var(--muted); margin:3px 0 0 }}
details {{ margin-top:9px }} summary {{ cursor:pointer; color:var(--muted) }}
pre {{ margin:8px 0 0; padding:13px; max-height:55vh; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; background:#111827; color:#e5e7eb; border-radius:8px; font:12px/1.5 ui-monospace,SFMono-Regular,monospace }}
@media (prefers-color-scheme:dark) {{ :root {{--bg:#0e1420;--panel:#151d2c;--text:#e7ecf4;--muted:#9aa7ba;--line:#2c374a}} }}
@media (max-width:680px) {{ .event {{ grid-template-columns:52px 1fr }} .event-head {{ display:block }} }}
</style>
</head>
<body><main>
<section class="panel">
  <h1>Navi Runtime Trace</h1>
  <div class="meta">
    <span class="pill">trace: {escape(trace.trace_id)}</span>
    <span class="pill">status: {escape(trace.status)}</span>
    <span class="pill">iterations: {trace.total_iterations}</span>
    <span class="pill">duration: {trace.duration_ms} ms</span>
    <span class="pill">model calls: {len(trace.model_calls)}</span>
    <span class="pill">tool calls: {len(trace.tool_executions)}</span>
  </div>
  {_render_usage(usage)}
  <p class="message"><strong>Session</strong><br>{escape(trace.session_id)}</p>
  <p class="message"><strong>User</strong><br>{escape(redact_sensitive_data(trace.user_message))}</p>
  <p class="message"><strong>Final response</strong></p>
  <pre>{escape(redact_sensitive_data(trace.final_response))}</pre>
</section>
{_render_skills(record)}
<h2>Runtime event timeline</h2>
{event_cards or '<section class="panel">No runtime events recorded for this trace.</section>'}
</main></body></html>"""


def render_session_index_html(sessions: list[SessionViewerRecord]) -> str:
    rows = "".join(_render_session_row(session) for session in sessions)
    return _page(
        title="Navi Sessions",
        body=f"""<section class="panel">
  <h1>Navi Sessions</h1>
  <p class="muted">Local read-only view of recorded runtime sessions.</p>
</section>
<section class="panel table-wrap">
  <table><thead><tr><th>Session</th><th>Status</th><th>Runs</th><th>Usage</th><th>Skills</th><th>Latest</th></tr></thead>
  <tbody>{rows or '<tr><td colspan="6">No recorded sessions.</td></tr>'}</tbody></table>
</section>""",
    )


def render_session_html(session: SessionViewerRecord) -> str:
    rows = "".join(_render_trace_row(trace) for trace in session.traces)
    return _page(
        title=f"Session · {session.session_id}",
        body=f"""<p><a href="/">← Sessions</a></p>
<section class="panel">
  <h1>Session</h1>
  <p class="mono">{escape(session.session_id)}</p>
  {_render_usage(_summarize_usage(call for trace in session.traces for call in trace.model_calls))}
  <div class="skills">{_pills(session.loaded_skill_names)}</div>
</section>
<section class="panel table-wrap">
  <table><thead><tr><th>Trace</th><th>Status</th><th>Message</th><th>Calls</th><th>Usage</th><th>Duration</th></tr></thead>
  <tbody>{rows}</tbody></table>
</section>""",
    )


def _page(*, title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
:root {{ color-scheme:light dark; --bg:#f5f7fb; --panel:#fff; --text:#172033; --muted:#667085; --line:#d8dee9; --link:#3157d5 }}
* {{ box-sizing:border-box }} body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.5 ui-sans-serif,system-ui,sans-serif }}
main {{ width:min(1180px,95vw); margin:28px auto 60px }} h1,p {{ margin-top:0 }}
.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:13px; padding:16px; margin-bottom:12px; box-shadow:0 8px 24px #1018280d }}
.muted {{ color:var(--muted) }} .mono {{ font-family:ui-monospace,SFMono-Regular,monospace; overflow-wrap:anywhere }}
a {{ color:var(--link); text-decoration:none }} a:hover {{ text-decoration:underline }}
.table-wrap {{ overflow:auto }} table {{ width:100%; min-width:1250px; border-collapse:collapse; line-height:1.25 }} th,td {{ padding:6px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:middle; white-space:nowrap }} th {{ color:var(--muted) }}
.session-line,.message-line {{ max-width:620px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }}
.message-line {{ max-width:420px }} .timestamp {{ white-space:nowrap }}
.usage-summary {{ display:flex; flex-wrap:wrap; gap:4px 16px; margin:8px 0; color:var(--muted) }}
.usage-stat,.usage-inline {{ white-space:nowrap }} .usage-stat strong {{ color:var(--text); margin-right:4px }}
.skills {{ display:flex; flex-wrap:nowrap; gap:6px }} .pill {{ border:1px solid var(--line); border-radius:999px; padding:2px 8px; color:var(--muted); white-space:nowrap }}
@media (prefers-color-scheme:dark) {{ :root {{--bg:#0e1420;--panel:#151d2c;--text:#e7ecf4;--muted:#9aa7ba;--line:#2c374a;--link:#8aa4ff}} }}
</style></head><body><main>{body}</main></body></html>"""


def _render_session_row(session: SessionViewerRecord) -> str:
    latest = session.latest_trace
    usage = _summarize_usage(
        call for trace in session.traces for call in trace.model_calls
    )
    href = f"/session/{quote(session.session_id, safe='')}"
    message = _compact(redact_sensitive_data(latest.user_message), 120)
    return f"""<tr>
  <td><div class="session-line" title="{escape(session.session_id)} · {escape(message)}"><a class="mono" href="{href}">{escape(_compact(session.session_id, 54))}</a><span class="muted"> · {escape(message)}</span></div></td>
  <td>{escape(latest.status)}</td><td>{len(session.traces)}</td>
  <td>{_format_usage(usage)}</td>
  <td><div class="skills">{_pills(session.loaded_skill_names)}</div></td>
  <td class="timestamp">{escape(latest.completed_at or latest.started_at or 'n/a')}</td>
</tr>"""


def _render_trace_row(trace: RuntimeTrace) -> str:
    href = f"/trace/{quote(trace.trace_id, safe='')}"
    calls = f"{len(trace.model_calls)} model / {len(trace.tool_executions)} tool"
    usage = _summarize_usage(trace.model_calls)
    message = _compact(redact_sensitive_data(trace.user_message), 120)
    return f"""<tr>
  <td><a class="mono" href="{href}">{escape(trace.trace_id)}</a></td>
  <td>{escape(trace.status)}</td>
  <td><div class="message-line" title="{escape(message)}">{escape(message)}</div></td>
  <td>{calls}</td><td>{_format_usage(usage)}</td><td>{trace.duration_ms} ms</td>
</tr>"""


def _compact(value: str, limit: int) -> str:
    compacted = " ".join(value.split())
    return compacted if len(compacted) <= limit else f"{compacted[: limit - 1]}…"


def _render_skills(record: TraceViewerRecord) -> str:
    return f"""<section class="panel">
  <h2>Skills</h2>
  <p><strong>Available</strong></p><div class="skills">{_pills(record.available_skill_names)}</div>
  <p class="message"><strong>Injected</strong></p><div class="skills">{_pills(tuple(record.trace.injected_skill_names))}</div>
  <p class="message"><strong>Loaded</strong></p><div class="skills">{_pills(record.loaded_skill_names)}</div>
  <p class="message"><strong>Loaded references</strong></p><div class="skills">{_pills(record.loaded_skill_references)}</div>
</section>"""


def _pills(values: tuple[str, ...]) -> str:
    if not values:
        return '<span class="pill">none</span>'
    return "".join(f'<span class="pill">{escape(value)}</span>' for value in values)


def _render_event(event: RuntimeEvent) -> str:
    css_class = "event"
    if event.source == "model" or event.name.startswith("model."):
        css_class += " event-model"
    elif event.source == "tool" or event.name.startswith("tool."):
        css_class += " event-tool"
    if event.name.endswith(".failed") or event.metadata.get("status") == "error":
        css_class += " event-error"
    iteration = f" · iteration {event.iteration}" if event.iteration is not None else ""
    details = redact_sensitive_data(
        json.dumps(event.metadata, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return f"""<section class="{css_class}">
  <div class="seq">#{event.sequence}</div>
  <div class="event-body">
    <div class="event-head"><strong>{escape(event.name)}</strong><span class="summary">{escape(event.timestamp)}{iteration}</span></div>
    <p class="summary">{escape(event.kind)} / {escape(event.source)}{_event_summary(event)}</p>
    <details><summary>Event payload</summary><pre>{escape(details)}</pre></details>
  </div>
</section>"""


def _event_summary(event: RuntimeEvent) -> str:
    if event.name == "tool.call":
        name = str(event.metadata.get("tool_name") or "unknown")
        return f" · {escape(name)}"
    if event.name == "tool.result":
        name = str(event.metadata.get("tool_name") or "unknown")
        status = str(event.metadata.get("status") or "unknown")
        return f" · {escape(name)} [{escape(status)}]"
    if event.name in {"model.response", "model.discarded"}:
        parts = []
        tool_calls = event.metadata.get("tool_calls")
        if isinstance(tool_calls, list):
            names = [
                str(item.get("name"))
                for item in tool_calls
                if isinstance(item, dict) and item.get("name")
            ]
            if names:
                parts.append(f"calls {escape(', '.join(names))}")
        usage = event.metadata.get("usage")
        if isinstance(usage, dict):
            parts.append(_format_event_usage(usage))
        if parts:
            return f" · {' · '.join(part for part in parts if part)}"
    return ""


def _summarize_usage(model_calls: Iterable[ModelCallTrace]) -> _UsageSummary:
    calls: tuple[ModelCallTrace, ...] = tuple(model_calls)
    costs = [call.cost_usd for call in calls]
    cost_usd = sum(cost for cost in costs if cost is not None) if costs and all(
        cost is not None for cost in costs
    ) else None
    return _UsageSummary(
        input_tokens=sum(call.input_tokens for call in calls),
        output_tokens=sum(call.output_tokens for call in calls),
        cache_read_tokens=sum(call.cache_read_tokens for call in calls),
        cache_write_tokens=sum(call.cache_write_tokens for call in calls),
        reasoning_tokens=sum(call.reasoning_tokens for call in calls),
        cost_usd=cost_usd,
    )


def _render_usage(usage: _UsageSummary) -> str:
    items = "".join(
        f'<span class="usage-stat"><strong>{value}</strong>{label}</span>'
        for label, value in _usage_values(usage)
    )
    return f'<div class="usage-summary">{items}</div>'


def _format_usage(usage: _UsageSummary) -> str:
    values = " · ".join(
        (
            f"{usage.input_tokens:,} in",
            f"{usage.output_tokens:,} out",
            f"{usage.cache_read_tokens:,}/{usage.cache_write_tokens:,} cache r/w",
            f"{usage.reasoning_tokens:,} reasoning",
            f"{_format_cost(usage.cost_usd)} cost",
        )
    )
    return f'<span class="usage-inline">{values}</span>'


def _usage_values(usage: _UsageSummary) -> tuple[tuple[str, str], ...]:
    return (
        ("input", f"{usage.input_tokens:,}"),
        ("output", f"{usage.output_tokens:,}"),
        ("cache read", f"{usage.cache_read_tokens:,}"),
        ("cache write", f"{usage.cache_write_tokens:,}"),
        ("reasoning", f"{usage.reasoning_tokens:,}"),
        ("cost", _format_cost(usage.cost_usd)),
    )


def _format_event_usage(usage: dict) -> str:
    return (
        f"input {_integer(usage.get('input_tokens')):,} / "
        f"output {_integer(usage.get('output_tokens')):,} / "
        f"cache read {_integer(usage.get('cache_read_tokens')):,} / "
        f"cache write {_integer(usage.get('cache_write_tokens')):,} / "
        f"reasoning {_integer(usage.get('reasoning_tokens')):,} / "
        f"cost {_format_cost(_optional_number(usage.get('cost_usd')))}"
    )


def _format_cost(cost_usd: float | None) -> str:
    return "—" if cost_usd is None else f"${cost_usd:.6f}"


def _integer(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _optional_number(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _available_skill_names(system_prompt: str | None) -> tuple[str, ...]:
    if not system_prompt:
        return ()
    in_skills = False
    names: list[str] = []
    for line in system_prompt.splitlines():
        if line.strip() == "[Skills]":
            in_skills = True
            continue
        if in_skills and line.startswith("["):
            break
        if in_skills and (match := _SKILL_LINE.match(line)):
            names.append(match.group(1))
    return tuple(dict.fromkeys(names))


def _loaded_skill_names(trace: RuntimeTrace) -> tuple[str, ...]:
    names = [
        str(execution.arguments.get("skill_name") or "").strip()
        for execution in trace.tool_executions
        if execution.tool_name == "skill_view" and execution.status == "success"
    ]
    return tuple(dict.fromkeys(name for name in names if name))


def _loaded_skill_references(trace: RuntimeTrace) -> tuple[str, ...]:
    references = []
    for execution in trace.tool_executions:
        if execution.tool_name != "skill_view" or execution.status != "success":
            continue
        skill_name = str(execution.arguments.get("skill_name") or "").strip()
        attachment = str(execution.arguments.get("attachment_path") or "").strip()
        if skill_name and attachment:
            references.append(f"{skill_name}/{attachment}")
    return tuple(dict.fromkeys(references))
