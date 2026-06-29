from __future__ import annotations

from hashlib import sha1
from hmac import compare_digest


def make_weixin_signature(token: str, timestamp: str, nonce: str) -> str:
    raw = "".join(sorted([token, timestamp, nonce]))
    return sha1(raw.encode("utf-8")).hexdigest()


def verify_weixin_signature(
    *,
    token: str,
    signature: str,
    timestamp: str,
    nonce: str,
) -> bool:
    expected = make_weixin_signature(token, timestamp, nonce)
    return compare_digest(expected, signature)
