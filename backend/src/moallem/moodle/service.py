"""Tenant-scoped, permission-checked entry point for Moodle reads (ties P2 to P3).

Order of checks (fail closed): tenant ownership (foreign == not found, AT-015) -> permission
(DEC-027 policy; DenyAll until the matrix is approved) -> connection ACTIVE -> reveal secret.
The raw token only exists inside this call stack, wrapped in `Token`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from moallem.domain.authorization import PermissionPolicy, authorize
from moallem.domain.membership import ActiveContext
from moallem.domain.scoped import InMemoryScopedRepository
from moallem.domain.secrets import SecretRef, SecretVault
from moallem.moodle.client import MoodleClient, MoodleTransport, Token
from moallem.moodle.errors import ConnectionNotActive
from moallem.moodle.read import (
    CapabilitySnapshot,
    CourseContents,
    CoursePage,
    discover_capabilities,
    get_course_contents,
    list_teacher_courses,
)
from moallem.moodle.url_policy import PrivateNetworkProfile, Resolver, normalize_site_url

# permission_code values from Contracts/tool_registry.draft.json
PERM_CONNECTION_READ = "moodle.connection.read"
PERM_COURSE_READ = "moodle.course.read"
PERM_COURSE_CONTENT_READ = "moodle.course.content.read"


class ConnectionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISCONNECTED = "DISCONNECTED"
    CREDENTIAL_INVALID = "CREDENTIAL_INVALID"


@dataclass(frozen=True, slots=True)
class MoodleConnection:
    connection_id: str
    tenant_id: str
    site_url: str
    secret_ref: SecretRef
    status: ConnectionStatus
    moodle_user_id: int | None = None


ConnectionRepository = InMemoryScopedRepository[MoodleConnection]


def new_connection_repository() -> ConnectionRepository:
    return InMemoryScopedRepository(lambda c: c.tenant_id, lambda c: c.connection_id)


class MoodleReadService:
    def __init__(
        self,
        *,
        connections: ConnectionRepository,
        vault: SecretVault,
        policy: PermissionPolicy,
        transport: MoodleTransport,
        resolver: Resolver,
        private_profile: PrivateNetworkProfile | None = None,
    ) -> None:
        self._connections = connections
        self._vault = vault
        self._policy = policy
        self._transport = transport
        self._resolver = resolver
        self._private = private_profile

    def _client(
        self, ctx: ActiveContext, connection_id: str, permission: str
    ) -> tuple[MoodleClient, MoodleConnection]:
        conn = self._connections.get(ctx, connection_id)  # foreign/missing -> ResourceNotFound
        authorize(ctx, permission, conn.tenant_id, self._policy)
        if conn.status is not ConnectionStatus.ACTIVE:
            raise ConnectionNotActive("connection is not active")
        client = MoodleClient(
            site=normalize_site_url(conn.site_url),
            token=Token(self._vault.reveal(ctx, conn.secret_ref)),
            transport=self._transport,
            resolver=self._resolver,
            private_profile=self._private,
        )
        return client, conn

    def discover_capabilities(
        self,
        ctx: ActiveContext,
        connection_id: str,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> CapabilitySnapshot:
        client, _ = self._client(ctx, connection_id, PERM_CONNECTION_READ)
        return discover_capabilities(client, now=now)

    def list_courses(
        self,
        ctx: ActiveContext,
        connection_id: str,
        *,
        cursor: str | None = None,
        page_size: int = 25,
    ) -> CoursePage:
        client, conn = self._client(ctx, connection_id, PERM_COURSE_READ)
        if conn.moodle_user_id is None:
            raise ConnectionNotActive("connection has no validated moodle user")
        return list_teacher_courses(
            client, moodle_user_id=conn.moodle_user_id, cursor=cursor, page_size=page_size
        )

    def course_contents(
        self,
        ctx: ActiveContext,
        connection_id: str,
        course_id: str,
        *,
        include_file_metadata: bool = True,
    ) -> CourseContents:
        client, conn = self._client(ctx, connection_id, PERM_COURSE_CONTENT_READ)
        return get_course_contents(
            client,
            connection_id=conn.connection_id,
            course_id=course_id,
            include_file_metadata=include_file_metadata,
        )
