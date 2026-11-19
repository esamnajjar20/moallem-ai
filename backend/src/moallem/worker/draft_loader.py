"""Load approved quiz drafts from immutable snapshots (Phase B).

The snapshot ``content`` always carries a ``preview`` object (see
``publishing_repository._draft_content``); it is validated with the strict
``QuizDraftPreview`` model. There is deliberately no reconstruction fallback: a snapshot
without a valid preview is not publishable.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from moallem.ai.quiz.contracts import QuizDraftPreview
from moallem.domain.errors import ResourceNotFound, TaskStateConflict


def draft_from_snapshot_content(content: object) -> QuizDraftPreview:
    """Validate and return the publishable preview stored in an immutable snapshot."""
    if not isinstance(content, Mapping):
        raise ResourceNotFound("snapshot content missing")
    preview: Any = content.get("preview")
    if not isinstance(preview, Mapping):
        raise TaskStateConflict("snapshot has no publishable preview")
    return QuizDraftPreview.model_validate(dict(preview))
