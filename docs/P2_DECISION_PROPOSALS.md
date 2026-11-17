# Open Decision Options and Recommendations

**Status: MIXED — SEE APPROVAL RECORDS BELOW.** This document summarizes decisions that remain
open after the Project Owner approved the v2.4 planning baseline and selected Auth0, PostgreSQL,
and AES-256-GCM on 2026-11-16. Recommendations below do not authorize vendor selection, account
creation, production configuration, or closing any ADR/DEC item unless explicitly approved below.

## Approved selections and implementation boundary

- **Auth0:** selected as identity provider. Issuer/audience, account linking, session lifecycle,
  refresh, revocation, MFA, and production configuration remain open.
- **PostgreSQL:** selected for persistence; PostgreSQL `SKIP LOCKED` queueing is approved for the
  MVP. Production schema/isolation review, hosting, backup/restore, and capacity validation remain
  open.
- **AES-256-GCM:** selected for application-level encryption. The current environment key is
  development-only; production KMS/Secret Manager and rotation are not configured.
- **DEC-030 queue for MVP:** PostgreSQL using `FOR UPDATE SKIP LOCKED` was approved by the Project
  Owner for the MVP. This does not establish production capacity or close operational decisions
  about database hosting, tuning, monitoring, recovery, or workload-based broker migration.
- **Authorization:** `DenyAllPolicy` remains the runtime default until the permission matrix is
  approved. Do not enable the proposed teacher grants by inference.

## Decision options

| Decision / owner | Options and trade-offs | Impact | Engineering recommendation (proposal only) | Requires approval from |
|---|---|---|---|---|
| **AI provider and model** — ADR-018; Product, Privacy, Education, FinOps | Managed API: quickest integration and elastic capacity, but sends data to a provider and has per-token cost/region constraints. Self-hosted models: greater data/control options, but GPU, operations, latency, and quality evaluation costs. Multi-provider abstraction: portability, with added testing and fallback complexity. | Privacy/data residency, Arabic quality, latency, availability, cost, vendor lock-in. | Evaluate at least two managed providers against a synthetic Arabic education benchmark and privacy terms before selecting; keep a provider interface, but do not build provider calls or send learner data before approval. | Product + Privacy + Education + FinOps |
| **Queue and worker delivery** — DEC-030; Backend, Ops | **PostgreSQL (approved for MVP):** `FOR UPDATE SKIP LOCKED` reuses the transactional outbox and avoids dual writes/extra service; polling and worker load compete with application queries. **Redis queue:** potentially lower latency/high throughput and low incremental cost if already hosted; durability, replication, retention, and crash recovery depend on the selected library and configuration. **RabbitMQ:** durable/quorum queues, publisher confirms, manual acknowledgements, and dead-letter exchanges provide mature routing/recovery, but add broker operations or managed-service cost. | PostgreSQL is simplest/lowest incremental cost for MVP but has unmeasured contention and database-bound throughput. Redis/RabbitMQ increase service and operational complexity/cost but can isolate queue load and scale independently. Recovery depends on durable configuration, idempotent handlers, monitoring, and tested restore/replay procedures for every option. Teacher count alone does not establish capacity. | **Approved:** PostgreSQL outbox queue using `FOR UPDATE SKIP LOCKED` for MVP; implementation includes leases, fencing, retries, and dead-lettering. **Still required:** benchmark enqueue rate, task age, DB contention and recovery under failure before production capacity claims. Reconsider RabbitMQ if measured throughput/isolation or routing needs justify it; consider Redis only with explicit durability/failover/retention evidence. | Project Owner approved MVP selection; Backend + Ops own operational validation |
| **Teacher and admin permissions** — DEC-027; Product, Security | Role-based grants: simple, but coarse. Resource-level grants/capabilities: precise, but more policy state and Moodle checks. Hybrid: application role plus resource ownership/capability checks. | IDOR risk, teacher workflow, admin access, auditability. | Define an explicit role × action × resource matrix; default deny; scope task actions to creator membership; require both application permission and Moodle capability evidence for Moodle operations. | Product + Security |
| **Tenant isolation** — DEC-032; Backend, Security | Application predicates + composite foreign keys: straightforward and already partly used, but depends on every query being correct. PostgreSQL RLS: database defense-in-depth, but session context and pooled-connection reset must be proven. Combined model: strongest layers, with more migration and operational complexity. | Cross-tenant exposure risk, query correctness, connection pooling, operations. | Retain application predicates and composite tenant keys; evaluate RLS as an additional layer with threat analysis and tests covering transaction-local context, pool reuse, API and worker access. Do not claim RLS is active. | Security + Backend + Architecture |
| **Hosting and region** — ADR-020; Product, Infrastructure | Managed platform: faster delivery and managed database/backups, but provider and region limits. Self-managed containers/Kubernetes: control, but higher operational and security burden. Private connector: needed for campus-only Moodle networks, but requires deployment/support ownership. | Data residency, egress, Moodle reachability, availability, backup, cost, staffing. | Compare candidates against Moodle network reachability, residency, restore requirements and budget; prefer managed PostgreSQL and queue if requirements permit. No provider/region is selected. | Product + Infrastructure + Security |
| **Production secret custody** — DEC-029; Security, Platform | Cloud KMS envelope encryption: rotation/audit integration, with service dependency and cost. Managed Secret Manager: convenient secret lifecycle, but per-tenant Moodle tokens still need encrypted application storage. HSM: strong custody, highest complexity/cost. Environment key: simplest, but weak rotation/access separation; development only here. | Key compromise blast radius, rotation, backups, audit, availability, cost. | Use a managed KMS/Secret Manager for production key custody and envelope-encrypt Moodle credentials in PostgreSQL; specify key version, rotation, backup and recovery. Keep production vault fail-closed until approved. | Security + Platform |
| **Data retention, deletion and privacy** — DEC-028; Product, Privacy, Legal | Fixed retention by data class: easy to implement but may not fit legal duties. User/tenant-configurable retention: flexible but complex and error-prone. Minimal retention with explicit exceptions: lowers exposure, but limits history and analytics. | Compliance, privacy risk, database/storage cost, backup deletion semantics, audit. | Inventory prompts, Moodle content, generated drafts, events, logs, embeddings and backups; set the shortest justified retention per class and prove deletion propagation. Do not invent durations. | Product + Privacy + Legal |
| **Usage limits and AI cost budgets** — ADR-023/DEC-043; Product, FinOps | Per-task limits: protects against runaway work but not aggregate tenant spend. Per-tenant period budgets: aggregate control but needs atomic reservations and reconciliation. Both: stronger protection with more accounting logic. | Spend, fairness, capacity, abuse resistance, task failure behavior. | Require configured per-task and tenant-period budgets before any AI call; fail closed when missing or exhausted. Set numeric limits only after provider pricing and pilot measurements. | Product + FinOps + Security |
| **Moodle connection sharing and validation** — DEC-026/037; Product, Moodle Admin | One Moodle connection per tenant: clearer ownership, less sharing risk. Shared site records with explicit grants: less duplication but more revocation and authorization complexity. | Credential exposure, ownership, tenant boundaries, support burden. | Default to tenant-owned connections without shared credentials for MVP; revisit sharing only with explicit grants and cross-tenant tests. Validate all assumptions against the Moodle staging site. | Product + Security + Moodle Admin |

## External blockers and current fail-closed behavior

- Moodle Admin must provide HTTPS staging URL, Moodle version/build, enabled Web Service functions,
  teacher test identity, and synthetic course before live compatibility can be tested.
- Auth0 production issuer/audience and account/session policies must be configured; unknown subjects
  are not auto-provisioned.
- The Moodle transport is opt-in. The API returns 503 when `MoodleReadService` is not explicitly
  injected. No Moodle write support exists.
- P4 now includes transactional idempotent task creation, a PostgreSQL `SKIP LOCKED` outbox worker,
  leases/fencing, retries, and terminal dead-letter handling. No production task handlers or inbox
  consumer are registered; bounded idempotency cleanup is integrated but its deployment tuning
  and operations need validation. Administrative dead-letter recovery, production operations, and
  capacity evidence remain outstanding.

## Approval record

Record a decision only after the named owners approve it, including date, rationale, rejected
alternatives, security/privacy impact, budget/region impact, and migration/reversal plan. The
DEC-030 owner approval is recorded in this repository; its approval date is not captured here.
Update the authoritative v2.4 `Unified_Decision_and_Blocker_Register_v2.4.md`; do not mark `OPEN`
or `READY_FOR_APPROVAL` items `CLOSED` solely because this recommendation is written.
