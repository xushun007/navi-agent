from __future__ import annotations

from threading import Event, Lock


class RunCancellationToken:
    def __init__(self) -> None:
        self._cancelled = Event()
        self._lock = Lock()
        self._reason = ""

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def cancel(self, reason: str = "user_requested") -> bool:
        with self._lock:
            if self._cancelled.is_set():
                return False
            self._reason = reason
            self._cancelled.set()
            return True


class ActiveRunRegistry:
    def __init__(self) -> None:
        self._tokens: dict[str, RunCancellationToken] = {}
        self._lock = Lock()

    def start(self, session_id: str) -> RunCancellationToken:
        token = RunCancellationToken()
        with self._lock:
            if session_id in self._tokens:
                raise RuntimeError(f"session already has an active run: {session_id}")
            self._tokens[session_id] = token
        return token

    def finish(self, session_id: str, token: RunCancellationToken) -> None:
        with self._lock:
            if self._tokens.get(session_id) is token:
                del self._tokens[session_id]

    def cancel(self, session_id: str, reason: str = "user_requested") -> bool:
        with self._lock:
            token = self._tokens.get(session_id)
        return token.cancel(reason) if token is not None else False

    def is_active(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._tokens
