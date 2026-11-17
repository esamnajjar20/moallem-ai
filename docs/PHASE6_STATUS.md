# P6 — Quiz Draft & Quality

**Status: PARTIAL / NOT READY FOR PILOT.** The local domain/application foundation for source-grounded quiz drafts and deterministic quality checks is implemented. P6 is not closed because the approved question-type set, educational scope, rubric, golden evaluation set, human-review workflow, provider execution policy, durable draft persistence, and API/Worker integration are not available.

**Assessment date:** 2026-11-17  
**Baseline:** Engineering Documentation v2.4; Implementation Control v2.5.  
**Roadmap position:** P6, after the P5 AI Gateway/model/provider foundation and before P7 Approval & Publish.

## Scope and decisions

P6 is limited to teacher-reviewable quiz drafts and quality validation. It does not approve, publish, or write quizzes to Moodle.

- **DEC-033 — question types and Question DTO:** OPEN. Product + Education must select the initial MVP question types and their answer, scoring, distractor, and media semantics. The runtime registry therefore starts empty; a type cannot be generated until a server-side strict schema and preview adapter are explicitly registered.
- **DEC-034 — educational scope and quality thresholds:** OPEN. Education must set grade/stage, subject, curriculum, language, source accuracy requirements, evaluation method, and acceptance thresholds.
- **ADR-024 — educational AI quality governance:** the principle is baselined, but rubric version, golden set, reviewers, and acceptance threshold still need Education Lead approval.
- **P5 execution dependencies:** ADR-018 provider/model/region/privacy approval, a production AI execution authorizer, durable budget reservation/settlement/reconciliation, and provider execution wiring remain open. `DenyAllAIExecution` must remain the default.

## Implemented in this pass

### Typed draft contracts and question-type registry

- Added strict/frozen `QuizSpec`, `EducationalScope`, `QuestionDraftPreview`, `QuizDraftPreview`, and provider-output envelopes with `extra='forbid'` and input bounds.
- Added an exact server-owned `QuestionTypeRegistry`. Every type requires a strict Pydantic payload model, a pinned schema version, and a preview adapter. Registry and rubric entries are read-only after construction.
- No production question type is preselected or silently enabled. The only `SINGLE_CHOICE` schema used in this pass is a test fixture and is not shipped as a production registration.
- Added OpenAPI alignment for the provisional `QuizSpec` / preview fields and executable contract tests. This does not freeze the contract or close DEC-033.

### Source-grounded draft generation service

- Added `QuizDraftGenerationService` that constructs a bounded `AIRequest` and calls only the injected `AIGateway`; it does not contact a provider directly.
- Prompts distinguish system/developer instructions from JSON-encoded teacher instructions and source context. Course excerpts are explicitly marked untrusted data, never instructions.
- Before dispatch, tenant/course scope, unique chunk identifiers, character totals, and SHA-256 content hashes are checked again at the generation boundary.
- Provider output must be one strict JSON object. The service enforces exact question count, requested registered types only, strict per-type payload schemas, and source UUIDs limited to the supplied context.
- Drafts carry stable invocation-derived IDs, schema/prompt versions, request/content hashes, provider identity, token usage, source chunk hashes, and source citation metadata (file ID/version, page, section, SHA-256) alongside each exact quoted evidence reference.
- Citation metadata is included in the draft content hash and is rechecked by the quality validator against the current source context.
- Unsupported status and its reason are surfaced in the per-question preview. No source UUID can be invented by the model.

### Deterministic quality validation

- Added `QuizQualityValidator` and a server-owned rubric registry, empty by default.
- Hard checks cover source context changes, type/schema drift, payload/preview mismatch, question count, duplicate normalized stems, missing/duplicate/out-of-scope source references, quotes not present in source text, unsupported-state consistency, and total points above the configured maximum grade.
- Missing or unapproved rubric, incomplete education scope, unsupported source claims, and factual/answer/alignment/fairness/age-suitability review needs are reported as warnings.
- The validator never certifies educational correctness based solely on the generating model. Human review remains mandatory, and `publish_allowed` is always `false`.
- No scoring thresholds or rubric are invented while DEC-034 is open.

## Deliberately not implemented / not enabled

- No production question types are registered until DEC-033 approval.
- No final educational rubric, grade/subject taxonomy, golden dataset, reviewer agreement report, or calibrated pass threshold exists; semantic correctness is not proven by deterministic checks.
- No durable quiz-draft/quality-report repository or database migration was added in this pass. Returned draft objects are application-domain results, not a persisted task snapshot.
- No API routes or Worker task handler were enabled. The repository's Worker composition still has no approved AI quiz handler; adding one before authorization/budget/persistence decisions would bypass the project gates.
- No direct provider call, fallback model, tool execution, Moodle API call, quiz creation, approval, or publish operation is present.
- Existing tool-registry entries for generation/quality are not marked executable.

## Verification

| Check | Result | Qualification |
|---|---:|---|
| P6-focused tests | **25 passed** | Contract parity, empty registry, explicit unsupported status, source hashes/scope, strict generation output, exact quotes, duplicate stems, total points, and human-review warnings. |
| AI + P6 + config tests | **88 passed** | Provider gateway/HTTP adapter/model contracts plus P6; mocked/local tests only. |
| Full backend suite | **467 passed, 45 skipped, 1 failed** | 45 PostgreSQL tests skipped because no `MOALLEM_TEST_DATABASE_URL`; the single failure is `test_docs_disabled_in_production`, which cannot create the PostgreSQL engine because `psycopg` is missing from this authoring environment. This is environmental and unrelated to P6; no test was removed or deselected. |
| `compileall` | **PASS** | Python 3.13.5. Project requires Python `>=3.12,<3.13`, so the pinned runtime still needs CI verification. |
| OpenAPI YAML parsing | **PASS** | YAML parsed successfully and exposes 40 component schemas; selected runtime/OpenAPI contract parity is tested. |
| Ruff / mypy | **NOT RUN** | Neither executable is installed in this environment. |
| PostgreSQL migration/persistence | **NOT APPLICABLE / NOT IMPLEMENTED** | This pass did not add a draft persistence schema/repository. |
| Live provider / Moodle | **NOT RUN** | Execution is still gated; no live AI or Moodle write was attempted. |

No production provider, PostgreSQL persistence, or Moodle integration test is implied by unit tests.

## Exit criteria before declaring P6 closed

1. Resolve DEC-033 and register only the approved MVP question types with versioned schemas, canonical answer/scoring behavior, and Moodle mapping.
2. Resolve DEC-034 and ADR-024: approved educational scope, rubric, golden dataset, reviewers, inter-reviewer process, and justified thresholds.
3. Add durable draft snapshots and immutable validation reports with tenant/task/source foreign-key constraints, idempotency, audit trail, and migration/integration tests.
4. Wire the generation/quality tools through the approved task handler and public preview API only after P5 authorizer, durable budget controls, privacy approval, and provider/region setup are verified.
5. Prove failure, cancellation, unknown provider outcome, retry/idempotency, source version drift, and tenant-isolation behavior with PostgreSQL integration tests.
6. Run the full CI gate on the pinned Python 3.12 environment, PostgreSQL, Ruff, and mypy; then complete teacher acceptance testing on real Arabic curriculum material.

**Decision: P6 remains PARTIAL / NOT READY.** The service foundation is implemented, but no live AI quiz generation is enabled and no educational-quality guarantee is claimed.
