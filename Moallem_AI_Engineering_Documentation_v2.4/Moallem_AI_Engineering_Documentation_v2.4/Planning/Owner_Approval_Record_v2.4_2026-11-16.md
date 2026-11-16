# Owner Approval Record — Engineering Documentation v2.4

- **Approval date:** 2026-11-16
- **Approver:** Esam Najjar, Project Owner
**Approval basis:** Written approval communicated in the project session.

## Approved

1. **Planning baseline:** Engineering Documentation v2.4 is approved for planning and implementation
   tracking. This approves the baseline document set; it does not automatically close every ADR,
   decision, external dependency, or verification gate described in it.
2. **Identity provider selection:** Auth0 is selected as the identity provider for the project.
   Issuer, API audience, token lifetime, subject/account-linking policy, sessions, refresh,
   revocation, MFA, and production configuration remain to be specified or verified.
3. **Database selection:** PostgreSQL is selected for P4 durable task, event, idempotency, and
   outbox/inbox storage. This does not approve a final production schema, primary-key strategy,
   tenant-isolation/RLS design, hosting region, queue broker, or retention policy.
4. **Application-level encryption:** AES-256-GCM is selected for application-level encryption of
   sensitive values. Development may receive a key through an environment variable. Production
   secret storage and key rotation remain blocked until a KMS or Secret Manager is approved.
5. **Implementation scope:** Begin P4 task persistence and contract-aligned task API routes, and
   replace hand-written RS256 verification with PyJWT and `cryptography`. Auth0 and encryption
   configuration must remain fail-closed when required environment values are absent.

## Configuration and safety boundaries

- Never commit real Auth0 values, database credentials, encryption keys, or HMAC keys.
- Do not use a generated, default, or test key outside tests. Missing encryption configuration
  disables secret encryption and any operation that requires it.
- Do not enable production secret storage using an environment key; production remains blocked
  pending KMS/Secret Manager approval.
- PostgreSQL task creation must require its configured database, idempotency HMAC key, and
  explicitly configured idempotency retention. There are no implicit defaults for these values.
- Auth0 selection does not authorize auto-provisioning unknown users or bypassing active
  membership and authorization checks.
- Moodle staging, live API compatibility, and Moodle write permissions remain unverified.

## Decisions that remain open

ADR-017 remains open for the Auth0 issuer/audience and the remaining session/security policy.
ADR-020 remains open for hosting, region, network egress, and deployment. DEC-029 remains open for
KMS/Secret Manager and storage lifecycle. DEC-030 remains open for broker and delivery semantics.
DEC-031/032 remain open for schema/key strategy and tenant isolation. DEC-033/034 remain open for
question types and educational acceptance. All `EXT-MDL-*` and `VER-MDL-*` items still require
Moodle-admin input or real staging evidence.

This record is a textual approval record, not a handwritten, cryptographic, or legal signature.
