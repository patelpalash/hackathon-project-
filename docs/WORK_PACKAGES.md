# Version-2 work packages

Work one gate at a time; these are deliverables, not guaranteed hour estimates. The full scope is larger than the original two-day estimate. Preserve the map and the automatic-event/manager-decision loop; defer decorative polish before correctness. Exact ownership is in MERGE_GUIDE.md.

## G0 — Shared base and contracts

Both people read START_HERE, audit resolutions and contracts. Commit this pack once and branch from that same commit. Claude owns frontend/**. Codex owns backend core, data, root integration and scripts. Antigravity owns backend/app/providers/**, backend/tests/providers/**, backend/tests/regression/** and qa/**. Use separate checkouts and lock files owned by the respective package maintainer.

Codex establishes Python settings, SQLite, tested dependencies and the imported provider protocol. Claude creates React/TypeScript/Vite and its tested npm lock. Antigravity implements adapter scaffolds against the shared protocol; dependencies go through Codex. All run the spec validator. Don't build three competing implementations of the API.

## G1 — First complete search

Codex: health/state/network and a real direct-path search; init command that preserves existing databases. Claude: search form, real typed API client, route cards and timeline. Antigravity: provider mock responses, timeout/no-key tests and audit regression outlines. Connect the browser to Python now, with /api proxy on Vite 5173 to backend 8000.

Gate: a real browser request displays the expected direct itinerary; stopping Python shows an error, not a hidden fixture fallback. Explicit development fixture mode is allowed while independent frontend work proceeds but defaults off.

## G2 — Complete routing and geographic map

Codex: all eligible paths/occurrences, timezones/cut-offs/calendars, OriginProgress, inactive nodes, exact timelines and typed source summary/capacity example. Claude: required MapLibre/OpenFreeMap map, route selection synchronization, incident overlay, attribution and offline/WebGL fallback; React Flow remains the schedule editor. Antigravity: provider adapters and tests against ProviderBatch, not DB writes.

Gate: all eight numerical scenarios match; map/cards/timeline agree; old/source coordinate assumptions are visible; production frontend worker loads. Road-only and no-route cases work. Supplied data imports reconcile.

## G3 — Events and human review

Codex: accepted/pending/versioned events, recomputation, plans_revision, selected projections, saved plans, immutable review evidence, idempotency and conflict handling. Claude: event/report forms, presets, saved-plan review, accept/keep/defer, history and independent counter refresh. Antigravity: F1-F6 regression tests and overlapping-event tests.

Gate: save direct -> traffic -> Munich recommended -> accept -> Munich handling delay -> Strasbourg recommended -> accept. Two sessions see decisions. Advancing clock between ready time and departure preserves valid progress. Another event/edit cannot alter an old approval's recorded evidence.

## G4 — Live adapters integrated

Antigravity: finish Open-Meteo, TomTom and optional configured bulletin adapter, unit conversion, scoped outputs and failure/deduplication tests. Codex: polling/cache/observation persistence, live-mode isolation, source validation, request budgets and API exposure. Claude: live/demo status, source times, unavailable/stale states and observation details; traffic geometry displayed only with provider provenance.

Gate: no credentials -> truthful not_configured; demo -> no live ingestion; live -> configured real fetch smoke test, or an explicitly reported missing configuration. Map still works without TomTom. Weather policy defaults advisory_only. Do not claim real feed verification from mocked tests.

## G5 — Merge, test and demo

Person B/Codex integrates branches after each preceding gate. Final merge uses MERGE_GUIDE order. Run Python engine/API/provider/regression tests, frontend typecheck/build and actual browser walkthrough. Run packaged frontend through Python, then restart and verify persistence. Test tile loss/backend loss/stale approval/reset separately. Run from a path with spaces.

Codex writes root README and scripts/start-demo.ps1 using the backend init/serve interface; Claude supplies the frontend build. Keep bootstrap/install separate from demo start. Example backend CLI to implement: python -m app.cli init --source-dir ../data/raw; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000. Default database resolves from repo root and mode. Init does not silently reset.

The final demo opens a real map, searches routes, injects a clearly simulated incident, shows automatic ETA/reroute recommendations, records a manager reason and shows unchanged historical evidence after subsequent edits. If live traffic is configured, show its status and source time separately from the repeatable simulation.

## If time runs short

Prioritize G1-G3 and the geographic map with fallback, then integrate the already developed provider adapters. Keep missing live configuration visible rather than inventing a feed. Reduce custom schedule-editing breadth, printing and decorative charts. Do not remove stale-approval protections or claim unfinished G4/G5 checks passed. Each tool reports files changed, exact checks run/outcome, unresolved issue and next gate.
