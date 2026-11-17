# Phase B — Implementation Status

**Date:** 2026-11-17  
**Goal:** Vertical Slice end-to-end (approve → publish → verify on Moodle)

## Scope

| ID | Item | Status |
|----|------|--------|
| B1 | Moodle Read against Staging | Blocked on A1 evidence |
| B2 | Moodle Write Adapter | Skeleton + design + DenyAll/Fake done |
| B3 | Worker Handler (publish) | **Handler + DraftLoader + composition done** |
| B4 | Real AI Gateway | Blocked on A3 credentials |
| B5 | Integration tests (Postgres + Staging) | Pending environment |

---

## Delivered code

| Path | Role |
|------|------|
| `moodle/write.py` | DTOs + Protocol + DenyAllWriteAdapter |
| `moodle/write_service.py` | Orchestration (auth → create → verify) |
| `moodle/question_mapping.py` | Draft → QuestionCreateSpec |
| `moodle/fake_write_adapter.py` | Test double |
| `worker/draft_loader.py` | **SnapshotDraftLoader** from snapshot JSON |
| `worker/composition.py` | **build_handler_registry** |
| `worker/handlers/publish_quiz.py` | PublishQuizHandler |
| `worker/main.py` | Wires composition (fail-closed; no live Moodle until deps injected) |
| Tests | `test_write`, `test_question_mapping`, `test_draft_loader` |

## Safety

- CREATE_QUIZ handler is **not registered** in production until connections + vault + transport + resolver + write adapter are passed to `build_handler_registry`.
- Default write adapter remains DenyAll.
- Default permission policy remains DenyAll unless `enable_teacher_policy=True`.

## Enable publish path (after A1)

```python
handlers = build_handler_registry(
    publications=PostgresPublicationRepository(sessions),
    connections=new_postgres_connection_repository(sessions),
    vault=...,
    transport=...,
    resolver=...,
    write_adapter=StagingMoodleWriteAdapter(...),
    enable_teacher_policy=True,
)
```

## Remaining to close Phase B

1. A1 Moodle Staging evidence
2. StagingMoodleWriteAdapter with confirmed WS functions
3. Inject Moodle deps in worker composition for Staging only
4. One Staging integration test (skipped by default)
