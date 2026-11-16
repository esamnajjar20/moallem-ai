# ADR-016: Python type checker — PROVISIONAL (not closed)

**Status:** PROPOSED. Register status stays `OPEN` until the Backend Lead signs off.
**Provisional choice:** mypy in `strict` mode with the Pydantic plugin (`backend/pyproject.toml`).

## Why provisional
The register requires a CI trial on a representative project and a documented strictness policy.
That trial has not been run: the skeleton was generated without network access and mypy has
**not been executed** against it yet.

## Basis (author's reasoning, not measured evidence)
- Mature Pydantic plugin; one config block in `pyproject.toml`; runs in CI without extra services.
- Pyright is the main alternative (faster, stricter inference); switching means replacing one CI step
  and one config block.

## Cost of reversing
Low now (few modules). Expect some annotation churn on switching.

## To close
Run `uv run mypy` and (optionally) pyright on the real codebase, record error counts and runtime,
sign this ADR, update register ADR-016 and backlog P0-07.
