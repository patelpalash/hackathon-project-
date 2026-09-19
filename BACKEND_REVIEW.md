# Backend quality review — 2026-09-19

**Rating: 7/10 for a hackathon prototype; not production ready.** The scheduled routing engine has useful deterministic fixtures and the original 28 tests passed. The provider side initially had several defects that made live operation unreliable. This review was performed against commit `4f2ca5d` and the improvements on `codex/backend-quality-review`.

## Corrected in this branch

- Open-Meteo now evaluates the whole modeled traversal window. A network failure or forecast outside its horizon reports stale data instead of a fabricated dry-weather observation. Weather penalties have positive validity and a future review deadline.
- TomTom now rejects missing or invalid `trafficDelayInSeconds` and reports HTTP failures without inventing a zero delay. Its event validity covers the intended occurrence. The API key is passed as a request parameter rather than interpolated into a hand-built URL.
- Provider ingestion rejects batches fetched for an older dataset or schedule, validates source/validity, persists provider status, deduplicates identical observations/effects, versions changed effects, and withdraws a cleared delay. Demo databases reject provider ingestion.
- Live initialization uses today's local service dates through 60 days ahead. A server worker advances the live evaluation clock independently of GET requests. Demo mode keeps its fixed fixture clock.
- Creating a plan now commits the plan and idempotency receipt. A manager decision and its receipt commit together. Demo reset clears dependent rows in foreign-key order. Public event mutations enforce basic effect/identity rules. The accidental `/api/api/integrations/refresh` route was removed.

## Evidence

- Before changes: `28 passed` (`.venv\Scripts\python.exe -m pytest backend/tests -q`).
- After changes: `33 passed`, including a regression that proves a traffic response changes a direct route ETA by 61 minutes, a subsequent response changes it to 2 minutes, a zero-delay response restores the baseline, and a stale batch is rejected. The API suite also resets a database containing a saved decision.
- `docs/tools/validate_spec.py` passes its 22-operation, 52-schema fixture validation. This validates specification artifacts, not every runtime API response.
- TomTom request parameter and delay semantics were checked against the [official Calculate Route reference](https://docs.tomtom.com/routing-api/documentation/tomtom-maps/v1/calculate-route). No credentialed live-provider smoke test was run.

## Remaining work before claiming a full live prototype

1. Provider polling is still initiated by `POST /api/integrations/refresh`; the planned 5/10/15-minute background polling schedule is not implemented. The clock worker runs, but it does not poll providers.
2. Weather currently samples the origin endpoint only. It does not sample both endpoints or a full corridor, so the map should present it as limited coverage.
3. Refresh ingestion and saved-plan recomputation use separate commits. A failure between them can temporarily leave event state newer than a plan projection. Use one transaction or an explicit recovery queue before operational use.
4. Provider request limits are enforced per adapter but requests are sequential; repeated timeouts may make a manual refresh slow. Add bounded concurrency and retry/backoff before a live demo with many lanes.
5. Run real Open-Meteo and TomTom smoke tests with permitted credentials and inspect attribution, units, and forecast horizon. Current provider tests use synthetic HTTP responses.

For the hackathon, the reliable demonstration path remains demo mode with documented synthetic schedules and manager decisions. Live mode should be labeled as using sample schedules and should show explicit provider status.
