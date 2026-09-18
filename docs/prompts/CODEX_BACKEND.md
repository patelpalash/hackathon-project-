# Assignment for Codex: backend core and integration

Implement the backend core and integrate the two-person project. Read docs/START_HERE.md, BUILD_SPEC.md, ROUTING_RULES.md, API_CONTRACT.md, contracts/openapi.json, MAP_AND_LIVE_DATA.md, contracts/provider_protocol.py, MERGE_GUIDE.md, AUDIT_RESOLUTIONS.md and ACCEPTANCE_TESTS.md. Version 2.0.0 supersedes earlier prompts. This is an implementation assignment.

You own backend/** except backend/app/providers/**, backend/tests/providers/** and backend/tests/regression/**; those belong to Antigravity. You also own data/**, scripts/**, root README/.gitignore and agreed contract integration. Claude owns frontend/**. Work on codex/backend in a separate checkout; integrate reviewed branches through codex/integration. Do not edit the other writers' files or reset their work.

Use Python, FastAPI, Pydantic, SQLite, pandas and datetime/zoneinfo with tzdata. Expose health/state/network and a real search immediately so Claude can connect. Then build the complete scheduler, event engine, saved plans, decisions and source import. Read original CSVs unchanged from data/raw. They contain operational volume context, not ETA training labels.

Implement all audit corrections: independent plans_revision refresh, OriginProgress and existing-plan clock handling, stable group-maximum delay iteration, exclusion of inactive intermediate nodes, typed capacity_example and immutable reviewed decision snapshots. Distinguish an already-booked cut-off from a new booking's acceptance instant. No in-transit origin reset.

Freeze the provider protocol import location with Antigravity at bootstrap. You implement poll scheduling, credential injection, cache/observation storage, source validation, mode isolation and API endpoints; Antigravity implements provider fetch adapters against the protocol. No network I/O in routing loops or DB transactions. Keep live and demo databases separate, expose missing-key/error states, and never label synthetic observations live. Validate all adapter outputs.

Use exact OpenAPI objects and error envelopes, durable transactions, idempotency and current snapshot/plan checks. Do not serialize schema counters differently on different endpoints. Preserve source provenance and every historical approval snapshot. Run engine/API tests and schema-validate returned payloads. Integrate Antigravity regressions and Claude's GUI, then execute the full browser workflow and production offline fallback.

Maintain small commits. Merge branches in MERGE_GUIDE order after checks, never with hard reset or blanket ours/theirs resolution. Provide setup/init/serve/reset commands, tested dependencies, and a one-command Windows launch after installation. Do not deploy or transmit source datasets externally. Report what is working, commands actually run, evidence, any unresolved limitation and the next gate.
