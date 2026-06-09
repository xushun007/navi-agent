from __future__ import annotations

import logging
from typing import Protocol

from .models import RuntimeTrace
from .store import TraceStore

logger = logging.getLogger("navi_agent.telemetry.export")


class TraceExporter(Protocol):
    def export_trace(self, trace: RuntimeTrace) -> None: ...


class CompositeTraceStore:
    def __init__(
        self,
        primary: TraceStore,
        exporters: list[TraceExporter] | None = None,
    ) -> None:
        self._primary = primary
        self._exporters = list(exporters or [])

    def record(self, trace: RuntimeTrace) -> None:
        self._primary.record(trace)
        for exporter in self._exporters:
            try:
                exporter.export_trace(trace)
            except Exception:
                logger.exception("Trace export failed")

    def list_traces(
        self,
        *,
        user_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[RuntimeTrace]:
        return self._primary.list_traces(
            user_id=user_id,
            status=status,
            limit=limit,
        )

    def get_session_traces(
        self,
        session_id: str,
        *,
        user_id: str | None = None,
    ) -> list[RuntimeTrace]:
        return self._primary.get_session_traces(
            session_id=session_id,
            user_id=user_id,
        )

    def get_latest_trace(
        self,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> RuntimeTrace | None:
        return self._primary.get_latest_trace(
            session_id=session_id,
            user_id=user_id,
        )
