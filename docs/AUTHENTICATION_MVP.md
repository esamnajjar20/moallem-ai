# Authentication — Backend MVP and Flutter integration contract

## Responsibilities

| Concern | Owner | Contract |
|---|---|---|
| Sign in / sign up | Auth0 + Flutter native SDK | OIDC Authorization Code + PKCE in system browser |
| Passwords / MFA | Auth0 | Never sent to Moallem API |
| Access token | Auth0 | RS256 JWT, Moallem API audience, lifetime <= 900 seconds |
| Refresh / rotation | Auth0 SDK | Rotating refresh token with reuse detection; SDK secure storage only |
| API authentication | FastAPI | Verify bearer access token and map `(iss, sub)` to an ACTIVE user |
| Account suspension | PostgreSQL | `users.auth_status`; immediate API denial |
| Active organization | FastAPI | `X-Active-Membership-ID` selector; ownership/status resolved server-side |
| Logout | Auth0 SDK + Flutter | Clear local credentials and Auth0 SSO session; revoke refresh grant on compromise |

## Runtime configuration

Set these values in the API secret/config store. Never commit a real issuer or credentials:

```dotenv
MOALLEM_ENV=staging
MOALLEM_AUTH_ISSUER=https://YOUR_TENANT.auth0.com/
MOALLEM_AUTH_AUDIENCE=https://api.your-domain.example
MOALLEM_AUTH_MAX_TOKEN_LIFETIME_SECONDS=900
MOALLEM_DATABASE_URL=postgresql://...
```

`MOALLEM_AUTH_ISSUER` must be the exact HTTPS issuer ending in `/`. `MOALLEM_AUTH_AUDIENCE` must exactly match the Auth0 API Identifier. The backend fails startup if Auth0 is configured without persistent PostgreSQL mapping outside tests. Staging/production configuration already requires PostgreSQL and the other mandatory backend configuration.

## Provision a teacher identity

User creation is not public self-provisioning. First create/invite the user through the approved Auth0 tenant flow and create or identify the tenant. Then use the trusted operator command from `backend/`:

```bash
uv run python scripts/manage_auth_identity.py provision \
  --issuer 'https://YOUR_TENANT.auth0.com/' \
  --subject 'auth0|AUTH0_SUBJECT' \
  --user-id '11111111-1111-4111-8111-111111111111' \
  --tenant-id '22222222-2222-4222-8222-222222222222' \
  --tenant-name 'Pilot School' \
  --membership-id '33333333-3333-4333-8333-333333333333' \
  --role TEACHER
```

If the tenant already exists, omit `--tenant-name`. The initial provisioning command only grants `TEACHER`; broader roles remain blocked until the product/security permission matrix (DEC-027) is approved. The Auth0 subject is never printed. To suspend or revoke a mapped user:

```bash
uv run python scripts/manage_auth_identity.py set-status \
  --user-id '11111111-1111-4111-8111-111111111111' --status SUSPENDED
```

Use `ACTIVE` to reactivate after an explicit operator decision. `REVOKED` represents a permanently disabled mapping; do not reuse that user mapping for a new identity.

## Flutter request behavior (implementation guide)

1. Use the Auth0 native SDK's Authorization Code + PKCE login method; request the Moallem API audience and `openid profile email offline_access` only where each scope is needed.
2. Retrieve an API access token through the SDK credential manager. Let the SDK serialize refresh operations and persist rotating credentials using OS-backed secure storage.
3. Send only `Authorization: Bearer <access_token>` to Moallem. Never send an ID token, refresh token, Auth0 client secret, user ID, tenant ID, or role as proof of identity.
4. Bootstrap with `GET /api/v1/me`; choose a returned ACTIVE membership and send its `membership_id` in `X-Active-Membership-ID` for tenant-scoped requests.
5. On `401 AUTHENTICATION_REQUIRED`, ask the SDK to renew credentials once; if it fails, clear local application state and require interactive login. Do not loop refresh attempts.
6. On logout, clear local application caches/drafts according to the separate offline-data policy, call Auth0 SDK logout to clear local credentials and the Auth0 SSO session, and ensure the SDK/provider revocation flow is used for compromised grants. Then clear the active membership and all user-scoped state.

## Database migration and verification

```bash
cd backend
uv run alembic upgrade head
uv run pytest -q tests/test_bearer_api.py tests/test_config.py tests/test_jwks.py \
  tests/domain/test_rs256.py tests/test_auth_identity_persistence.py
```

The added migration is `f4a2d9c61b80_auth_user_lifecycle.py`. Run the complete suite with the project-pinned Python 3.12.16 and a disposable PostgreSQL test database before merge/deploy.

## Operational notes

- `GET /api/v1/me` and authentication failures are `no-store`.
- `/readyz` checks that Auth0 JWKS can be loaded when Auth0 auth is configured.
- JWKS is fetched only from the configured issuer, capped at 256 KiB, cached for one hour, and refreshed for unknown `kid` no more than once per minute.
- The API does not issue or accept refresh tokens. JWT access-token revocation is not immediate; suspend/revoke the Moallem user to deny API requests immediately, and revoke the Auth0 refresh grant when the device/grant is compromised.
- `X-Dev-User-ID` is prohibited outside `development` and `test`.

## External acceptance checklist

- [ ] Auth0 Native Application and API created; callback/logout URLs match actual mobile bundle identifiers.
- [ ] API signing algorithm RS256; exact issuer and audience configured.
- [ ] Access-token lifetime <= 900 seconds.
- [ ] Refresh rotation, reuse detection, and refresh-token grant lifetime configured.
- [ ] MFA is required in the pilot tenant.
- [ ] Android physical device: PKCE login, encrypted credential persistence, app restart, refresh, and logout.
- [ ] iOS physical device: PKCE login, Keychain persistence, app restart, refresh, and logout.
- [ ] Refresh-token revocation tested; copied access token behavior documented until expiry.
- [ ] Unknown Auth0 subject rejected; SUSPENDED and REVOKED users rejected immediately.
- [ ] JWKS key rotation and issuer unavailability behavior tested.
