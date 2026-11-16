.PHONY: setup lint typecheck test build audit check api worker mobile-bootstrap mobile-check mobile-build-android check-all
BACKEND = cd backend &&
MOBILE = cd mobile &&

setup:        ## install backend deps from the locked environment
	$(BACKEND) uv sync --locked
lint:
	$(BACKEND) uv run --locked ruff check . && uv run --locked ruff format --check .
typecheck:
	$(BACKEND) uv run --locked mypy
test:
	$(BACKEND) uv run --locked pytest
build:
	$(BACKEND) uv build
audit:
	$(BACKEND) uv run --locked pip-audit
check: lint typecheck test build audit
api:          ## local API (needs MOALLEM_* env, see backend/.env.example)
	$(BACKEND) uv run uvicorn --factory moallem.api.app:create_app --reload
worker:
	$(BACKEND) uv run python -m moallem.worker
mobile-bootstrap: ## create Flutter platform projects and lock dependencies (one time)
	./scripts/bootstrap_mobile.sh
mobile-check: ## enforce the Flutter lock, formatting, static analysis and tests
	./scripts/check_mobile_prerequisites.sh
	$(MOBILE) flutter pub get --enforce-lockfile && dart format --output=none --set-exit-if-changed lib test && flutter analyze --fatal-infos && flutter test
mobile-build-android: ## build a debug APK (Android SDK required)
	$(MOBILE) flutter build apk --debug
check-all: check mobile-check mobile-build-android
