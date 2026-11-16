.PHONY: setup lint typecheck test build audit check api worker
BACKEND = cd backend &&

setup:        ## install backend deps from the lockfile
	$(BACKEND) uv sync --locked
lint:
	$(BACKEND) uv run ruff check . && uv run ruff format --check .
typecheck:
	$(BACKEND) uv run mypy
test:
	$(BACKEND) uv run pytest
build:
	$(BACKEND) uv build
audit:
	$(BACKEND) uv run pip-audit
check: lint typecheck test build audit
api:          ## local API (needs MOALLEM_* env, see backend/.env.example)
	$(BACKEND) uv run uvicorn --factory moallem.api.app:create_app --reload
worker:
	$(BACKEND) uv run python -m moallem.worker
