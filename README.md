# Moallem AI

Planning baseline: Moallem AI Engineering Documentation v2.4. Status of the current phase:
[`docs/PHASE1_STATUS.md`](docs/PHASE1_STATUS.md).

```
backend/    FastAPI API + Worker skeleton (Python 3.12)
mobile/     Flutter skeleton (Riverpod, RTL Arabic shell)
contracts/  openapi.draft.yaml (draft v0.4.0, not frozen)
docs/       ADRs (provisional) and phase status
```

Backend quick start (after `uv lock` has produced `uv.lock`):

```bash
cd backend && cp .env.example .env
make setup check        # lint, typecheck, tests, build, audit
make api                # http://127.0.0.1:8000/healthz  /readyz
```

Synthetic data only. No real student data in development (Deployment Spec §2).
