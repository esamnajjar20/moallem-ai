import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from moallem.api.app import create_app
from moallem.config import Environment, Settings
from moallem.domain.authorization import StaticPolicy
from moallem.domain.membership import ActiveContext
from moallem.domain.secrets import InMemoryVault
from moallem.moodle.service import ConnectionStatus, MoodleConnection, new_connection_repository
from moallem.domain.membership import (
    InMemoryMembershipRepository,
    Membership,
    MembershipStatus,
)
from moallem.persistence.task_repository import PersistedTaskEvent, PersistedTaskEventPage

_USER_ID = str(uuid.uuid4())
_TENANT_ID = str(uuid.uuid4())
_MEMBERSHIP_ID = str(uuid.uuid4())
_CONNECTION_ID = str(uuid.uuid4())


def _client(*, allow_tasks: bool = False) -> TestClient:
    membership_repo = InMemoryMembershipRepository(
        {
            _MEMBERSHIP_ID: Membership(
                membership_id=_MEMBERSHIP_ID,
                user_id=_USER_ID,
                tenant_id=_TENANT_ID,
                roles=("TEACHER",),
                status=MembershipStatus.ACTIVE,
            )
        }
    )
    policy = (
        StaticPolicy({"TEACHER": frozenset({"task.create", "task.read"})}) if allow_tasks else None
    )
    app = create_app(
        Settings(env=Environment.TEST, _env_file=None),
        checks=[],
        membership_repo=membership_repo,
        permission_policy=policy,
    )
    return TestClient(app)


def _headers() -> dict[str, str]:
    return {
        "X-Dev-User-ID": _USER_ID,
        "X-Active-Membership-ID": _MEMBERSHIP_ID,
        "Idempotency-Key": "x" * 22,
    }


def _payload() -> dict[str, str]:
    return {
        "task_type": "CREATE_QUIZ",
        "connection_id": _CONNECTION_ID,
        "course_id": "course-1",
        "prompt": "Create a draft quiz",
    }


def test_task_routes_remain_fail_closed_without_an_explicit_policy() -> None:
    response = _client().post("/tasks", headers=_headers(), json=_payload())

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_task_creation_reports_unconfigured_database_instead_of_faking_success() -> None:
    response = _client(allow_tasks=True).post("/tasks", headers=_headers(), json=_payload())

    assert response.status_code == 503
    assert response.json()["code"] == "INTERNAL_ERROR"


def test_create_task_returns_versioned_status_and_events_urls() -> None:
    context_connection_id = str(uuid.uuid4())
    ctx_vault = InMemoryVault()
    membership_repo = InMemoryMembershipRepository(
        {
            _MEMBERSHIP_ID: Membership(
                membership_id=_MEMBERSHIP_ID,
                user_id=_USER_ID,
                tenant_id=_TENANT_ID,
                roles=("TEACHER",),
                status=MembershipStatus.ACTIVE,
            )
        }
    )
    connection_repo = new_connection_repository()
    active_context = ActiveContext(_USER_ID, _MEMBERSHIP_ID, _TENANT_ID, ("TEACHER",))
    secret_ref = ctx_vault.put(active_context, "synthetic-moodle-token")
    connection_repo.add(
        active_context,
        MoodleConnection(
            context_connection_id,
            _TENANT_ID,
            "https://moodle.example.edu",
            secret_ref,
            ConnectionStatus.ACTIVE,
            42,
        ),
    )
    app = create_app(
        Settings(
            env=Environment.TEST,
            idempotency_hmac_key="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
            idempotency_retention_seconds=86400,
            _env_file=None,
        ),
        checks=[],
        membership_repo=membership_repo,
        permission_policy=StaticPolicy({"TEACHER": frozenset({"task.create"})}),
    )

    class TaskRepository:
        def create_idempotent(self, _context, **_kwargs):
            return SimpleNamespace(
                task=SimpleNamespace(
                    task_id=str(uuid.uuid4()), created_at=datetime.now(UTC)
                )
            )

    app.state.task_repository = TaskRepository()
    app.state.moodle_connection_repository = connection_repo
    response = TestClient(app).post(
        "/api/v1/tasks",
        headers={
            "X-Dev-User-ID": _USER_ID,
            "X-Active-Membership-ID": _MEMBERSHIP_ID,
            "Idempotency-Key": "x" * 22,
        },
        json={
            **_payload(),
            "connection_id": context_connection_id,
        },
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    assert response.json()["status_url"] == f"/api/v1/tasks/{task_id}"
    assert response.json()["events_url"] == f"/api/v1/tasks/{task_id}/events"


def test_task_request_rejects_unknown_fields_without_echoing_values() -> None:
    payload = {**_payload(), "unexpected_secret": "must-not-be-echoed"}
    response = _client().post("/tasks", headers=_headers(), json=payload)

    assert response.status_code == 400
    assert "must-not-be-echoed" not in response.text
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_task_event_endpoint_serializes_recovery_events() -> None:
    task_id = uuid.uuid4()
    event_id = uuid.uuid4()

    class RecoveryEventRepository:
        def list_event_page(self, context, task_id_value, *, after_sequence, limit):
            assert task_id_value == str(task_id)
            return PersistedTaskEventPage(
                items=[
                    PersistedTaskEvent(
                        event_id=str(event_id),
                        sequence=1,
                        event_type="TASK_RECOVERED",
                        from_status=None,
                        to_status=None,
                        message_code=None,
                        occurred_at=datetime.now(UTC),
                    )
                ],
                has_more=False,
                last_sequence=1,
                oldest_available_sequence=1,
            )

    client = _client(allow_tasks=True)
    client.app.state.task_repository = RecoveryEventRepository()
    client.app.state.settings = Settings(
        env=Environment.TEST,
        _env_file=None,
        event_cursor_hmac_key="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
    )
    response = client.get(
        f"/tasks/{task_id}/events",
        headers={
            "X-Dev-User-ID": _USER_ID,
            "X-Active-Membership-ID": _MEMBERSHIP_ID,
        },
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["event_type"] == "TASK_RECOVERED"


def test_snapshot_and_approval_routes_remain_fail_closed_without_permission_policy() -> None:
    task_id = uuid.uuid4()
    app = create_app(
        Settings(env=Environment.TEST, _env_file=None),
        checks=[],
        membership_repo=InMemoryMembershipRepository(
            {
                _MEMBERSHIP_ID: Membership(
                    membership_id=_MEMBERSHIP_ID,
                    user_id=_USER_ID,
                    tenant_id=_TENANT_ID,
                    roles=("TEACHER",),
                    status=MembershipStatus.ACTIVE,
                )
            }
        ),
    )
    app.state.publication_repository = object()
    client = TestClient(app)
    headers = {
        "X-Dev-User-ID": _USER_ID,
        "X-Active-Membership-ID": _MEMBERSHIP_ID,
        "Idempotency-Key": "p" * 22,
    }
    snapshot = client.get(f"/api/v1/tasks/{task_id}/snapshot", headers=headers)
    assert snapshot.status_code == 403
    approval = client.post(
        f"/api/v1/tasks/{task_id}/approvals",
        headers=headers,
        json={
            "decision": "APPROVED",
            "snapshot_id": str(uuid.uuid4()),
            "snapshot_hash": "a" * 64,
        },
    )
    assert approval.status_code == 403


def test_approval_route_uses_server_ttl_hmac_and_never_accepts_destination() -> None:
    from moallem.persistence.publishing_repository import ApprovalResult
    from moallem.domain.publishing import ApprovalDecision

    task_id = uuid.uuid4()
    snapshot_id = uuid.uuid4()
    observed: dict[str, object] = {}

    class FakePublicationRepository:
        def record_approval(self, context, **kwargs):
            observed["membership_id"] = context.membership_id
            observed.update(kwargs)
            now = datetime.now(UTC)
            return ApprovalResult(
                approval_id=str(uuid.uuid4()),
                task_id=str(task_id),
                snapshot_id=str(snapshot_id),
                snapshot_hash="b" * 64,
                decision=ApprovalDecision.APPROVED,
                decided_at=now,
                expires_at=now.replace(year=now.year + 1),
            )

    membership_repo = InMemoryMembershipRepository(
        {
            _MEMBERSHIP_ID: Membership(
                membership_id=_MEMBERSHIP_ID,
                user_id=_USER_ID,
                tenant_id=_TENANT_ID,
                roles=("TEACHER",),
                status=MembershipStatus.ACTIVE,
            )
        }
    )
    app = create_app(
        Settings(
            env=Environment.TEST,
            idempotency_hmac_key="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
            idempotency_retention_seconds=86400,
            approval_ttl_seconds=3600,
            _env_file=None,
        ),
        checks=[],
        membership_repo=membership_repo,
        permission_policy=StaticPolicy({"TEACHER": frozenset({"quiz.approve"})}),
    )
    app.state.publication_repository = FakePublicationRepository()
    response = TestClient(app).post(
        f"/api/v1/tasks/{task_id}/approvals",
        headers={
            "X-Dev-User-ID": _USER_ID,
            "X-Active-Membership-ID": _MEMBERSHIP_ID,
            "Idempotency-Key": "p" * 22,
        },
        json={
            "decision": "APPROVED",
            "snapshot_id": str(snapshot_id),
            "snapshot_hash": "b" * 64,
        },
    )
    assert response.status_code == 201
    assert observed["approval_ttl_seconds"] == 3600
    assert observed["snapshot_hash_value"] == "b" * 64
    assert "destination" not in observed
    assert observed["decision"] is ApprovalDecision.APPROVED


def test_verified_task_result_is_returned_only_after_repository_verification() -> None:
    task_id = uuid.uuid4()

    class FakePublicationRepository:
        def get_verified_result(self, context, requested_task_id):
            assert requested_task_id == str(task_id)
            assert context.tenant_id == _TENANT_ID
            return {
                "external_object_type": "QUIZ",
                "external_object_id": "quiz-123",
                "verification_status": "VERIFIED",
                "verified_at": datetime.now(UTC).isoformat(),
                "snapshot_hash": "a" * 64,
                "course_id": "course-1",
                "expected_content_match": True,
            }

    app = create_app(
        Settings(env=Environment.TEST, _env_file=None),
        checks=[],
        membership_repo=InMemoryMembershipRepository(
            {
                _MEMBERSHIP_ID: Membership(
                    membership_id=_MEMBERSHIP_ID,
                    user_id=_USER_ID,
                    tenant_id=_TENANT_ID,
                    roles=("TEACHER",),
                    status=MembershipStatus.ACTIVE,
                )
            }
        ),
        permission_policy=StaticPolicy({"TEACHER": frozenset({"task.read"})}),
    )
    app.state.publication_repository = FakePublicationRepository()
    response = TestClient(app).get(
        f"/api/v1/tasks/{task_id}/result",
        headers={
            "X-Dev-User-ID": _USER_ID,
            "X-Active-Membership-ID": _MEMBERSHIP_ID,
        },
    )
    assert response.status_code == 200
    assert response.json()["verification_status"] == "VERIFIED"
    assert response.json()["external_object_id"] == "quiz-123"


def test_verified_task_result_route_is_fail_closed_without_read_permission() -> None:
    task_id = uuid.uuid4()
    app = create_app(
        Settings(env=Environment.TEST, _env_file=None),
        checks=[],
        membership_repo=InMemoryMembershipRepository(
            {
                _MEMBERSHIP_ID: Membership(
                    membership_id=_MEMBERSHIP_ID,
                    user_id=_USER_ID,
                    tenant_id=_TENANT_ID,
                    roles=("TEACHER",),
                    status=MembershipStatus.ACTIVE,
                )
            }
        ),
    )
    app.state.publication_repository = object()
    response = TestClient(app).get(
        f"/api/v1/tasks/{task_id}/result",
        headers={
            "X-Dev-User-ID": _USER_ID,
            "X-Active-Membership-ID": _MEMBERSHIP_ID,
        },
    )
    assert response.status_code == 403
