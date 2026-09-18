# Implementation specification, version 2.0.0

## 1. Fixed product scope

Working title: Transit Planner. Audience: dispatcher, customer-service planner and manager. Initial service is branch-to-branch: ready at the origin facility through arrival at the destination facility. Origin and intermediate handling are included; destination handling, pickup and consignee delivery are excluded and clearly labeled. This is a deliberate simplification of the broader brief. Do not call the result a door-to-door delivery promise. The PDF's 70-hour illustration is educational context, not our fixture's expected result.

Must ship: search, three feasible alternative paths when available, MapLibre geographic map with OpenFreeMap basemap and offline fallback, network schematic, segment timeline, editable lane schedule and node handling, automatic event-based recalculation, manager reports/decisions, decision history, CSV source summary, reset, one-command local launch. Use nine seeded nodes and ten lanes. All schedules, locations/coordinates and durations are demo assumptions. Supplied relation destinations remain source data; do not invent mappings from their unspecified origins to these lanes.

Not in version 2: live GPS, turn-by-turn navigation, production dispatch, production authentication, pricing, learned ETA models, probabilistic confidence, load forecasting, arbitrary graph editing, sea-service examples, full driver-hours/legal compliance or customer dashboards. Do not add a chatbot as a substitute for the controls.

## 2. Architecture

React/TypeScript + Vite + CSS modules + MapLibre GL JS (planner) + React Flow (schedule editor) -> same-origin /api -> FastAPI/Pydantic -> pure Python scheduling functions + SQLite. Use pandas for one-time CSV inspection/import; use datetime/zoneinfo and install tzdata for Windows. Frontend uses fetch with a small typed client; avoid adding a global-state library initially. Backend is the sole owner of calculations and validation. UI can format durations, but cannot synthesize ETAs, route feasibility or review decisions.

Development ports: frontend 5173, backend 8000 on 127.0.0.1. Vite proxies /api to http://127.0.0.1:8000. Packaged demo: backend serves frontend/dist and /api on 8000. API routes must win before SPA fallback; unknown /api paths must return JSON 404, not index.html. Use one backend worker because demo clock and recalculation are local; persist durable state in SQLite, not only memory.

Package versions: choose mutually compatible available stable versions at bootstrap, verify install/build and commit lock files. Do not upgrade mid-hackathon after the integration gate. Frontend owner commits package.json and package-lock.json; backend owner pins a tested Python dependency set. The deterministic demo requires no key. Live TomTom traffic requires a server-side key; Open-Meteo account/endpoint must suit the intended usage. See MAP_AND_LIVE_DATA.md. Missing credentials must be visible, never replaced by fake live results.

## 3. Repository and ownership

```
frontend/                 # A: React application, tests, npm dependencies
backend/app/api/          # B: endpoint handlers and wire models
backend/app/domain/       # B: nodes, lanes, events, itinerary types
backend/app/engine/       # B: pure functions for time, routing, events
backend/app/storage/      # B: sqlite repositories and transactions
backend/app/services/     # Codex: search/plans/worker/clock
backend/app/providers/    # Antigravity: provider fetch adapters
backend/tests/            # Codex: engine/API; Antigravity: providers/regression
data/raw/                 # B: copied original CSVs, excluded from public release by default
data/demo/                # B: runtime copy of reviewed fixture seed
data/runtime/             # B: SQLite database, ignored by git
scripts/                  # Codex: bootstrap/start/build/reset integration scripts
docs/                     # frozen specification, Codex integrates agreed changes
README.md                 # Codex: setup, commands, demo and limitations
```

Original user CSVs must remain unchanged. Use a configurable --data-dir path; never hard-code C:\Users\acer into runtime code. Both people should be able to launch from a folder with spaces. Keep logs concise and omit CSV customer details from routine logging. Commit source and seed fixtures; ignore virtual environments, node_modules, build output, SQLite files and scratch renders.

## 4. Canonical types and persistence

Wire shapes are in contracts/openapi.json. Operational schedule/search timestamps are RFC3339 with an offset, normalized to UTC Z and whole minutes; reject nonzero seconds in user schedule/search input. Provider observation/receipt timestamps may retain seconds; adapter rules explicitly round derived duration values upward. All durations and offsets are integer minutes. Weekdays are ISO 1=Monday through 7=Sunday. Local schedule times are HH:MM, with the departure node's IANA time zone. IDs are opaque strings; CSV relation IDs are not routable lane IDs.

Recommended SQLite tables:

| Table | Key/contents |
|---|---|
| app_state | singleton, dataset_id UUID, schedule/event/clock revisions, plans_revision, integrations_revision, dataset mode and evaluation clock |
| nodes | node ID and validated node JSON |
| lanes | lane ID and validated lane JSON including departures |
| calendar_rules | rule ID and validated scoped rule JSON |
| event_versions | (event_id, version), immutable validated event JSON, received time, withdrawal metadata |
| searches | search_id, request/response JSON, revision snapshot |
| plans | plan_id, immutable initial selection, current selection, computed PlanView, plan_revision |
| decisions | decision_id, plan_id, actor, action, reason, old/new route, immutable reviewed snapshot, timestamp |
| review_snapshots | content ID, full reviewed PlanView, Network, relevant event versions, source observation IDs; immutable |
| origin_progress | plan ID, progress time, frozen origin timeline prefix, work completed and completion state |
| provider_observations | normalized source measurement, fetch/effective times, lane/departure target, raw-response digest and attribution |
| mutation_receipts | mutation_id unique, normalized request hash, response JSON |
| import_summary | source filename, hash, row count, schema and quality findings |

Foreign keys and unique constraints must be enabled. Transactions cover every operational mutation plus revision increment plus recalculation plus response receipt; roll back the whole operation on unexpected failure. Internal recomputation uses the saved-plan rules, never new-search validation; disabled endpoints and unavailable routes produce blocked views rather than input exceptions. Provider network I/O occurs before and outside the transaction. This tiny demo can recalculate saved plans synchronously on mutations. Do not introduce a background queue or allow GET to mutate state.

All mutations carry mutation_id and expected snapshot. An exact retry returns the original response without duplicating anything, even if revisions have since advanced. Reusing a mutation_id with a different request returns 409 IDEMPOTENCY_CONFLICT. Verify expected snapshot for a first application inside the transaction. After reset use a new dataset_id so old requests are rejected even when numerical revisions restart. Decisions also compare plan_revision to prevent two managers overwriting a choice.

## 5. Simulation clock and provenance

Demo initial clock: 2026-09-21T07:00:00Z. Live mode uses a separate database/dataset and wall-clock minute updates from a server worker, with mode controls described in MAP_AND_LIVE_DATA.md. It is frozen until explicitly advanced. A visible badge says "Simulation: 21 Sep 2026 09:00 Europe/Berlin". System wall time is used only for technical logs and receipt timestamps; the simulation clock controls known events, route readiness eligibility, event freshness and scenario display.

The event demo applies a preset immediately at the current simulation clock; event validity can refer to the shipment's future travel window. A separate forward-only clock endpoint demonstrates event expiry. No invisible timer changes dates during the presentation. Frontend polls /api/state every two seconds while visible; watch snapshot for schedule/event/clock changes, plans_revision for plan creation/decisions, and integrations_revision for provider/map status. The latter two are refresh signals outside the expected_snapshot used for operational concurrency. Stop polling while hidden; resume with an immediate read. Invalidate cached search/plan data when the snapshot changes.

Historical CSV date coverage and synthetic seed provenance are always available in the data drawer. Do not claim measured historical ETA accuracy. All event delay values are declared synthetic assumptions or manager estimates. A manager note is not an authoritative legal determination.

## 6. Manager model and state

The single demo identity is demo-manager and is visibly described as a demo role, not secure authentication. Automatic calculation never requires manager approval. Saving an initial route creates a plan. Subsequent events automatically update its projected arrival or mark it infeasible, but the selected lane/departure sequence changes only after a recorded decision.

A selected itinerary fixes every lane and departure occurrence. Re-evaluate those same departures under the new inputs. If it misses a later connection, becomes closed, or the departure no longer exists, selected_feasible=false and selected_projection=null; retain the prior selected itinerary for display/history. Rebooking the same lane path on another day is a new option requiring review.

Recompute alternatives for every saved request after schedule, event or clock mutation using the saved-plan progress rules in ROUTING_RULES section 10. Never reject an existing request merely because its original ready_at is now historical. Plan status: stable if selected remains feasible without material review; review_required if selected is infeasible but alternatives exist, a deadline is missed, or a different feasible option arrives at least 30 minutes earlier; blocked if selected is infeasible and no alternative exists. Optional switches below 30 minutes stay visible but do not demand review. Any infeasibility bypasses that threshold.

Decision actions: accept_route (choose an ID from the latest alternatives), keep_selected (only if selected is feasible) or defer (records acknowledgement but leaves unresolved review/blocked status). All require a nonblank reason. Keeping a feasible plan dismisses review for the same computed recommendation fingerprint until relevant inputs/results change. A deadline breach stays visible even after acknowledgement. Repeated polling must not create duplicate history or reopen the same unchanged recommendation.

If clock reaches or passes the first selected departure, mark status outside_demo_scope and stop automatically rerouting that plan. Show that live position is required; never move a departed shipment back to its origin. Manager changes to its itinerary are disabled. This preserves the explicitly pre-dispatch scope.

## 7. Source-data import rules

Read UTF-8 with optional BOM, comma-separated CSV and ISO date strings. Validate required headers against the supplied source files; fail with filename/column details. Preserve postal prefixes and IDs as strings. Parse intended numeric fields explicitly. Blank nullable cells remain null. Non-null required fields may not become zero by default.

Expected rows: disposition 19,980; relationen 30; kalender 1,050; stoerungen 7; kundenstamm 820; kundensignale 72; vertriebsereignisse 188. Treat counts as fixtures for this provided dataset, not permanent business restrictions for future uploads. Check relation/date joins, customer references with ALLE exception and unique disposition(date, relation). Surface top30 flag count 31 and three missing signal end dates. Do not alter them.

Minimum GUI use: coverage/quality table plus the nullable, structured DataSummary.capacity_example containing one Hamburg capacity example (2024-01-04: 4 planned, 5 needed, 1 special trip, 55.5 loading metres). This example is historical source context and does not affect synthetic route times. Data import must not pretend that volume percentages in stoerungen translate to travel-time delay. The Baden-Wuerttemberg workday flag is not a universal road/air operating calendar.

## 8. Failures and recovery

All errors follow the OpenAPI Error envelope. Surface field errors near controls, retain user input and allow retry. When API is down show "Backend unavailable" with retry, never silently switch to fixtures. 409 responses trigger a refresh/review of the new state; do not auto-resubmit an acceptance against unseen changes. Server exceptions roll back writes and display a trace ID, with details in local logs.

Reset is a destructive local demo action with a clear in-app confirmation explaining that plans, edits and decisions are cleared. Seed reset is deterministic except dataset_id and technical IDs. Frontend must discard old IDs after reset. Do not reset on every server start.
