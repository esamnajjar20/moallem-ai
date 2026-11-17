# Moodle Write Adapter — Design (Phase B Preparation)

**Status:** Design ready for implementation  
**Date:** 2026-11-17  
**Depends on:** A1 (Staging evidence), A2 (TeacherMVPPolicy), P7 publishing domain

## Goal

Enable the Vertical Slice publish step:

> Approved snapshot → Moodle creates a Quiz activity + questions → read-back verification → ledger COMPLETED / NEEDS_RECONCILIATION

## Design Principles (match existing codebase)

1. **Fail-closed by default** — no live side effect until a concrete adapter is injected.
2. **Same security posture as Read** — Token only in POST body, pinned URL, no redirects, size/time limits, sanitised errors.
3. **Tenant + Permission first** — `authorize(..., PERM_QUIZ_PUBLISH, ...)` then connection ACTIVE.
4. **Idempotency** — every write is keyed by `external_operation_key` derived from `PublishIntent`.
5. **No guesswork on Moodle functions** — exact WS function names and payload shapes are **OPEN** until Staging evidence (A1) confirms them.
6. **Read-back verification is mandatory** — never claim COMPLETED without proving the quiz exists and matches critical fields.
7. **Separation** — pure mapping/parsing in `write.py`; orchestration + auth in `MoodleWriteService`.

---

## Package Layout

```
backend/src/moallem/moodle/
  client.py          # existing
  transport.py       # existing
  read.py            # existing
  write.py           # NEW — DTOs, pure call helpers, parsers
  service.py         # existing read service; Write service can live here or in write_service.py
  errors.py          # existing (extend if needed)
```

Optional later:

```
backend/src/moallem/moodle/write_service.py
```

---

## Core Interfaces

### 1. Input from Publishing domain

```python
# Already exists in domain/publishing.py
SnapshotDescriptor
ApprovalRecord
PublishIntent          # contains external_operation_key
PublishPreflight       # must be ready
```

The Write Adapter **never** accepts raw client-supplied course/quiz IDs for the side effect.
Destination comes only from the server-side snapshot + connection.

### 2. New DTOs (`moodle/write.py`)

```python
@dataclass(frozen=True, slots=True)
class QuizCreateRequest:
    """Server-derived request to create a quiz activity."""
    course_id: str
    section_id: int | None          # optional; Moodle may default
    name: str                       # quiz title
    intro: str                      # HTML-stripped / bounded
    time_open: datetime | None
    time_close: datetime | None
    external_operation_key: str     # idempotency / correlation

@dataclass(frozen=True, slots=True)
class QuestionCreateSpec:
    """One question to add. Mapped from internal QuestionDraftPreview."""
    question_type: str              # "multichoice" | "truefalse" | "shortanswer" | ...
    name: str
    text: str                       # stem
    default_mark: Decimal
    options: tuple[QuestionOptionSpec, ...]
    correct_answer: str | None
    general_feedback: str | None

@dataclass(frozen=True, slots=True)
class QuestionOptionSpec:
    text: str
    is_correct: bool
    fraction: Decimal               # 0..1 for multichoice

@dataclass(frozen=True, slots=True)
class QuizCreateResult:
    """What Moodle returned after create (untrusted — must be re-read)."""
    moodle_quiz_id: int
    moodle_cmid: int | None         # course module id
    raw_reference: str              # opaque correlation if any

@dataclass(frozen=True, slots=True)
class QuizVerification:
    """Read-back proof that the publish succeeded."""
    moodle_quiz_id: int
    name_matches: bool
    question_count: int
    course_id_matches: bool
    verified_at: datetime
```

### 3. Protocol — MoodleWriteAdapter

```python
class MoodleWriteAdapter(Protocol):
    """Side-effecting adapter. Only concrete implementations talk to Moodle."""

    def create_quiz(
        self,
        client: MoodleClient,
        request: QuizCreateRequest,
        questions: Sequence[QuestionCreateSpec],
    ) -> QuizCreateResult:
        """Create quiz activity + questions. Must be idempotent on external_operation_key
        where the target site supports it (or emulate via lookup-before-create).
        """
        ...

    def verify_quiz(
        self,
        client: MoodleClient,
        *,
        course_id: str,
        moodle_quiz_id: int,
        expected_name: str,
        expected_question_count: int,
    ) -> QuizVerification:
        """Read-back. Raises or returns verification with flags; never trusts create response alone."""
        ...
```

### 4. Orchestration — MoodleWriteService

```python
class MoodleWriteService:
    def __init__(
        self,
        *,
        connections: ConnectionRepository,
        vault: SecretVault,
        policy: PermissionPolicy,
        transport: MoodleTransport,
        resolver: Resolver,
        write_adapter: MoodleWriteAdapter,   # injected; no default that writes
        private_profile: PrivateNetworkProfile | None = None,
    ) -> None: ...

    def publish_approved_quiz(
        self,
        ctx: ActiveContext,
        *,
        connection_id: str,
        snapshot: SnapshotDescriptor,
        intent: PublishIntent,
        questions: Sequence[QuestionCreateSpec],
        quiz_name: str,
        quiz_intro: str = "",
    ) -> tuple[QuizCreateResult, QuizVerification]:
        """
        Order of checks (fail-closed):
        1. authorize(ctx, PERM_QUIZ_PUBLISH, snapshot.tenant_id, policy)
        2. connection ACTIVE + secret reveal
        3. (optional) capability probe if Staging evidence requires it
        4. write_adapter.create_quiz(...)
        5. write_adapter.verify_quiz(...)
        6. return both results for the worker to ledger
        """
        ...
```

Default composition remains **no write adapter** (or a `DenyAllWriteAdapter` that raises).

---

## Question Type Mapping (MVP)

Only these types are in scope until DEC-033 expands:

| Internal type (approx) | Moodle qtype     | Notes                                      |
|------------------------|------------------|--------------------------------------------|
| multichoice            | multichoice      | single or multi correct via fraction       |
| truefalse              | truefalse        |                                            |
| shortanswer            | shortanswer      |                                            |

Unsupported types are rejected **before** any Moodle call (map to quality gate / draft flag).

Mapping lives in pure functions:

```python
def map_question_draft_to_spec(draft: QuestionDraftPreview) -> QuestionCreateSpec: ...
```

---

## Moodle Web Service Functions (OPEN — must be confirmed on Staging)

These are **candidates only**. Exact names, parameters, and availability are recorded in A1 evidence:

| Purpose                    | Candidate function(s)                          | Status   |
|---------------------------|-------------------------------------------------|----------|
| Create quiz activity      | site-specific / `local_*` / module edit APIs    | OPEN     |
| Add questions to quiz     | question bank + `mod_quiz_*` variants           | OPEN     |
| Get quiz by id            | `mod_quiz_get_quizzes_by_courses` or equivalent | OPEN     |
| Capability check          | `core_capability_get_user_capabilities` etc.    | OPEN     |

**Rule:** No function name is hard-coded as “the” production path until Staging evidence lists the enabled functions and a successful manual create has been observed.

Until then the adapter implementation can:

- use a **StagingConfirmedWriteAdapter** that only activates when a config flag + evidence hash is present, or
- keep a pure in-memory / fixture adapter for tests.

---

## Idempotency & Unknown Outcomes

- `external_operation_key` from `PublishIntent` is the correlation ID.
- Preferred strategy: **lookup-before-create** when the site allows searching by name/tag/idnumber.
- If create times out after possible success → state `NEEDS_RECONCILIATION` (already in P7).
- Never automatic retry of a write that may have partially succeeded without reconciliation logic.

---

## Error Mapping

Reuse existing `Moodle*` errors:

| Situation                        | Error                         |
|----------------------------------|-------------------------------|
| Token invalid / expired          | `MoodleCredentialInvalid`     |
| Function not available           | `MoodleFunctionNotAvailable`  |
| No capability on course          | `MoodlePermissionDenied`      |
| Network / timeout / 5xx          | `MoodleUnavailable`           |
| Response shape unexpected        | `MoodleResponseInvalid`       |
| Verification failed after create | domain-level conflict / FAILED|

---

## Worker Integration (Phase B later)

```
Worker handler (publish_quiz):
  1. Load task + snapshot + latest approval
  2. Run PublishAuthorizer.preflight → require_ready()
  3. Map draft questions → QuestionCreateSpec[]
  4. MoodleWriteService.publish_approved_quiz(...)
  5. Ledger:
       - success + verification OK → COMPLETED
       - create OK, verification ambiguous → NEEDS_RECONCILIATION
       - hard failure → FAILED (with safe code)
```

---

## Test Strategy

| Layer                    | Approach                                      |
|--------------------------|-----------------------------------------------|
| Pure mapping / parsing   | Unit tests with synthetic Moodle JSON         |
| Adapter contract         | Protocol tests + fixture transport            |
| Service orchestration    | Inject DenyAll / Fake adapter; assert auth order |
| Staging integration      | Skipped until A1 evidence present             |
| End-to-end               | One happy-path test against real Staging      |

---

## Safety Boundaries

- No default write implementation that reaches the network.
- `DenyAllPublishAuthorizer` and absence of `MoodleWriteAdapter` remain the production defaults.
- Teacher-facing API never receives Moodle IDs to “force” a publish; only server-side snapshot + approval.

---

## Implementation Order (when starting Phase B coding)

1. Add DTOs + `MoodleWriteAdapter` protocol + `DenyAllWriteAdapter` in `write.py`.
2. Implement `map_question_draft_to_spec` for the 3 MVP types.
3. Implement `MoodleWriteService` orchestration (auth + connection + call + verify).
4. Add Fake/Fixture adapter for unit tests.
5. After A1 evidence: implement `StagingMoodleWriteAdapter` with confirmed function names.
6. Wire worker handler + ledger transitions.
7. One Staging integration test (marked, skipped by default).

---

## Open Items (must close with Staging)

- [ ] Exact WS functions for create quiz + add questions on the target site
- [ ] Whether `idnumber` or another field can carry `external_operation_key`
- [ ] Section placement rules
- [ ] Maximum questions / payload size observed
- [ ] Capability names required for the teacher token
