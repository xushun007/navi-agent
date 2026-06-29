from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class WeixinIncomingMessage:
    to_user_name: str
    from_user_name: str
    create_time: int
    msg_type: str
    content: str = ""
    msg_id: str | None = None

    @property
    def session_id(self) -> str:
        if self.msg_id:
            return f"weixin:{self.from_user_name}:{self.msg_id}"
        return f"weixin:{self.from_user_name}"

    @property
    def user_id(self) -> str:
        return self.from_user_name


@dataclass(frozen=True, slots=True)
class WeixinReply:
    to_user_name: str
    from_user_name: str
    content: str
    create_time: int | None = None
    msg_type: str = "text"

    @classmethod
    def from_incoming(
        cls,
        message: WeixinIncomingMessage,
        content: str,
        *,
        create_time: int | None = None,
    ) -> WeixinReply:
        return cls(
            to_user_name=message.from_user_name,
            from_user_name=message.to_user_name,
            content=content,
            create_time=create_time,
        )


def new_weixin_session_id(user_id: str) -> str:
    return f"weixin:{user_id}:{uuid4().hex}"
