import json
import logging

import pytest

from moallem.domain.errors import ResourceNotFound
from moallem.domain.membership import ActiveContext
from moallem.domain.secrets import InMemoryVault

A = ActiveContext("u1", "m-a", "tenant-A", ("TEACHER",))
B = ActiveContext("u2", "m-b", "tenant-B", ("TEACHER",))
RAW = "moodle-token-SUPERSECRET-123"


def test_ref_never_exposes_raw_in_repr_str_or_json() -> None:
    ref = InMemoryVault().put(A, RAW)
    for text in (repr(ref), str(ref), f"{ref}", json.dumps({"ref": ref.ref_id})):
        assert RAW not in text
    assert "redacted" in repr(ref)


def test_ref_does_not_leak_through_logging() -> None:
    ref = InMemoryVault().put(A, RAW)
    rec = logging.LogRecord("t", logging.INFO, "f", 1, "ref=%s %r", (ref, ref), None)
    assert RAW not in rec.getMessage()


def test_reveal_roundtrip_same_tenant() -> None:
    v = InMemoryVault()
    assert v.reveal(A, v.put(A, RAW)) == RAW


def test_other_tenant_cannot_reveal_or_delete() -> None:
    v = InMemoryVault()
    ref = v.put(A, RAW)
    for op in (v.reveal, v.delete):
        with pytest.raises(ResourceNotFound):
            op(B, ref)
    assert v.reveal(A, ref) == RAW


def test_deleted_secret_is_gone() -> None:
    v = InMemoryVault()
    ref = v.put(A, RAW)
    v.delete(A, ref)
    with pytest.raises(ResourceNotFound):
        v.reveal(A, ref)
