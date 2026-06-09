from __future__ import annotations

from .models import RuntimeTrace


class InMemoryTraceStore:
    def __init__(self) -> None:
        self.traces: list[RuntimeTrace] = []

    def record(self, trace: RuntimeTrace) -> None:
        self.traces.append(trace)

    def list_traces(
        self,
        *,
        user_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[RuntimeTrace]:
        traces = list(self.traces)
        if user_id is not None:
            traces = [trace for trace in traces if trace.user_id == user_id]
        if status is not None:
            traces = [trace for trace in traces if trace.status == status]
        traces.reverse()
        if limit is not None:
            traces = traces[:limit]
        return traces

    def get_session_traces(
        self,
        session_id: str,
        *,
        user_id: str | None = None,
    ) -> list[RuntimeTrace]:
        traces = [trace for trace in self.traces if trace.session_id == session_id]
        if user_id is not None:
            traces = [trace for trace in traces if trace.user_id == user_id]
        return traces

    def get_latest_trace(
        self,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> RuntimeTrace | None:
        traces = self.traces
        if session_id is not None:
            traces = [trace for trace in traces if trace.session_id == session_id]
        if user_id is not None:
            traces = [trace for trace in traces if trace.user_id == user_id]
        if not traces:
            return None
        return traces[-1]
