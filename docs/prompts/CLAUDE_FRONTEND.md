# Assignment for Claude: frontend

Implement the frontend of our two-person transport-planning prototype. Read docs/START_HERE.md, BUILD_SPEC.md, API_CONTRACT.md, contracts/openapi.json, UI_SPEC.md, MAP_AND_LIVE_DATA.md, ROUTING_RULES.md, MERGE_GUIDE.md and ACCEPTANCE_TESTS.md. Follow version 2.0.0 and its exact fixtures. This is an implementation assignment, not another planning response.

You own frontend/** only on codex/frontend-claude, including its package lock and GUI tests. Person B uses Codex for backend/core integration and Antigravity for provider adapters/regression tests. They own backend/**, data/**, scripts/** and root integration files. Read those files but do not edit them. Do not independently rename API fields or modify expected fixtures; propose a justified shared-contract change first.

Use React, TypeScript, Vite, CSS modules, MapLibre GL JS and React Flow. Main planner gets a real geographic MapLibre view with OpenFreeMap, selected/alternative routes and correctly scoped incident markers. React Flow remains in the schedule editor. Follow geometry_kind, [lon,lat] order, attribution, worker bundling and offline/WebGL fallback. Do not describe schematic connections as actual road geometry.

Build search/cards/timeline, schedule forms, imported data/assumptions, live integration statuses/observations, simulated presets, manager reports, saved plans and decisions with immutable history. All ETA calculations and persistence come from FastAPI. An explicit development fixture mode may help early work but defaults off and cannot conceal API failures.

Follow plans_revision refresh and snapshot/plan_revision concurrency. Another manager decision must become visible without a schedule/event/clock change. The saved selected route and the suggested alternative are distinct. Block Keep on infeasible plans and require fresh review for stale approvals. Never post a mutation from a mount effect. Preserve drafts and prevent out-of-order requests overwriting newer results.

Connect a real API search during the first milestone, then implement complete incident -> recommendation -> manager decision -> persistent history. Validate the baseline 14h/14h/15h fixture, map selection, two-tab refresh, origin timezone conversion, inactive hubs, unavailable providers and backend outage. Use the production build when checking MapLibre workers. Report actual checks and observed results.

Commit small scoped packages; push your branch for Person B to merge into codex/integration. Do not create a competing backend or use hard-coded success responses when an endpoint is unavailable. Do not deploy, publish inputs or request secrets in a public file. End each package with files changed, checks run, unresolved issue and precise integration dependency.
