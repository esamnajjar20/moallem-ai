"""Worker composition stays fail-closed unless every dependency is injected."""

from moallem.domain.membership import InMemoryMembershipRepository
from moallem.domain.secrets import InMemoryVault
from moallem.moodle.service import new_connection_repository
from moallem.worker.composition import build_handler_registry
from moallem.worker.handlers.publish_quiz import TASK_TYPE_CREATE_QUIZ
from tests.moodle.fakes import PUBLIC, FakeResolver, FakeTransport
from tests.worker.support import FakeGateway


def test_registry_is_empty_without_dependencies() -> None:
    registry = build_handler_registry(publications=FakeGateway())
    assert registry.registered_types == frozenset()


def test_registry_registers_publish_handler_with_all_dependencies() -> None:
    registry = build_handler_registry(
        publications=FakeGateway(),
        connections=new_connection_repository(),
        vault=InMemoryVault(),
        transport=FakeTransport(),
        resolver=FakeResolver(PUBLIC),
        memberships=InMemoryMembershipRepository(),
    )
    # `registered_types` is a property (the worker log line must not call it).
    assert sorted(registry.registered_types) == [TASK_TYPE_CREATE_QUIZ]
