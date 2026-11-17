# ADR-017: Authentication and session lifecycle — MVP decision

**Implementation status:** IMPLEMENTED IN BACKEND; EXTERNAL AUTH0 CONFIGURATION/DEVICE VERIFICATION REMAINS OPEN.
**Provider:** Auth0 (selected by the Project Owner on 2026-11-16).
**Scope:** Moallem API authentication and the native Flutter client session boundary. Authorization policy DEC-027 remains separate and is not closed by this ADR.

## Decision

1. The native Flutter application is an OAuth 2.0 / OpenID Connect public client and uses Authorization Code Flow with PKCE through the Auth0 native SDK / system browser. It contains only the Auth0 application client ID and configured domain; it never contains a client secret.
2. Auth0 owns credential entry, sign-up policy, MFA challenge, authorization code exchange, refresh-token issuance/rotation, and the provider SSO session. The Moallem API does **not** implement password login, token issuance, refresh-token exchange, or provider logout endpoints.
3. The Flutter client requests an **API access token** for the exact Moallem API audience. It stores credentials only through the SDK's OS-backed secure credential store (Android Keystore-backed storage / iOS Keychain), serializes refresh operations through the SDK, and uses refresh-token rotation with reuse detection. Refresh tokens are never sent to the Moallem API.
4. Access tokens are JWTs signed with RS256. The API accepts only `Authorization: Bearer <access_token>`, verifies signature against HTTPS JWKS derived solely from the configured issuer, exact `iss`, exact configured `aud`, required `sub`, `exp`, `iat`, optional `nbf`, and a maximum lifetime of 900 seconds. Clock tolerance is 30 seconds. ID tokens, HS256, unsigned tokens, unknown subjects and unrecognized keys are rejected.
5. `auth_issuer` is the exact HTTPS Auth0 issuer including its trailing slash. `auth_audience` is the exact API Identifier. These are required in staging/production. Auth0 JWKS must be reachable and contain a valid signing key for readiness to pass.
6. `(iss, sub)` maps to a pre-provisioned global Moallem user. API login never auto-provisions users and never trusts roles, user IDs, tenant IDs, or Moodle IDs from token custom claims or client headers. Identity provisioning is a trusted operator/database action using `backend/scripts/manage_auth_identity.py`.
7. Account states are `ACTIVE`, `SUSPENDED`, and `REVOKED`. Only ACTIVE users map to a principal. Suspension/revocation is checked against PostgreSQL for every authenticated API request and therefore immediately blocks new API requests, even while an already-issued JWT has not expired. Membership status and membership ownership are rechecked for every tenant-scoped request.
8. Logout is a client/provider operation: the native SDK clears local credentials and the Auth0 browser SSO session; the client must use the provider's refresh-token revocation capability when revocation of a compromised device/grant is required. The API never accepts a refresh token. A copied JWT access token cannot be remotely revoked by Auth0 and can remain cryptographically valid until `exp`; keep its lifetime at or below 15 minutes and set the user to SUSPENDED/REVOKED to block API use immediately.
9. MFA is required by Auth0 for the MVP login policy. This intentionally applies to all Moallem accounts until DEC-027 formally identifies and classifies privileged roles; a later policy may narrow MFA enforcement to administrative/support roles. MFA configuration is an Auth0 tenant setting and must be verified in staging before pilot.
10. Development-only `X-Dev-User-ID` authentication remains available only in `development` and `test`. It cannot be selected in staging or production.

## API contract

- `GET /api/v1/me` is the authenticated principal/session bootstrap endpoint. It returns the server-mapped `user_id` and memberships; it requires no active-membership header. It is `Cache-Control: no-store`.
- All tenant-scoped endpoints still require `X-Active-Membership-ID`; it is a selector only. The API resolves its owner, tenant, roles and ACTIVE status server-side for each request.
- Authentication failures are uniform `401 AUTHENTICATION_REQUIRED`, include `WWW-Authenticate: Bearer`, and are not cacheable.
- Login, refresh and logout are deliberately absent from the Moallem API. This avoids handling passwords or refresh-token secrets in this service and keeps the OAuth public-client model correct.

## Database change

Alembic revision `f4a2d9c61b80` adds `users.auth_status` with a database check constraint. Existing users default to ACTIVE. Apply it with `uv run alembic upgrade head` before deploying this code.

## Required Auth0 tenant setup (external gate)

- Create a Native Application and an API; configure the API signing algorithm as RS256 and use its API Identifier as `MOALLEM_AUTH_AUDIENCE`.
- Set the exact tenant/custom-domain issuer including trailing slash as `MOALLEM_AUTH_ISSUER`.
- Configure the API access-token lifetime to 900 seconds (or less).
- Enable Refresh Token grant for the native application, rotation, reuse detection, and an explicit absolute/inactivity lifetime appropriate to the pilot.
- Enforce MFA for the MVP user population and configure approved callback/logout URLs for the mobile application.
- Do not configure a client secret in Flutter. Do not enable a password grant or Resource Owner Password Credentials flow.
- Verify live login, token renewal, logout, refresh-token revocation, key rotation, MFA challenge, and disabled-account behavior using a dedicated Auth0 staging tenant.

## Consequences and limitations

- No Moallem password table or API refresh-token store is required.
- The API has a single clear trust boundary: Auth0 verifies the user; PostgreSQL resolves an active Moallem identity and memberships; application authorization decides each action.
- Auth0 tenant provisioning, the mobile callback configuration, and real-device PKCE/secure-storage behavior cannot be proven from this Backend-only change.
- This ADR closes the backend authentication implementation design. It does not close DEC-027 permission matrix, hosting/KMS decisions, or live provider verification.

## Verification evidence

The automated suite covers RS256-only behavior, issuer/audience/expiration/lifetime checks, future-issued tokens, unknown subjects, bearer errors, no-store behavior, account suspension/revocation mapping, and JWKS readiness/cache behavior. Live Auth0 staging and Android/iOS tests remain external acceptance checks.
