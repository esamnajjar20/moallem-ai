import pytest

from moallem.domain.errors import ResourceNotFound
from moallem.domain.membership import ActiveContext
from moallem.domain.tenant_keys import (
    cache_key,
    make_envelope,
    require_cache_key,
    require_envelope_for,
    require_storage_path,
    storage_path,
    tenant_of_cache_key,
    tenant_of_storage_path,
)

A = ActiveContext("u1", "m-a", "tenant-A", ("TEACHER",))
B = ActiveContext("u1", "m-b", "tenant-B", ("TEACHER",))


def test_keys_embed_tenant_taken_from_context_only() -> None:
    k = cache_key(A, "courses", "page1")
    assert k == "t:tenant-A:courses:page1"
    assert tenant_of_cache_key(k) == "tenant-A"
    p = storage_path(A, "uploads", "file1.pdf")
    assert p == "tenants/tenant-A/uploads/file1.pdf"
    assert tenant_of_storage_path(p) == "tenant-A"


def test_same_logical_key_differs_per_tenant() -> None:
    assert cache_key(A, "courses", "x") != cache_key(B, "courses", "x")
    assert storage_path(A, "uploads", "x") != storage_path(B, "uploads", "x")


@pytest.mark.parametrize("bad", ["", "a/b", "a:b", "..", "a..b", "a b", "/abs", "a\\b", "x" * 200])
def test_unsafe_segments_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        cache_key(A, "ns", bad)
    with pytest.raises(ValueError):
        storage_path(A, "area", bad)


def test_key_needs_at_least_one_part() -> None:
    with pytest.raises(ValueError):
        cache_key(A, "ns")
    with pytest.raises(ValueError):
        storage_path(A, "area")


def test_foreign_cache_key_and_storage_path_look_like_not_found() -> None:  # AT-015
    foreign_k = cache_key(B, "courses", "x")
    foreign_p = storage_path(B, "uploads", "x")
    with pytest.raises(ResourceNotFound):
        require_cache_key(A, foreign_k)
    with pytest.raises(ResourceNotFound):
        require_storage_path(A, foreign_p)
    for junk in ("", "courses:x", "t:tenant-A", "tenants/tenant-A"):
        with pytest.raises(ResourceNotFound):
            require_cache_key(A, junk)
        with pytest.raises(ResourceNotFound):
            require_storage_path(A, junk)
    assert require_cache_key(A, cache_key(A, "courses", "x")).startswith("t:tenant-A:")


def test_traversal_in_tenant_id_cannot_be_built() -> None:
    evil = ActiveContext("u", "m", "tenant-A/../tenant-B", ("TEACHER",))
    with pytest.raises(ValueError):
        storage_path(evil, "uploads", "x")
    with pytest.raises(ValueError):
        cache_key(evil, "ns", "x")


def test_worker_rejects_foreign_tenant_message() -> None:
    env = make_envelope(A, "task-1", "ref-1")
    assert require_envelope_for(A, env) is env
    with pytest.raises(ResourceNotFound):
        require_envelope_for(B, env)
