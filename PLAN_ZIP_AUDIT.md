# Audit of the delivered implementation ZIP

Reviewed artifact: TRANSIT_PLANNER_IMPLEMENTATION_PACK.zip, 18 files.

SHA-256: dbea76e8f90aee05139d873ec4e05fba470c489a940f8072628355b0f14b0719.

The review read the ZIP entries directly. At review time all corresponding workspace files were byte-identical to the archived entries, so their line references below also identify the archived content. The ZIP and specification files were not modified by this review. This report is separate from the archive.

## Findings that need specification changes before implementation

### F1 — High: another manager's decision cannot trigger the prescribed refresh

Evidence: docs/API_CONTRACT.md lines 53 and 94; docs/contracts/openapi.json schemas State and Snapshot; docs/UI_SPEC.md line 55.

The UI polls only /api/state and refreshes saved plans when its snapshot changes. Decisions explicitly do not change any of the schedule/event/clock revisions. State contains no plan revision or plans collection revision. Creating a plan similarly has no defined observable state revision.

Reproduction from the contract: browser A and B show the same saved plan; A accepts another route; only plan_revision changes; B continues to receive the identical State response and therefore never fetches the changed plan. Server-side stale-decision checks still protect writes, but B displays stale operational information indefinitely until another unrelated change or explicit refresh.

Fix: add a monotonic plans_revision to the state response, increment it on plan creation and changed plan/decision state, and make the client use it to invalidate plan views. Alternatively explicitly poll the currently visible plan and plan list. Avoid using a presentation refresh counter to invalidate unrelated route-search snapshots unnecessarily.

Acceptance: in two tabs, accepting/keeping/deferring and creating a plan in one becomes visible in the other without changing a lane/event/clock and without a manual reload.

### F2 — High: moving the clock can invalidate normal saved-plan recomputation

Evidence: docs/ROUTING_RULES.md line 10; docs/BUILD_SPEC.md lines 58, 76 and 80; docs/API_CONTRACT.md semantic ready_at validation.

New searches reject ready_at before the simulation clock, yet saved requests are searched again on every clock change. There is no separate rule for historical ready_at in an existing pre-dispatch plan.

Reproduction: save the default ready_at=08:00Z itinerary, whose direct departure is 16:00Z. Advance the clock to 09:00Z. The shipment has not departed, so outside_demo_scope does not apply. The required fresh search uses ready_at=08:00Z and now fails PAST_READY_TIME. Since recalculation is inside the clock mutation transaction, a literal implementation can reject/roll back an otherwise valid clock change. An implementation that bypasses the check without further rules could recommend a departure already in the past.

Fix: distinguish validation of a new search from recomputation of an existing plan. Specify an evaluation instant, retain handling already performed under the chosen simulation policy, and forbid new departures earlier than the evaluation instant. Do not simply replace ready_at with now and charge all handling again. Define exactly what happens at departure equality, not only after it.

Acceptance: advance from before ready time to between ready time and departure; recalculate successfully, preserve elapsed processing consistently and propose no past departure. Then advance to/after departure and verify the documented scope transition.

### F3 — Medium: the delay-iteration stopping rule can undercount a stronger report

Evidence: docs/ROUTING_RULES.md lines 35 and 41.

The plan says each pass must add a group or stop, but also says use the largest report within a correlation group. Extending an interval can expose a stronger report for an already-matched group, without adding a new group.

Counterexample: base handling is 08:00-09:00. A report for incident A adds 60 minutes, extending it to 10:00. A second report for incident A starts at 09:30 and estimates 180 minutes. No new group exists, but the required maximum changes from 60 to 180, so completion should become 12:00. A new-group-only stopping condition can incorrectly stop at 10:00.

Fix: iterate until the complete correlation-key-to-effective-delay mapping and interval are stable, not just the key set. Recompute from base duration plus the current group maxima; do not repeatedly append the full penalty. Require monotonic effective changes and a finite bound based on candidate reports.

Acceptance: include the same-group stronger-report example, plus repeated passes that must not add the same delay twice.

### F4 — Medium: disabling an intermediate hub lacks an explicit routing rule

Evidence: docs/UI_SPEC.md line 21 allows every node's active flag to be edited; docs/API_CONTRACT.md and docs/ROUTING_RULES.md mandate active origin/destination but do not explicitly exclude inactive intermediate nodes.

A literal implementation can validate Frankfurt and Kempten, then still route through an inactive Munich hub. The intention is inferable, but an implementation handoff should state it precisely.

Fix: all visited nodes must be active; an inactive node removes its incident connections from candidate traversal. Reevaluate existing selections through that node and treat them as infeasible. An already-saved plan whose endpoint is disabled needs a business blocked state rather than an input exception that prevents the disabling transaction.

Acceptance: deactivate MUC_HUB and confirm both new searches and saved projections exclude its transit path; reactivation restores it.

### F5 — Medium: the required capacity example has no structured API payload

Evidence: docs/BUILD_SPEC.md line 88 and docs/UI_SPEC.md line 39 require the Hamburg trailer example. OpenAPI DataSummary contains only sources, assumptions and import_complete; SourceSummary contains only file/row/date/issue/hash metadata. No endpoint exposes operation rows or the example values.

Frontend and backend assistants could both follow their assignments and still fail to integrate this card. A frontend would have to hard-code the supplied numbers or extract them from free-text assumptions.

Fix: add a small typed capacity_example object to DataSummary or a bounded read-only source-example endpoint, including source filename, relation, date, planned/needed trailers, special trips and loading metres. If instead it is intentionally a static educational example, say so explicitly and do not present it as dynamically imported data.

Acceptance: editing a copied test dataset's example row changes the API-backed card after reimport; missing example is shown as unavailable rather than defaulting to old numbers.

### F6 — Medium: decision history cannot reliably reconstruct what was approved

Evidence: OpenAPI Decision stores previous/new route IDs and a revision counter; docs/ROUTING_RULES.md line 14 gives identical route IDs to different delay projections; docs/BUILD_SPEC.md lines 48-54 propose current node/lane records, event versions and current/initial selections.

The minimal who/when/action log is specified, but a full reconstruction of the reviewed ETA and timeline is not. Delay changes can keep the same route ID, and later schedule edits overwrite current records. A numeric schedule_revision does not itself preserve the referenced schedule. Initial/current plan selections also do not preserve every intermediate review.

Fix: save an immutable reviewed-plan snapshot with each decision (selected and proposed itinerary, ETA/timeline, applied events, schedule snapshot/version), or provide a complete versioned schedule/result repository referenced by the decision. Keep the light actor/reason list for the UI, but retain the evidence behind each entry.

Acceptance: accept an option, change its duration and event severity, restart the application, and still show the exact before/after ETA and reasons reviewed at the earlier decision.

## Product gaps and scope risks (not hidden implementation bugs)

### G1 — Geographic map is not included in the delivered version

Evidence: docs/UI_SPEC.md lines 7 and 15; docs/BUILD_SPEC.md line 13. The mandatory visualization is React Flow; geographic maps are optional and external tile dependencies are excluded. There is no MapLibre dependency, tile-provider configuration, map lifecycle, geometry contract or map acceptance test.

This was an explicit earlier simplification, but it does not capture the subsequent discussion about using a geographic map. To include one, update the same ZIP/specification version with the renderer, map-data source, attribution, network-failure fallback and route/incident selection synchronization. Distinguish schematic straight connections from real road geometry. A map display does not supply traffic or arrival calculations by itself.

### G2 — Automatic recomputation is present; automatic live data acquisition is absent

Evidence: docs/BUILD_SPEC.md line 9; docs/UI_SPEC.md line 31; OpenAPI EventInput source_kind only accepts demo_feed or manager. There is no provider adapter, real observation mapping, refresh policy or live-to-demo clock policy.

The demo can automatically respond to injected incidents, but cannot independently discover today's traffic/weather/border conditions. This is clearly labeled in the files and is a legitimate prototype boundary; it should not be described to judges as a live monitoring system. Adding a provider would require extending the contract and defining how measured lane times become impacts without double counting. Keep live evaluation time separate from the fixed September scenario clock.

### G3 — The two-person effort estimate is optimistic

Evidence: docs/WORK_PACKAGES.md lines 3 and 61-65. The backend's three-hour B3 includes event versioning, saved plans, projections, recommendations, approvals, audit, idempotency and revision protections. The full package has 18 operations, four GUI views and a nontrivial temporal routing engine.

This is an estimate risk, not a proven timing failure. A small vertical workflow should be the first delivery: search -> incident -> recomputed option -> manager decision -> persisted history. Additional editing screens and breadth should follow only after that loop passes. Preserve safety against stale decisions while reducing peripheral work.

## What the existing validation proves

The ZIP's VALIDATION_REPORT correctly limits its claim to schema/reference checks and a limited replay of the eight fixture paths. docs/tools/validate_spec.py greedily chooses the minimum-arrival service at each reference step and does not run a production exhaustive search, state machine, HTTP API or GUI. That is acceptable for checking those simple fixtures, but does not detect F1-F6 or establish global optimality for time-dependent routes.

The review inspected the archived schemas and constructed explicit counterexamples for F1-F3. These are specification-level deductions; there is no implemented application in this ZIP on which to reproduce runtime failures. The existing positive fixture arithmetic is not invalidated by these findings.

## Recommended repair order

1. Resolve state refresh and saved-plan clock/recalculation semantics (F1, F2).
2. Make delay convergence and inactive-node behavior explicit (F3, F4).
3. Close the source-example API and historical-review evidence gaps (F5, F6).
4. Decide the geographic-map and live-feed scope and update all affected prompts/contracts together (G1, G2).
5. Add regression cases for these findings and issue a clearly versioned replacement ZIP. Do not silently overwrite the audited archive and call the findings already fixed.
