# GUI behavior specification

## Global frame

Desktop-first, usable at 1440x900 and 1280x720 without horizontal page scrolling. Header: Transit Planner, explicit demo/live mode and evaluation clock, API/provider status and demo manager identity. Left navigation: Planner, Network & schedules, Disruptions & review, Data & assumptions. Main text in English; retain original German source column names in an expandable dictionary. Labels use explicit units. Local times display location zone/offset, not ambiguous bare clock values.

Use restrained blue/white styling with amber handling and labeled red blocked/waiting states. Provide keyboard focus, real labels, accessible dialog titles and text in addition to colors. Bundle fonts/icons or use system fonts. Bundle JS/CSS/workers/icons locally. The geographic basemap uses OpenFreeMap online; when unavailable use the mandatory bundled coordinate overlay fallback and a visible basemap-unavailable label. Core calculations and the deterministic demo still work offline.

## Planner

Top form: Origin combobox, Destination combobox (different from origin), Ready at in origin local time, Service (mixed/road_only), optional arrival deadline, Calculate button. Default origin FRA_HUB, destination KEM_BRANCH, local ready 2026-09-21 10:00 Europe/Berlin. It equals 08:00Z; the browser's current timezone must not alter it. For the demo use an offset-aware conversion helper verified against backend validation. Show an offset selector on ambiguous DST dates or reject ambiguous form values with guidance; do not use new Date(localString) and assume the device's zone is correct.

Results: up to three cards with arrival date/time, total hours/minutes, transfers and source label. First card selected initially; preserve a user's selected route by ID on refresh if it still exists. Selecting a card synchronizes timeline and network. If missing after refresh, select the new best and show an explanation of why the old result disappeared. Never retain an old timeline under a new route card.

Below: MapLibre geographic map with selected/alternative paths, hub markers and disruption markers, plus the timeline showing each handling/wait/travel block. Keep the React Flow schematic in Network & schedules. Clicking a timeline segment highlights its node/lane; a detail drawer shows start/end local and UTC, duration, reason and event source. Label schematic as connections, not street-level road geometry. Show scope "Branch to branch; pickup and final delivery excluded" by results. The geographic map is mandatory in version 2; see MAP_AND_LIVE_DATA.md for providers, geometry types, attribution and offline fallback.

Actions: Save selected plan, Print itinerary, Show assumptions. Save uses search_id + route_id + snapshot from that response. A saved plan is a backend object, not localStorage. The print view includes clock, scope, ETA, route, timeline, sources and assumptions; do not print hidden navigation.

## Network & schedules

Use a read/select React Flow graph with distinct branch/hub/hand-over nodes and mode-labeled edges. Arbitrary drag-to-create/delete topology is outside v1. Selecting a lane opens a form: active, inclusive valid-from/to dates, duration minutes and a full list of departure rules (HH:MM, ISO weekdays, cut-off minutes). Selecting a node allows processing_minutes and active state edits. IDs/endpoints/timezones are read-only in v1.

Save submits complete editable values with expected snapshot, never an unvalidated partial graph object. Disable Save while submitting. On success read the returned revision, invalidate old routes, refresh plans and show the precise change. A 409 preserves the draft and displays current values for review; no silent overwrite. Cancel does not mutate.

## Disruptions & review

Left: event list with category, affected lane/node, effective interval, source (SIMULATED FEED, MANAGER or LIVE PROVIDER), verification, review due, current/withdrawn and description. Filter by current/pending/all. A Report disruption button opens a structured form. Effect selector permits additional travel minutes for a lane, additional handling minutes for a node, or lane closure/cancellation. Node closures and travel-time replacements are unavailable in v1.

Require target, mode, valid start, end or review due, nonnegative delay value where applicable, correlation key/incident selector and reason. Show existing correlated incidents to prevent double counting. Default a new incident key only when user selects "new incident". A manager report explicitly saved as accepted becomes operational immediately; pending reports do not affect calculations. Correct/withdraw forms require reason and expected event version; retain history.

Demo controls: Apply traffic preset, Apply Munich handling preset, Apply border/corridor closure preset, Advance simulation clock, Reset demo. Disable duplicate preset application or report the existing event. Explicitly label these simulated events. Reset asks for confirmation and clears all selections after success. Replays change backend state, not just frontend cards.

Right: saved plans with status and current selected ETA. Open a plan to compare originally selected itinerary, current projection and recommended alternatives. An infeasible projection shows unavailable with reasons, never the old ETA labeled current. Display previous ETA only as historical context. Buttons: Accept selected alternative, Keep current feasible route, Defer. All require a reason. Show blocked constraints and disable Keep when selected is infeasible. Append decision history with actor, time and explanation.

Manager accepts against exact plan revision and snapshot. If state changed, explain that it must be reviewed again. Successful acceptance updates selected itinerary from backend response and records one history entry. It does not send a vehicle instruction, email or external notification.

## Data & assumptions

Seven-row source table with record counts, date coverage and import issues. An example card shows Hamburg's supplied trailer data. Separate synthetic network assumptions: schedules, durations, timezones, coordinates, Sunday pause scope and event estimates. Include limitations: no live GPS, live traffic only when its adapter is configured and usable, no shipment ETA training labels, no secure production identity and no door-to-door service calculation. Do not use decorative accuracy percentages.

## UI state rules

| State | Required behavior |
|---|---|
| Initial | Form visible; useful seeded prompt; no fabricated result. |
| Loading | Preserve inputs, show progress, prevent duplicate mutation submissions. |
| Input error | Field-specific message and retained inputs. |
| Empty/no route | Display bounded-search reason and useful changed-input action. |
| API unavailable | Show connection failure and retry; no fixture fallback. |
| Stale response | Discard a response from an older request counter or revision than a newer accepted state. |
| Event change | Automatically rerun an active unsaved search and refresh saved plans. |
| Scenario clock changed | Refresh state; if ready time is now in the past, explain and request a new time. |
| Printing | Output only selected itinerary and provenance. |

Use AbortController plus monotonically increasing request counters for searches. Poll state every two seconds while the tab is visible, avoiding overlapping polls; compare plans_revision and integrations_revision as well as snapshot. Another manager decision must refresh plans/history without a schedule/event/clock change. A failed poll cannot erase a previously displayed plan; label it disconnected/stale. Never perform a mutation inside a render effect that can run twice. Generate one mutation_id per user intent and reuse only for retries of that same payload.


## Version-2 provider and audit controls

Read MAP_AND_LIVE_DATA.md for mandatory map behavior and status/observation details. The source card reads DataSummary.capacity_example. Decision history expands immutable review_evidence rather than recomputing an old approval against current data. Live missing-key, stale estimate and offline basemap messages must be distinct. Display the sample-schedule and branch-to-branch assumptions in live mode too.
