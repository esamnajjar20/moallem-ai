from dataclasses import dataclass

import pytest

from moallem.domain.errors import ResourceNotFound
from moallem.domain.membership import ActiveContext


@dataclass(frozen=True)
class Doc:
    id: str
    tenant_id: str


A = ActiveContext("u1", "m-a", "tenant-A", ("TEACHER",))
B = ActiveContext("u1", "m-b", "tenant-B", ("TEACHER",))


def _repo():  # type: ignore[no-untyped-def]
    from moallem.domain.scoped import InMemoryScopedRepository

    r: InMemoryScopedRepository[Doc] = InMemoryScopedRepository(
        lambda d: d.tenant_id, lambda d: d.id
    )
    r.add(A, Doc("d1", "tenant-A"))
    r.add(B, Doc("d2", "tenant-B"))
    return r


def test_list_returns_only_own_tenant() -> None:
    r = _repo()
    assert [d.id for d in r.list(A)] == ["d1"]
    assert [d.id for d in r.list(B)] == ["d2"]


def test_get_foreign_and_missing_are_indistinguishable() -> None:  # AT-015
    r = _repo()
    errs = []
    for ctx, rid in ((A, "d2"), (A, "nope")):
        with pytest.raises(ResourceNotFound) as ei:
            r.get(ctx, rid)
        errs.append((ei.value.code, str(ei.value), ei.value.http_status))
    assert len(set(errs)) == 1


def test_cannot_add_item_for_another_tenant() -> None:
    r = _repo()
    with pytest.raises(ResourceNotFound):
        r.add(A, Doc("d3", "tenant-B"))


def test_cannot_delete_foreign_item_and_it_survives() -> None:
    r = _repo()
    with pytest.raises(ResourceNotFound):
        r.delete(A, "d2")
    assert r.get(B, "d2").id == "d2"
