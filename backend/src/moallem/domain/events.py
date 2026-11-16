"""Task event replay (DEC-044, API Addendum v2.4 §5).

Cursor = signed, opaque, versioned, EXCLUSIVE (returns sequence > last_sequence) and bound to
(tenant_id, task_id). Never built from timestamps. Expired cursor -> 410 EVENT_CURSOR_EXPIRED.
"""

import base64
import hashlib
import hmac
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from moallem.domain.errors import CursorInvalid, EventCursorExpired

CURSOR_VERSION = 1


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def encode_cursor(*, key: bytes, tenant_id: str, task_id: str, last_sequence: int) -> str:
    body = json.dumps(
        {"v": CURSOR_VERSION, "t": tenant_id, "k": task_id, "s": last_sequence},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    mac = hmac.new(key, body, hashlib.sha256).digest()
    return f"{_b64e(body)}.{_b64e(mac)}"


def decode_cursor(cursor: str, *, key: bytes, tenant_id: str, task_id: str) -> int:
    try:
        body_s, mac_s = cursor.split(".")
        body, mac = _b64d(body_s), _b64d(mac_s)
        data: dict[str, Any] = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise CursorInvalid("malformed cursor") from exc
    if not hmac.compare_digest(mac, hmac.new(key, body, hashlib.sha256).digest()):
        raise CursorInvalid("bad cursor signature")
    seq = data.get("s")
    if (
        data.get("v") != CURSOR_VERSION
        or data.get("t") != tenant_id
        or data.get("k") != task_id
        or not isinstance(seq, int)
        or isinstance(seq, bool)
        or seq < 0
    ):
        raise CursorInvalid("cursor does not belong to this task")
    return seq


@dataclass(frozen=True, slots=True)
class Page:
    items: list[int]  # sequences returned (the real row type is the repository's concern)
    last_sequence: int
    has_more: bool
    oldest_available_sequence: int


def select_page(
    sequences: Sequence[int], *, after: int | None, oldest_available: int, limit: int
) -> Page:
    """`sequences` = retained sequences of ONE task. after=None starts from the oldest retained.

    Expired when retention already dropped events the client has not seen: after + 1 < oldest.
    """
    if limit < 1:
        raise CursorInvalid("limit must be >= 1")
    start = oldest_available - 1 if after is None else after
    if start + 1 < oldest_available:
        raise EventCursorExpired("cursor older than retained events")
    ordered = sorted(s for s in sequences if s > start)
    page = ordered[:limit]
    last = page[-1] if page else start
    return Page(page, last, len(ordered) > limit, oldest_available)
