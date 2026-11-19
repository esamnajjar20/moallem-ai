"""Worker handler composition (Phase B).

Builds a TaskHandlerRegistry. The publish path is registered only when every collaborator
is supplied. The Moodle write adapter defaults to DenyAll and the permission policy to
DenyAll, so production stays fail-closed until a Staging adapter and an approved policy are
injected explicitly.
"""

from __future__ import annotations

import logging

from moallem.domain.authorization import DenyAllPolicy, PermissionPolicy, TeacherMVPPolicy
from moallem.domain.membership import MembershipRepository
from moallem.domain.secrets import SecretVault
from moallem.moodle.client import MoodleTransport
from moallem.moodle.fake_write_adapter import FakeWriteAdapter
from moallem.moodle.service import ConnectionRepository
from moallem.moodle.url_policy import PrivateNetworkProfile, Resolver
from moallem.moodle.write import DenyAllWriteAdapter, MoodleWriteAdapter
from moallem.moodle.write_service import MoodleWriteService
from moallem.worker.actor import ActorContextResolver
from moallem.worker.handlers.publish_quiz import (
    TASK_TYPE_CREATE_QUIZ,
    PublicationGateway,
    PublishQuizHandler,
)
from moallem.worker.queue import TaskHandlerRegistry

log = logging.getLogger("moallem.worker.composition")


def build_handler_registry(
    *,
    publications: PublicationGateway | None = None,
    connections: ConnectionRepository | None = None,
    vault: SecretVault | None = None,
    transport: MoodleTransport | None = None,
    resolver: Resolver | None = None,
    memberships: MembershipRepository | None = None,
    permission_policy: PermissionPolicy | None = None,
    write_adapter: MoodleWriteAdapter | None = None,
    enable_fake_write: bool = False,
    enable_teacher_policy: bool = False,
    private_profile: PrivateNetworkProfile | None = None,
) -> TaskHandlerRegistry:
    """Compose handlers for the worker process.

    Defaults:
    - No CREATE_QUIZ handler unless publications and every Moodle dependency are provided.
    - Write adapter = DenyAllWriteAdapter (FakeWriteAdapter only if enable_fake_write).
    - Permission policy = DenyAllPolicy (TeacherMVPPolicy only if enable_teacher_policy).
    """
    registry = TaskHandlerRegistry()

    if (
        publications is None
        or connections is None
        or vault is None
        or transport is None
        or resolver is None
        or memberships is None
    ):
        log.warning(
            "worker.publish_handler_not_registered",
            extra={"reason": "missing publications, membership or moodle dependencies"},
        )
        return registry

    policy: PermissionPolicy
    if permission_policy is not None:
        policy = permission_policy
    elif enable_teacher_policy:
        policy = TeacherMVPPolicy()
    else:
        policy = DenyAllPolicy()

    adapter: MoodleWriteAdapter
    if write_adapter is not None:
        adapter = write_adapter
    elif enable_fake_write:
        adapter = FakeWriteAdapter()
        log.warning("worker.using_fake_write_adapter")
    else:
        adapter = DenyAllWriteAdapter()

    write_service = MoodleWriteService(
        connections=connections,
        vault=vault,
        policy=policy,
        transport=transport,
        resolver=resolver,
        write_adapter=adapter,
        private_profile=private_profile,
    )
    registry.register(
        TASK_TYPE_CREATE_QUIZ,
        PublishQuizHandler(
            write_service=write_service,
            publications=publications,
            actors=ActorContextResolver(memberships),
        ),
    )
    log.info(
        "worker.publish_handler_registered",
        extra={
            "task_type": TASK_TYPE_CREATE_QUIZ,
            "write_adapter": type(adapter).__name__,
            "policy": type(policy).__name__,
        },
    )
    return registry
