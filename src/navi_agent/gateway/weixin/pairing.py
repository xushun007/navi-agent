from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import secrets
from pathlib import Path

from navi_agent.paths import get_navi_home


@dataclass(frozen=True, slots=True)
class PairingRequest:
    code: str
    user_id: str
    created_at: str


class WeixinPairingStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or get_navi_home() / "weixin" / "pairing.json"

    def is_approved(self, user_id: str) -> bool:
        data = self._load()
        return user_id in set(data.get("approved_users") or [])

    def request_code(self, user_id: str) -> PairingRequest:
        data = self._load()
        pending = data.setdefault("pending", {})
        for code, item in pending.items():
            if item.get("user_id") == user_id:
                return PairingRequest(
                    code=code,
                    user_id=user_id,
                    created_at=str(item.get("created_at") or ""),
                )
        code = self._new_code(pending)
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        pending[code] = {"user_id": user_id, "created_at": created_at}
        self._save(data)
        return PairingRequest(code=code, user_id=user_id, created_at=created_at)

    def approve(self, code: str) -> str | None:
        data = self._load()
        pending = data.setdefault("pending", {})
        item = pending.pop(code, None)
        if not item:
            return None
        user_id = str(item.get("user_id") or "")
        if not user_id:
            return None
        approved = set(data.get("approved_users") or [])
        approved.add(user_id)
        data["approved_users"] = sorted(approved)
        self._save(data)
        return user_id

    def list_pending(self) -> list[PairingRequest]:
        data = self._load()
        pending = data.get("pending") or {}
        return [
            PairingRequest(
                code=str(code),
                user_id=str(item.get("user_id") or ""),
                created_at=str(item.get("created_at") or ""),
            )
            for code, item in sorted(pending.items())
            if isinstance(item, dict)
        ]

    def list_approved(self) -> list[str]:
        data = self._load()
        return sorted(str(user_id) for user_id in data.get("approved_users") or [])

    def _load(self) -> dict:
        if not self._path.exists():
            return {"pending": {}, "approved_users": []}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {"pending": {}, "approved_users": []}
        return data if isinstance(data, dict) else {"pending": {}, "approved_users": []}

    def _save(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @staticmethod
    def _new_code(pending: dict) -> str:
        while True:
            code = f"{secrets.randbelow(1_000_000):06d}"
            if code not in pending:
                return code
