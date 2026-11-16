# Moallem AI Engineering Documentation Package v2.4

**Purpose:** Planning specification baseline for the teacher-only, mixed-execution product and narrow end-to-end Quiz Creation MVP. v2.4 adds concrete proposed design baselines for planning gates P0-H through P0-L. It is not implementation, owner sign-off, or Moodle compatibility certification.

## Contents and precedence
- `Specifications/` preserves v2.0 source specifications and adds v2.2/v2.3/v2.4 amendment layers. A newer addendum supersedes older planning text only for the subject it explicitly covers.
- `Planning/Unified_Decision_and_Blocker_Register_v2.4.md` is the authoritative decision/external-input/verification/gap register.
- `Planning/Planning_Closure_Decisions_v2.4.docx` describes the five proposed P0 closure baselines and residual blockers.
- `Planning/Implementation_Control_v2.4.xlsx` tracks backlog, decision states and review approvals.
- `Planning/Requirements_Traceability.csv` maps requirements to tests/evidence/owners. `Planning/Test_ID_Catalog_v2.4.csv` is the authoritative test identifier index.
- `Contracts/openapi.draft.yaml` is the proposed 17-operation Moallem REST contract.
- `Contracts/tool_registry.draft.json` defines per-tool JSON Schemas and policy metadata; tools remain `executable=false`.
- `Contracts/agent_runtime_limits.v2.4.json` records provisional guardrails; cost is reserved atomically and missing financial caps block AI task start. Composite Moodle publish is a durable async command with 30 outer tool calls and a separate 256 external-step envelope.
- `Validation/` contains document consistency output, the Moodle staging checklist, and SSRF/network-egress policy for public and private-campus Moodle sites.

## v2.4 decision outcomes
| Gate | Proposed baseline | State |
|---|---|---|
| P0-H Membership | `X-Active-Membership-ID` required on tenant-scoped requests except `GET /me`; server verifies membership ownership and ACTIVE status. | READY_FOR_APPROVAL |
| P0-I Moodle connection | Legacy Moodle External Web Service token linked to an authorized Moodle user and custom service; vault-only storage; local disconnect; remote token revoke remains Moodle-side action unless verified plugin support exists. | READY_FOR_APPROVAL |
| P0-J API contract | Typed transport DTOs, error catalogue, sequence-based event cursors, and connection lifecycle endpoints. Question payload union remains DEC-033. | READY_FOR_APPROVAL_WITH_DOMAIN_RESIDUAL |
| P0-K Tool contract | Versioned input/output JSON Schemas and authorization/runtime/audit policy metadata for each tool. Registry remains non-executable pending CI/policy enforcement and site mappings. | READY_FOR_APPROVAL |
| P0-L Reliability | PostgreSQL idempotency/outbox/inbox/tool ledger, stable per-step identities, cancel intent/reconciliation, ordered events. | READY_FOR_APPROVAL |

## Moodle credential distinction
The MVP uses legacy External Web Services functions and therefore uses a token for the configured External Service. Moodle 5.3 Personal Access Tokens belong to the newer REST API and are not treated as interchangeable with External Web Service tokens. The site-specific API Documentation, roles, capabilities and enabled functions must still be checked on staging.

## Provisional runtime limits
The proposed MVP guardrails are 900 seconds per task, 24 agent steps, 30 tool calls, 2 parallel tools (1 external write per connection), 24,000 total tokens, at most 2 read/internal retries, 0 automatic write retries after dispatch, and a separate 256 external-step envelope per composite Moodle publish (30 outer tool calls are counted separately). Financial ceilings are required configuration and deliberately have no invented default; PostgreSQL reserves task and tenant-period budgets atomically before AI task start, which is blocked when either cap is missing. These values require Product/Ops/FinOps approval and staging calibration.

## What remains open or blocked
- `ADR-017`: auth issuer/session/refresh/MFA.
- `DEC-026/027/032`: Moodle Site sharing, full permission matrix and RLS/isolation strategy.
- `DEC-030`: concrete broker/lease/DLQ configuration.
- `DEC-033/034`: question type set, educational scope, golden dataset and acceptance thresholds.
- `ADR-018/020`, `DEC-028/029`: AI provider/model/region, hosting, Secret Manager/KMS, retention/deletion, RPO/RTO/SLO.
- `EXT-MDL-*` and `VER-MDL-*`: target Moodle staging, live Web Services functions, teacher account/capabilities and Local Plugin deployment authority.
- A write with unknown outcome is manual reconciliation unless a trusted Moodle-side operation-key lookup exists.

## What v2.4 does not claim
It does not claim backend/Flutter implementation, approved migrations, site-specific Moodle write support, successful tests, a selected AI provider/region, an approved security/legal policy, measured performance/cost, or tested disaster recovery. `READY_FOR_APPROVAL` is not `CLOSED`.
