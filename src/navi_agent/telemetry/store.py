from __future__ import annotations

from typing import Protocol

from .models import RuntimeTrace


class TraceStore(Protocol):
    def record(self, trace: RuntimeTrace) -> None: ...
