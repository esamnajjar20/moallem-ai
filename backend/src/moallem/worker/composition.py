"""Worker handler composition (Phase B).

Builds a TaskHandlerRegistry. Publish path is registered only when the required
collaborators are supplied. The Moodle write adapter defaults to DenyAll so
production remains fail-closed until a Staging adapter is injected.
"""

from __future__ import annotations

import logging
from typing import Any

from moallem.domain.authorization import DenyAllPolicy, PermissionPolicy, TeacherMVPPolicy
from moallem.moodle.fake_write_adapter import FakeWriteAdapter
from moallem.moodle.write import DenyAllWriteAdapter, MoodleWriteAdapter
from moallem.moodle.write_service import MoodleWriteService
from moallem.worker.draft_loader import SnapshotDraftLoader
from moallem.worker.handlers.publish_quiz import (
    TASK_TYPE_CREATE_QUIZ,
    PublishQuizHandler,
)
from moallem.worker.queue import TaskHandlerRegistry

log = logging.getLogger("moallem.worker.composition")


def build_handler_registry(
    *,
    # Required for real publish path
    publications: Any | None = None,
    connections: Any | None = None,
    vault: Any | None = None,
    transport: Any | None = None,
    resolver: Any | None = None,
    # Optional overrides
    permission_policy: PermissionPolicy | None = None,
    write_adapter: MoodleWriteAdapter | None = None,
    enable_fake_write: bool = False,
    enable_teacher_policy: bool = False,
    private_profile: Any | None = None,
) -> TaskHandlerRegistry:
    """Compose handlers for the worker process.

    Defaults:
    - No CREATE_QUIZ handler unless publications + moodle deps are provided.
    - Write adapter = DenyAllWriteAdapter (or FakeWriteAdapter if enable_fake_write).
    - Permission policy = DenyAllPolicy (or TeacherMVPPolicy if enable_teacher_policy).
    """
    registry = TaskHandlerRegistry()

    can_publish = publications is not None and all(
        x is not None for x in (connections, vault, transport, resolver)
    )
    if not can_publish:
        log.warning(
            "worker.publish_handler_not_registered",
            extra={"reason": "missing publications or moodle dependencies"},
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
    draft_loader = SnapshotDraftLoader(publications)

    handler = PublishQuizHandler(
        write_service=write_service,
        publications=publications,
        draft_loader=draft_loader,
    )
    registry.register(TASK_TYPE_CREATE_QUIZ, handler)
    log.info(
        "worker.publish_handler_registered",
        extra={
            "task_type": TASK_TYPE_CREATE_QUIZ,
            "write_adapter": type(adapter).__name__,
            "policy": type(policy).__name__,
        },
    )
    return registry
