# ADR-018 — AI provider, model revision, and processing region

**Status: OPEN — no provider, model, or region is selected.**  
**Decision owners:** Product, Privacy, Education, and FinOps.  
**Scope:** P5-01 AI Gateway and all future processing of Moallem prompts, course material, files,
learner-related data, generated drafts, and provider usage metadata.

## Context

Moallem requires an AI provider for the teacher-only Quiz Creation MVP. The project must evaluate
at least two managed-provider candidates with a synthetic Arabic education benchmark before a
provider is selected. The decision affects privacy, international data transfers, Arabic quality,
provider terms and retention, latency, availability, unit cost, model revisions, and fallback.

The project currently contains a provider-neutral request contract, a bounded Chat Completions-
compatible HTTPS adapter, an execution gateway, and a PostgreSQL usage ledger. These components
are code interfaces, not approval to send course or learner data to a third party.

## Options to evaluate

1. **Managed model API:** faster integration and elastic capacity; requires explicit contractual,
   regional, privacy, retention, and per-token cost review.
2. **Self-hosted model:** more control over data path and deployment; requires GPU capacity,
   inference operations, patching, safety evaluation, and cost/latency measurements.
3. **Multiple providers:** potential resilience and portability; adds policy, evaluation, contract,
   and operational complexity. No automatic cross-provider fallback is permitted for sensitive
   requests without an explicit data-region approval.

No option is selected by this ADR draft.

## Required decision evidence

Before approval, record at least two candidate evaluations using the same versioned synthetic
Arabic benchmark and prompt set. Each candidate must have a documented:

- exact provider, immutable model revision, API endpoint, processing region, and supported response
  format;
- allowed data classes and explicit exclusions, retention/training terms, subprocessors, deletion
  behavior, transfer mechanism, and incident obligations;
- Arabic factuality, source-grounding, answer correctness, clarity, and pedagogical quality results
  with human-reviewed evidence;
- p50/p95 latency, rate limits, availability evidence, token accounting behavior, and measured
  cost for representative synthetic requests;
- failure classification, timeout and `UNKNOWN` handling, and approved fallback behavior;
- secret ownership, endpoint allow-list, network-egress rule, key rotation, and operational owner.

The benchmark must not contain real teacher, learner, or Moodle data. Its domain, grade levels,
question types, reviewers, rubric weights, and acceptance thresholds must be approved under
DEC-033/DEC-034 and ADR-024; they are not inferred by this ADR.

## Implementation baseline (not a vendor decision)

- Keep `AIRequest`, `ProviderIdentity`, `ModelPricing`, and `AIExecutionPermit` provider-neutral.
- Use an exact-ID provider registry. It must not silently select another provider or perform
  cross-region fallback.
- The current `OpenAICompatibleHTTPProvider` supports only the Chat Completions wire format;
  providers with a different contract require a separate adapter and contract tests.
- Pin the model identity and version in deployment configuration. A response model-ID match does
  not independently prove model revision or processing region; those are still verified through
  provider documentation, contractual evidence, and deployment configuration.
- Provider endpoint hostnames are exact allow-list entries. TLS verification remains enabled,
  environment proxy inheritance and redirects are disabled, and network egress must separately
  enforce the approved destination.
- Do not log prompt or completion bodies. Persist hashes, model metadata, token usage, cost,
  provenance references, and safe failure codes only.
- Every invocation must pass a server-issued execution permit and durable budget reservation
  before provider dispatch. The model cannot set identity, tenant scope, price, budget, or policy.
- Ambiguous post-dispatch outcomes remain `UNKNOWN`; no automatic retry or fallback is allowed.

## Go / no-go conditions

**Go** only after all decision owners approve the selected provider/model/revision/region, permitted
 data classes, terms, privacy and retention handling, benchmark acceptance, price table, budget
limits, egress policy, and fallback policy. A production `AIExecutionAuthorizer` must atomically
reserve task and tenant-period budgets and support settlement and reconciliation.

**No-go** when any of the following is missing: provider/model pin, region, approved data classes,
privacy terms, price version, either cost ceiling, durable reservation, or a trusted operator path
for `UNKNOWN` outcomes. The runtime must fail closed.

## Consequences

The existing adapter and the optional settings/factory are usable for local contract tests and
future approved composition. They do not enable the model. `DenyAllAIExecution` remains the default;
P5 stays partial until the evidence above is approved and verified.
