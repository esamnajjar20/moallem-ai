# ADR-015: Flutter state management — PROVISIONAL (not closed)

**Status:** PROPOSED. Register status stays `OPEN` until the Mobile Lead signs off.
**Provisional choice:** Riverpod (`flutter_riverpod`).

## Why provisional
The register closes ADR-015 only after a short prototype, testability/maintainability review and
team agreement. P1 only needed *a* choice to lay a skeleton. This file records the choice so
nothing downstream assumes it is final.

## Basis (author's reasoning, not measured evidence)
- Compile-safe providers and straightforward test overrides (see `mobile/test/widget_test.dart`).
- Config and API client wiring in P1 needs dependency injection more than complex event flows.

## Cost of reversing
Low today: P1 uses state management in one place (`lib/core/providers.dart`) and one `ProviderScope`.
The cost grows with every screen added in P8.

## To close
Mobile Lead runs the prototype (task-progress screen with polling), compares against Bloc on
testability and team familiarity, signs this ADR, then updates register ADR-015 and backlog P0-06.
