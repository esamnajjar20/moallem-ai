# ADR-016: Python type checker — PROVISIONAL (not closed)

**Status:** PROPOSED. Register status stays `OPEN` until the Backend Lead signs off.  
**Provisional choice:** mypy in `strict` mode with the Pydantic plugin (`backend/pyproject.toml`).

## Evidence recorded

`docs/PHASE1_STATUS.md` records a successful historical CI/local trial: `mypy --strict` reported
no issues in 24 source files on 2026-11-16. The earlier version of this ADR incorrectly stated
that mypy had not been executed; that statement is withdrawn.

The current execution environment does not have mypy installed and has no network access, so this
update does not claim a fresh independent run. The pinned GitHub Actions backend job executes
`uv run --locked mypy` on Python 3.12.16 on every PR and push to `main`.

## Why provisional

The register requires a representative CI trial and a documented strictness policy, followed by
Backend Lead agreement. A recorded successful tool run is technical evidence, not the owner's
approval to close the ADR.

## Basis

- Pydantic's mypy plugin is already configured.
- `strict = true` and `warn_unreachable = true` are enabled.
- Pyright remains the alternative; switching would replace the CI step and type-checker config.

## Cost of reversing

Low while the module count is small; annotation and plugin/config changes will grow with the codebase.

## To close

Backend Lead reviews the CI result for the pinned Python version, compares the policy with project
needs, signs this ADR, and updates the decision register and P0-07 backlog row.
