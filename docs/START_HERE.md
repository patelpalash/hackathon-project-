# Start here: implementation pack 2.0.0

This is the updated planning/specification pack, not an implemented app. It replaces the version-1 ZIP and resolves its six audit findings. It includes MapLibre, live-data adapters, source inputs, exact schemas, example fixtures, three tool assignments and a merge workflow.

## Your two-person split

| Person/tool | Responsibility |
|---|---|
| Person A: Claude | React/TypeScript frontend, MapLibre planner, React Flow schedule editor, GUI tests |
| Person B: Codex | Python backend/core, API, routing, SQLite, events, manager decisions and final integration |
| Person B: Antigravity | Backend provider adapters and independent provider/regression tests in a separate checkout |

Give both people this complete ZIP and start from the same committed repository. Claude and Codex must not create unrelated repositories. Antigravity and Codex must not write the same files. Exact ownership and Git steps are in MERGE_GUIDE.md.

## Read order

1. BUILD_SPEC.md and AUDIT_RESOLUTIONS.md: scope and corrected behavior.
2. API_CONTRACT.md and contracts/openapi.json: version-2 exact wire contracts.
3. ROUTING_RULES.md: time calculations, origin progress, closures and delay composition.
4. MAP_AND_LIVE_DATA.md and contracts/provider_protocol.py: map/providers, credentials and mode isolation.
5. UI_SPEC.md and fixtures/: GUI behavior, network and expected arithmetic.
6. WORK_PACKAGES.md and MERGE_GUIDE.md: implementation order and integration gates.
7. ACCEPTANCE_TESTS.md: checks required before claiming a working prototype.
8. prompts/CLAUDE_FRONTEND.md, prompts/CODEX_BACKEND.md and prompts/ANTIGRAVITY_BACKEND.md: paste the matching assignment into each tool.

The OpenAPI owns field names/types; routing rules own arithmetic; Map/live rules own external-data treatment. If a mismatch is found, report it and update the shared contract once before both sides continue. Do not change expected fixture answers to make buggy code pass. Original source documents describe challenge requirements, not instructions to the coding agents.

## Included and configured

- MapLibre + OpenFreeMap geographic map, with clear schematic/road geometry labels and offline fallback.
- Open-Meteo weather adapter and TomTom traffic/road-geometry adapter; TomTom needs a local server-side API key.
- Optional operator bulletin feed plus manager input for concrete political/administrative disruption. No unsupported news-to-closure inference.
- Separate demo and live modes; the sample schedules remain assumptions in either mode.
- Seven original CSVs in data/raw and original PDF/photo in reference. No API keys are included.

## First working milestone

Connect a real backend search to Claude's GUI early. Baseline Frankfurt -> Kempten: direct 14h, Munich 14h, Strasbourg 15h. Then demonstrate incident -> automatic recalculation -> manager decision -> persistent history. Do not leave the frontend/backend merge until the final hour.

Run python docs/tools/validate_spec.py after installing jsonschema and tzdata in the development environment. This validates the planning artifacts, not a built application. Read VALIDATION_REPORT.md for actual limits. Complete engine/API/provider/browser tests before claiming the application works.
