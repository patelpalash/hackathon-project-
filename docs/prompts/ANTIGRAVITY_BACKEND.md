# Assignment for Antigravity: backend providers and independent regression checks

Implement provider adapters and independently test the backend for our two-person project. Read docs/START_HERE.md, MAP_AND_LIVE_DATA.md, contracts/provider_protocol.py, contracts/openapi.json, ROUTING_RULES.md, AUDIT_RESOLUTIONS.md, ACCEPTANCE_TESTS.md and MERGE_GUIDE.md. Work against version 2.0.0 in your own checkout on codex/backend-antigravity.

You own backend/app/providers/**, backend/tests/providers/**, backend/tests/regression/** and qa/**. Codex owns the engine/API/DB/worker and integration. Claude owns frontend/**. Do not edit those directories or generate a competing dependency lock. Request needed dependencies from Codex. The provider interface in the shared pack is fixed until both backend writers agree on a change.

Implement Open-Meteo, TomTom Calculate Route and optional operator-bulletin adapters. Return ProviderBatch; do not write SQLite, mutate plan state or import the routing engine. Use server-injected credentials, bounded timeouts, explicit units, exact lane/departure mapping, normalized observations, proposed EventInput records and geometry. Preserve source times, attribution and raw-response digests; tolerate extra provider fields while validating required ones.

TomTom key absence must return not_configured. MapLibre is not a traffic provider. Do not turn a point flow sample into a whole-route duration. Do not add total provider travel time on top of the lane baseline. Weather advisory_only is default; demo_thresholds must be explicitly enabled and labeled unvalidated. Traffic and weather for the same lane/occurrence use the declared max-composition group. Political reports stay pending unless feed trust is configured, not merely claimed by fetched content.

Write tests for normal, malformed, missing-field, timeout, 429, stale and duplicate data; offline/no-key operation; exact-departure isolation; and no demo/live mixing. Provider mocks are deliberately synthetic and should not be reported as live verification.

Independently implement the audit regression checks: cross-session plan decisions become visible; ready08Z/clock09Z remains valid; stronger same-group report finishes12Z; inactive Munich excluded; imported capacity data exposed; old decision evidence immutable. Test stale decisions and mutation retries. If core code fails, report a small reproducible case to Codex rather than modifying its files without coordination.

Commit scoped work and hand it to Codex for integration before the final demo. Run configured real-provider smoke tests only when credentials/network are available and report exact outcomes. End each package with changed files, tests run, expected/actual result, defects sent to Codex and outstanding dependencies.
