from __future__ import annotations

import json
from pathlib import Path

from .models import RuntimeTrace
from .serializer import TraceSerializer


class JsonlTraceStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def record(self, trace: RuntimeTrace) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(TraceSerializer.to_json(trace))
            handle.write("\n")

    def list_traces(
        self,
        *,
        user_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[RuntimeTrace]:
        traces = self._read_traces()
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
        traces = [trace for trace in self._read_traces() if trace.session_id == session_id]
        if user_id is not None:
            traces = [trace for trace in traces if trace.user_id == user_id]
        return traces

    def get_latest_trace(
        self,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> RuntimeTrace | None:
        traces = self.list_traces(user_id=user_id, limit=None)
        if session_id is not None:
            traces = [trace for trace in traces if trace.session_id == session_id]
        if not traces:
            return None
        return traces[0]

    def _read_traces(self) -> list[RuntimeTrace]:
        if not self._path.exists():
            return []
        traces = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                payload.pop("schema_version", None)
                traces.append(RuntimeTrace(**payload))
        return traces
