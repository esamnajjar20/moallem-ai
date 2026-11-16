"""Tenant-scoped repository base (P2-03; DEC-032 application-layer guard).

Every operation REQUIRES an ActiveContext, so a repository call without a tenant cannot be
written. Cross-tenant reads/updates/deletes look identical to "not found" (AT-015).
"""

from collections.abc import Callable

from moallem.domain.authorization import require_tenant
from moallem.domain.errors import ResourceNotFound
from moallem.domain.membership import ActiveContext


class InMemoryScopedRepository[T]:
    """Test double. A DB version must enforce the same contract via composite (tenant_id, id)."""

    def __init__(self, tenant_of: Callable[[T], str], id_of: Callable[[T], str]) -> None:
        self._tenant_of = tenant_of
        self._id_of = id_of
        self._items: dict[str, T] = {}

    def add(self, ctx: ActiveContext, item: T) -> None:
        # The tenant is taken from the context; an item claiming another tenant is rejected.
        require_tenant(ctx, self._tenant_of(item))
        self._items[self._id_of(item)] = item

    def get(self, ctx: ActiveContext, item_id: str) -> T:
        item = self._items.get(item_id)
        if item is None:
            raise ResourceNotFound("resource not found")
        require_tenant(ctx, self._tenant_of(item))
        return item

    def list(self, ctx: ActiveContext) -> list[T]:
        return [i for i in self._items.values() if self._tenant_of(i) == ctx.tenant_id]

    def delete(self, ctx: ActiveContext, item_id: str) -> None:
        self.get(ctx, item_id)
        del self._items[item_id]
