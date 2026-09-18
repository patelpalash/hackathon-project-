# API integration contract

Machine-readable source: contracts/openapi.json (OpenAPI 3.1). All properties shown in a schema are required. An optional semantic value is explicit null, not a missing field. Arrays are empty rather than null. Unknown properties are rejected. This strictness avoids different assumptions in the two independently coded halves.

Generate frontend types from this file or manually transcribe and test them; do not create a second incompatible interface. FastAPI-generated /openapi.json will naturally differ in titles/operation metadata; compare paths, methods, requiredness, enum values, payload shapes and response status codes rather than requiring byte equality. The checked-in contract remains the agreed source until both owners approve a change.

## Operations

| Method/path | Body schema | Success schema/status |
|---|---|---|
| GET /api/health | none | Health, 200 |
| GET /api/state | none | State, 200 |
| GET /api/network | none | Network, 200 |
| GET /api/data-summary | none | DataSummary, 200 |
| POST /api/routes/search | SearchRequest | SearchResponse, 200 |
| PATCH /api/lanes/{lane_id} | LaneUpdate | LaneMutationResult, 200 |
| PATCH /api/nodes/{node_id} | NodeUpdate | NodeMutationResult, 200 |
| GET /api/events | none | EventList, 200 |
| POST /api/events | CreateEvent | EventMutationResult, 201 |
| POST /api/events/{event_id}/revisions | ReviseEvent | EventMutationResult, 201 |
| GET /api/plans | none | PlanList, 200 |
| POST /api/plans | CreatePlan | PlanView, 201 |
| GET /api/plans/{plan_id} | none | PlanView, 200 |
| GET /api/plans/{plan_id}/decisions | none | DecisionList, 200 |
| POST /api/plans/{plan_id}/decisions | DecisionRequest | DecisionResult, 201 |
| POST /api/demo/presets | ApplyPreset | EventMutationResult, 200 |
| POST /api/demo/clock | AdvanceClock | State, 200 |
| POST /api/demo/reset | ResetRequest | State, 200 |
| GET /api/map/geometry | none | MapGeometry, 200 |
| GET /api/integrations | none | Integrations, 200 |
| GET /api/integrations/observations | none | ObservationList, 200 |
| POST /api/integrations/refresh | RefreshIntegrations | RefreshResult, 200 |

The three preset IDs are traffic_direct, handling_munich and closure_strasbourg. Their initial data is in fixtures/presets.json. An already applied preset returns its existing event without adding another delay. Corrections and withdrawals require explicit event-revision operations; reapplying a withdrawn preset must not silently reactivate it. The demo script starts with reset when replaying from scratch.

## Exact request example

See fixtures/search-request.json. Initial request:

```json
{
  "origin_id": "FRA_HUB",
  "destination_id": "KEM_BRANCH",
  "ready_at": "2026-09-21T10:00:00+02:00",
  "service_profile_id": "mixed",
  "max_results": 3,
  "arrival_deadline": null
}
```

This equals 08:00Z. fixtures/search-response.json contains all three complete route/timeline responses, including stable route IDs. The fixture dataset_id and search_id are specification examples; runtime produces its own dataset/search identities. Do not expect API responses to copy those technical IDs.

POST search stores its response for subsequent plan selection, but does not change the application revision snapshot. POST plan requires search_id, route_id, name, mutation_id and that snapshot. Server confirms the route belongs to the stored search and current state; client cannot supply arbitrary itinerary JSON. If stale, return 409 and require a new search. Limit saved plans to 25 for this bounded demo and return a clear 422 DEMO_PLAN_LIMIT on overflow.

## Snapshot and concurrency

Every snapshot contains dataset_id, schedule_revision, event_revision and clock_revision. Reset creates new dataset_id and initial revisions (1,0,0). Lane/node updates increment schedule_revision; new/corrected/withdrawn events increment event_revision; a forward clock change increments clock_revision. A search or plan decision does not increment these global calculation revisions. State.plans_revision increments for plan creation and any changed plan view or decision, once per committing transaction; clients watch it independently. State.integrations_revision signals provider/geometry metadata changes. Neither counter belongs in expected_snapshot, so unrelated manager actions do not invalidate searches. Each saved plan has a separate plan_revision that increments on any changed computed view or accepted decision, not on unchanged polling.

Expected snapshots compare all four fields. Missing/incorrect IDs are errors, not a request to use current state. Idempotency replay is checked first. All first-application mutation responses contain the resulting snapshot directly or inside the returned plan. A stale decision must never overwrite new event information. A fresh retry requires human review and a new mutation_id if its payload changes.

## Semantic validations beyond JSON Schema

- ISO date/time inputs require explicit offset and minute precision; ready_at offset must match origin timezone. ready_at >= evaluation clock for new searches only; arrival_deadline if supplied >= ready_at. UTC Z is accepted when it represents the input instant and the request uses UTC explicitly: for Z input normalize into the origin zone rather than reject it. Non-Z local offset strings must match the origin zone.
- Origin and destination differ; every visited node and lane must be active. All graph references exist; each lane connects distinct nodes. Duration >0; handling >=0; cut-off >=0. Valid-from <= valid-to. Departure IDs unique within a lane; no duplicate weekday/time occurrence after expansion.
- Event effect additional_handling_minutes requires target_kind=node. Other effects require target_kind=lane. Lane-target mode must match lane mode. Delay events require integer effect_minutes >=0; closure/cancellation require null. Node-target mode filters outgoing services.
- valid_until when supplied > valid_from. Unknown end requires review_due_at > observed_at. review_due_at, if present, must be > observed_at. observed_at <= simulation_clock. A new create must be active; withdraw only via explicit revision.
- Event identity and source fields cannot be changed in a correction. expected_version must match current version. Manager submissions are marked reported_by=demo-manager by the server. Demo preset events keep explicit simulated-source labels.
- All creates/corrections require a reason of 3-1000 trimmed characters; whitespace-only strings fail. correlation_key and source identity strings are trimmed and nonblank. Unknown target is 422, unknown addressed resource path is 404.
- Decision accept_route requires non-null route_id from latest alternatives. keep_selected/defer require route_id=null. keep_selected fails if selected is infeasible. Snapshot and plan_revision must both match. Decisions on outside_demo_scope fail.
- In demo mode the clock moves forward or remains equal; equal is a no-op preserving revision. In live mode the worker advances it and the manual demo-clock/preset endpoints return MODE_MISMATCH. Reset uses confirm=RESET_DEMO. Presets must not rewrite the simulation clock.
- Node/lane editing only affects fields allowed in NodeUpdate/LaneUpdate; do not allow changing origin, destination, ID or timezone through extra fields.
- EventInput.applies_to_departure_at is either null (interval-scoped) or an exact UTC departure of a lane-target event. Non-null is invalid for a node target. observation_id links normalized provider evidence or is null for manual/demo events. source_kind=provider is accepted only from adapter-internal ingestion, not public manager event creation/revision; expose a 422 PROVIDER_SOURCE_RESERVED error to public callers attempting it.
- Decision.review_evidence is server-generated and immutable; clients never submit this field. Include the reviewed selected/proposed route, projection, network snapshot, applicable event versions and observation references. Keeping/defer has proposed_itinerary=null. Preserve evidence after later edits.
- DataSummary.capacity_example is null when source import/example is missing. Otherwise populate its typed values from the imported row and relation metadata, never from a hard-coded frontend constant.
- The two display counters State.plans_revision and integrations_revision are outside Snapshot. A plan create/decision increments plans_revision; a changed recalculation transaction increments it once even if several plans changed. A provider status/geometry change increments integrations_revision. GET remains read-only.
- Live mode rejects manual demo presets/clock/reset with 422 MODE_MISMATCH. Live /api/integrations/refresh follows its documented two-phase concurrency behavior; it does not hold the database lock during provider requests. Demo mode returns MODE_MISMATCH for live refresh.

## Error envelope

```json
{
  "error": {
    "code": "STALE_SNAPSHOT",
    "message": "Conditions changed. Refresh the plan before deciding.",
    "details": [],
    "trace_id": "local-example-001",
    "current_snapshot": {
      "dataset_id": "runtime-dataset-id",
      "schedule_revision": 1,
      "event_revision": 2,
      "clock_revision": 0
    }
  }
}
```

Standard codes: 404 NOT_FOUND; 409 STALE_SNAPSHOT, STALE_PLAN, EVENT_VERSION_CONFLICT, IDEMPOTENCY_CONFLICT, ROUTE_INFEASIBLE; 422 VALIDATION_ERROR, TIMEZONE_MISMATCH, PAST_READY_TIME, DEMO_PLAN_LIMIT, OUTSIDE_DEMO_SCOPE; 503 SEARCH_LIMIT or STORAGE_UNAVAILABLE. Unexpected 500 uses the same envelope with INTERNAL_ERROR; include no stack trace in UI. All operation schemas include a 500 envelope; clients handle non-2xx envelopes generically. Override FastAPI's default validation exception response to match this format.

Empty result is 200 no_feasible_route, not an exception. Get collections sorted deterministically: nodes/lanes by ID, events by observed_at then ID, plans by ID, decisions chronologically then ID. Collections are small and complete in v1; no pagination is implied.

## UI refresh agreement

Poll state every two seconds while visible. Compare snapshot plus independent plans_revision and integrations_revision. On plans_revision changes fetch the plan list, visible plan and decisions even when snapshot is unchanged. On integrations_revision changes fetch integrations and map geometry metadata. On calculation revision changes refresh visible network/events/plan state and automatically rerun a valid active search. Guard against out-of-order responses. After any successful mutation, update the known snapshot immediately; do not wait for a poll. Keep unsubmitted manager drafts intact during refresh and mark their expected snapshot stale until reviewed.
