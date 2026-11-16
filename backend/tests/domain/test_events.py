import pytest

from moallem.domain.errors import CursorInvalid, EventCursorExpired
from moallem.domain.events import decode_cursor, encode_cursor, select_page

KEY = b"k" * 32


def test_cursor_roundtrip_and_binding() -> None:
    c = encode_cursor(key=KEY, tenant_id="t", task_id="x", last_sequence=7)
    assert decode_cursor(c, key=KEY, tenant_id="t", task_id="x") == 7
    for kw in ({"tenant_id": "other", "task_id": "x"}, {"tenant_id": "t", "task_id": "y"}):
        with pytest.raises(CursorInvalid):
            decode_cursor(c, key=KEY, **kw)
    with pytest.raises(CursorInvalid):
        decode_cursor(c, key=b"z" * 32, tenant_id="t", task_id="x")


def test_tampered_or_garbage_cursor_rejected() -> None:
    c = encode_cursor(key=KEY, tenant_id="t", task_id="x", last_sequence=7)
    body, mac = c.split(".")
    for bad in (f"{body}x.{mac}", f"{body}.{mac[:-2]}", "garbage", "", "a.b.c"):
        with pytest.raises(CursorInvalid):
            decode_cursor(bad, key=KEY, tenant_id="t", task_id="x")


def test_exclusive_ordered_paging_without_gaps_or_dupes() -> None:  # AT-045
    seqs = [5, 1, 3, 2, 4, 6, 7]
    seen: list[int] = []
    after: int | None = None
    while True:
        p = select_page(seqs, after=after, oldest_available=1, limit=3)
        seen += p.items
        after = p.last_sequence
        if not p.has_more:
            break
    assert seen == [1, 2, 3, 4, 5, 6, 7]


def test_resume_returns_only_newer_events() -> None:
    p = select_page([1, 2, 3, 4], after=2, oldest_available=1, limit=10)
    assert p.items == [3, 4] and not p.has_more
    empty = select_page([1, 2], after=2, oldest_available=1, limit=10)
    assert empty.items == [] and empty.last_sequence == 2


def test_expired_when_retention_dropped_unseen_events() -> None:
    with pytest.raises(EventCursorExpired):
        select_page([5, 6], after=2, oldest_available=5, limit=10)  # 3,4 gone
    ok = select_page([5, 6], after=4, oldest_available=5, limit=10)  # 4 seen, 5 is next
    assert ok.items == [5, 6]


def test_no_cursor_starts_at_oldest_retained() -> None:
    assert select_page([5, 6], after=None, oldest_available=5, limit=10).items == [5, 6]


def test_bad_limit() -> None:
    with pytest.raises(CursorInvalid):
        select_page([1], after=None, oldest_available=1, limit=0)
