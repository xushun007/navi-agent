from __future__ import annotations

from typing import Protocol

from .models import RuntimeEvent


class RuntimeObserver(Protocol):
    def on_event(self, event: RuntimeEvent) -> None: ...
