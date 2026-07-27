from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from navi_agent.paths import get_navi_home


@dataclass(frozen=True, slots=True)
class WeixinRoute:
    user_id: str
    context_token: str


class WeixinRouteStore:
    def __init__(self, account_id: str, path: Path | None = None) -> None:
        self._path = path or (
            get_navi_home() / "weixin" / "accounts" / f"{account_id}.routes.json"
        )

    def remember(self, route: WeixinRoute) -> None:
        data = self._load()
        routes = data.setdefault("routes", {})
        routes[route.user_id] = asdict(route)
        data["latest_user_id"] = route.user_id
        self._save(data)

    def get(self, user_id: str | None = None) -> WeixinRoute | None:
        data = self._load()
        selected_user_id = user_id or str(data.get("latest_user_id") or "")
        item = (data.get("routes") or {}).get(selected_user_id)
        if not isinstance(item, dict):
            return None
        context_token = str(item.get("context_token") or "")
        if not selected_user_id or not context_token:
            return None
        return WeixinRoute(
            user_id=selected_user_id,
            context_token=context_token,
        )

    def _load(self) -> dict:
        if not self._path.exists():
            return {"routes": {}}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {"routes": {}}
        return data if isinstance(data, dict) else {"routes": {}}

    def _save(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._path.chmod(0o600)
