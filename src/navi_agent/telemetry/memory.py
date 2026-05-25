from __future__ import annotations

from .models import RuntimeTrace


class InMemoryTraceStore:
    def __init__(self) -> None:
        self.traces: list[RuntimeTrace] = []

    def record(self, trace: RuntimeTrace) -> None:
        self.traces.append(trace)
