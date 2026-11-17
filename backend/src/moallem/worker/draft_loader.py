"""Load approved quiz drafts from immutable snapshots (Phase B).

The snapshot `content` JSON stores a full draft serialization that includes a
`preview` object matching QuizDraftPreview. This loader prefers that preview
and falls back to reconstructing from per-question preview payloads.
"""

from __future__ import annotations

from typing import Any, Protocol

from moallem.ai.quiz.contracts import QuizDraftPreview
from moallem.domain.errors import ResourceNotFound, TaskStateConflict
from moallem.domain.membership import ActiveContext


class SnapshotSource(Protocol):
    def get_current_snapshot(self, ctx: ActiveContext, task_id: str) -> Any: ...


class SnapshotDraftLoader:
    """DraftLoader implementation backed by PostgresPublicationRepository (or compatible)."""

    def __init__(self, snapshots: SnapshotSource) -> None:
        self._snapshots = snapshots

    def load_draft(
        self, *, tenant_id: str, task_id: str, snapshot_id: str
    ) -> QuizDraftPreview:
        # Membership roles are not re-checked here; the publish handler already
        # authorized PERM_QUIZ_PUBLISH. We only need a tenant-scoped read context.
        ctx = ActiveContext(
            user_id="worker",
            membership_id="worker",
            tenant_id=tenant_id,
            roles=("TEACHER",),
        )
        record = self._snapshots.get_current_snapshot(ctx, task_id)
        record_snapshot_id = str(
            getattr(record, "snapshot_id", None) or getattr(record, "id", "")
        )
        if snapshot_id and record_snapshot_id and snapshot_id != record_snapshot_id:
            # Worker should publish the snapshot bound to the publish intent.
            # If the current head moved, fail closed rather than publish a different draft.
            raise TaskStateConflict("snapshot is no longer the current head")

        content = getattr(record, "content", None)
        if not isinstance(content, dict):
            raise ResourceNotFound("snapshot content missing")

        preview_payload = content.get("preview")
        if isinstance(preview_payload, dict):
            return QuizDraftPreview.model_validate(preview_payload)

        # Fallback: rebuild from questions[].preview when top-level preview is absent
        questions_raw = content.get("questions")
        if not isinstance(questions_raw, list) or not questions_raw:
            raise TaskStateConflict("snapshot has no publishable questions")

        rebuilt_questions: list[dict[str, object]] = []
        for item in questions_raw:
            if not isinstance(item, dict):
                raise TaskStateConflict("invalid question payload in snapshot")
            q_preview = item.get("preview")
            if not isinstance(q_preview, dict):
                raise TaskStateConflict("question preview missing in snapshot")
            rebuilt_questions.append(q_preview)

        spec = content.get("spec") if isinstance(content.get("spec"), dict) else {}
        title = str(spec.get("name") or "Quiz")
        instructions = spec.get("instructions")
        schema_version = str(
            content.get("schema_version")
            or getattr(record, "schema_version", None)
            or "1.0"
        )

        return QuizDraftPreview.model_validate(
            {
                "title": title,
                "instructions": instructions,
                "questions": rebuilt_questions,
                "schema_version": schema_version,
                "total_points": sum(
                    float(q.get("points") or 0) for q in rebuilt_questions
                ),
            }
        )
