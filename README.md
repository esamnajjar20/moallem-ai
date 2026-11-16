# Moallem AI

Planning baseline: Moallem AI Engineering Documentation v2.4.

Status:
- Backend P1 gate: **closed locally** (2026-11-16) — see [`docs/PHASE1_STATUS.md`](docs/PHASE1_STATUS.md)
- Post-P1 / domain core: [`docs/PHASE2_STATUS.md`](docs/PHASE2_STATUS.md)

```
backend/    FastAPI API + Worker skeleton (Python 3.12) + domain core
mobile/     Flutter skeleton (Riverpod, RTL Arabic shell)
contracts/  openapi.draft.yaml (draft v0.4.0, not frozen)
docs/       ADRs (provisional) and phase status
```

Backend quick start:

```bash
cd backend && cp .env.example .env
uv sync --locked
make check              # lint, typecheck, tests, build, audit
make api                # http://127.0.0.1:8000/healthz  /readyz
```

Verified locally (2026-11-16):
- `uv.lock` present
- ruff format/check clean
- mypy strict: 24 files OK
- pytest: **82 passed**

Synthetic data only. No real student data in development (Deployment Spec §2).
