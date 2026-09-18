# Routing and disruption rules, version 2.0.0

Implement these as pure, independently testable Python functions. The HTTP layer must not contain a second version of the arithmetic. All values here describe the synthetic prototype, not real carrier timetables or legal compliance.

## 1. Service boundaries and ordering

- Ready time is arrival at the origin facility before its handling. Handle at every node before an outgoing leg. Do not add destination handling.
- Process one node visit once. Do not charge handling again merely because the next departure is tomorrow. No pickup/delivery stages in v1.
- Enumerate directed, cycle-free node paths with at most five lanes. Respect service profile allowed_modes: mixed permits road and air; road_only permits road. Transfer count is lane count minus one.
- Search from ready_at through ready_at + 14 * 24 elapsed hours, inclusive for final arrival. Reject ready_at before the evaluation clock only for a new user search. Existing saved plans use section 10 progress semantics. Origin and destination must exist and differ. Every visited node, including all intermediate hubs, and every used lane must be active. An inactive endpoint in a new user search is a validation error; in saved-plan recomputation it produces a blocked result, not a failed edit transaction.
- Explore every eligible departure sequence for each path inside that horizon; do not keep only the first departure or prune all later node arrivals. Time-dependent handling events can invalidate simplistic earliest-arrival pruning.
- Keep the earliest final arrival per distinct lane-ID path. Order ties by transfer_count, then joined lane IDs, then departure timestamp sequence. Return up to max_results; never pad with duplicate or impossible routes.
- Bound work at 50,000 evaluated departure transitions per request. If reached, return 503 SEARCH_LIMIT rather than an incomplete list labeled optimal. The seed should fit well under this bound; measure it.
- route.id is the first 24 lowercase hex characters of SHA-256 of canonical JSON with fields lane_ids and departure_times (UTC Z), compact separators and sorted keys. Changes in delay alone retain the same itinerary ID; a departure change changes the ID. Snapshot revisions still distinguish calculated versions.

## 2. Time zones and departures

Lane schedules have weekdays (ISO 1-7), local HH:MM and cutoff_minutes. Multiple departures per day are allowed and have unique IDs. Use the origin node timezone; never server local time. Lane validity dates are inclusive local departure dates. A lane can finish after valid_to if its departure was within validity.

For each occurrence:

```
cutoff_utc = departure_utc - cutoff_minutes
eligible = ready_after_handling_utc <= cutoff_utc
```

Equality is accepted. Cut-off changes acceptance, not the travel duration. Do not move a fixed departure because a shipment missed it. Find the next eligible occurrence. If arrival at a node is earlier than opening/service time, waiting must be represented explicitly. V1 nodes are always open except that scoped event delays can extend handling; broad node opening calendars are deferred.

For nonexistent local schedule times during the spring DST transition, skip that occurrence and attach a schedule warning. For ambiguous repeated local times in autumn, select the earlier UTC occurrence only (fold=0) as the documented demo convention; do not invent a second service. Validate this by round-tripping zone-aware candidates through UTC. User inputs contain an explicit offset: UTC Z is accepted as an absolute instant and converted into the origin zone; a non-Z local offset must agree with the origin's offset at that instant or return 422 TIMEZONE_MISMATCH. Seconds must be zero. Display times using IANA zones and Intl.DateTimeFormat in the GUI.

## 3. Handling and event matching

Use event verification accepted, lifecycle active, observed_at <= evaluation clock and recorded version known by that clock. Events with applies_to_departure_at set apply only to that exact UTC departure occurrence; null uses the interval rules below. Live provider events never enter the demo dataset. received_at is technical provenance, not the simulation knowledge cutoff. An event may concern a future interval and is applicable if already known. Intervals are half-open [valid_from, valid_until); null valid_until means indefinite. Equality to valid_until is outside the interval.

For node handling, start with processing_minutes. Select additional_handling_minutes events scoped to this node/mode (mode refers to the outgoing service) whose windows overlap the handling interval. Extend duration with the grouped delay policy below. Recheck overlap with the extended interval; recompute the complete correlation-key -> maximum-delay mapping, including stronger reports for an existing key. Continue until both mapping values and end time are unchanged. Each changing pass must add a report or increase an effective maximum; bound by eligible report count plus a final stability pass. Recompute base plus current maxima rather than repeatedly adding prior penalties. A zero-duration base node checks events active exactly at arrival as a point rather than using an empty interval. Extra handling remains a handling segment with a separate reason component.

For road/air travel, start with lane duration. Select additional_travel_minutes events scoped to this lane and mode whose windows overlap the predicted traversal interval. Extend driving/flying work and apply road pauses as below, then recheck event overlap. Iterate monotonically until the complete group-to-maximum-delay mapping and traversal end time stop changing, including value changes for existing groups. Delay values must be >=0; do not allow negative events to reduce a duration. These whole-lane delay assumptions are a demo simplification; actual incident location along the road is not modeled.

## 4. Composition and double-counting policy

Each event requires a correlation_key describing the incident. For the same activity and correlation_key, use the largest accepted delay among its current reports; do not sum reports about the same incident. Different correlation keys sum. Every selected maximum and suppressed duplicate report is available in the explanation. An event correction uses the same event_id with a new version, superseding the old version, so only the latest known version participates.

If two overlapping delay reports lack reliable incident identity, queue the new report as pending until a manager supplies/chooses a correlation key. The v1 API requires a nonblank correlation_key. It cannot infer that independently labeled weather and congestion are actually the same cause. The GUI makes this limitation visible and lets the manager select an existing incident.

Do not implement travel_duration_replacement in v1; this intentionally narrows the earlier plan and avoids an undefined mixture of additive and replacement estimates. Future adapters must normalize inputs into these documented event types before automatic acceptance. Do not convert weather severity or source volume percentages directly into hours.

## 5. Closures, cancellations and calendar pauses

closure and departure_cancellation target a single lane in v1. A cancellation invalidates departures whose departure instant lies in the event window. A closure invalidates any occurrence whose full projected traversal interval overlaps the event window. A closure extending into a waiting pause also invalidates that occurrence. Reject that service; do not hold it in the middle of a closed corridor or invent a detour. Try other dates/paths.

closure can have null valid_until; then review_due_at is mandatory and the route stays excluded beyond that review time until corrected/withdrawn. A known-ended closure stops affecting future traversals after its interval, but retain the historical record. Expiry must not erase its relevance to a traversal overlapping the interval in a historical test.

The seed includes one explicit calendar pause: lane L_FRA_HAM, road only, Europe/Berlin, Sunday 00:00 through Monday 00:00. This is a synthetic full-lane proxy rule, not a claim that all lanes or all trucks share that restriction.

Algorithm for pause-aware travel:

1. Let remaining be base travel plus matched delay work; current be departure.
2. Expand relevant recurring blocked intervals into UTC and merge overlapping intervals.
3. If current lies inside a blocked interval, emit a wait until its end; consume no remaining travel work.
4. Otherwise consume min(remaining, minutes until next block), emitting a travel chunk.
5. Continue until remaining=0, or search horizon exceeded. Arrival exactly at block start needs no wait if remaining is already zero.

A scheduled road service starting during a calendar pause is skipped; it is not silently delayed. A service that encounters the rule later pauses under the explicit demo policy above. Air ignores road pauses. Recalculate intervals in UTC so DST changes do not automatically mean a 24-hour pause.

## 6. Timeline and reason codes

Segments must be contiguous, ordered and non-overlapping from ready_at through arrival_at. Drop zero-minute segments. duration_minutes equals (end-start)/60. Their sum equals route.total_minutes. Travel pause chunks belong to the same lane and do not increment transfers. node_id is set for handling/connection waiting; lane_id for travel/pause. The other field is null. A pause segment has type=wait, lane_id set and node_id=null; do not assume every wait must have a node_id.

Reason codes: NODE_HANDLING, EVENT_HANDLING_DELAY, WAIT_DEPARTURE, MISSED_CUTOFF, LANE_TRAVEL, EVENT_TRAVEL_DELAY, CALENDAR_PAUSE. A handling/travel segment can carry several Reason objects with separate contributions; sum(reason.minutes) must equal segment.duration_minutes. For split travel chunks, attribute base work first, then additive event work ordered by correlation key, splitting contributions across chunks as needed; calendar pause minutes have their own wait reason and consume neither base nor delay work. This is a deterministic explanation allocation, not knowledge of an incident's precise road position. A wait's reason indicates MISSED_CUTOFF if a preceding otherwise active departure occurrence was missed at this visit; otherwise WAIT_DEPARTURE. Preserve current event IDs and provenance in each applicable reason. Name suppressed duplicate reports in explanation text but give them no additional minute contribution.

Explain with templates, not generated free-form AI facts. Example: "Traffic report adds 180 min on Frankfurt -> Kempten; demo event TRAFFIC-01." A service rejection is returned in diagnostics with reason code CLOSED_LANE, CANCELLED_DEPARTURE, INACTIVE_LANE, OUTSIDE_VALIDITY, HORIZON_EXCEEDED or DISCONNECTED. Search diagnostics should be concise and bounded, not every explored transition.

## 7. Search outcome and projections

HTTP 200 + status=no_feasible_route is a valid business result; routes is empty. Distinguish structural disconnection, no eligible services within the 14-day window, and profile restrictions in diagnostics. Never claim no route exists anywhere when the bounded model merely found none.

For a saved plan, calculate selected_projection using its exact lane and departure occurrences, ignoring top-three ranking limits. Keep that projection even if it ranks fourth. Handling or travel delays can update it while those connections remain catchable. Inactive/expired/closed or missed occurrences make it infeasible. Compare it to a fresh full search and create review state as defined in BUILD_SPEC.

## 8. Event freshness and corrections

Event verification is pending or accepted; withdrawn is a lifecycle state on a new event version. For accepted delay estimates use review_due_at to flag staleness. If review is overdue, continue its last explicit effect within its validity and label the result "uses an overdue estimate"; do not silently set it to zero. An estimate without an end is allowed only with a review_due_at. When a finite delay's validity ends before a planned traversal, it does not apply. Unknown closure remains blocking when overdue.

POST a correction with event_id and expected_version. Do not change its source/external identity; create version+1. A withdrawal must carry a reason and preserves prior versions. App event_revision increases once per accepted mutation even for pending events; all displayed results refresh from the new snapshot. Duplicate ingestion with the same source/external_id/version and identical content returns the existing event; divergent content returns 409 EVENT_VERSION_CONFLICT. Human correction is explicit rather than a duplicate version.

## 9. Reference scenario arithmetic

All main scenarios use ready 2026-09-21T08:00Z, Frankfurt handling 120 min and the initial clock 07:00Z.

| Path | UTC segment arithmetic | Arrival | Elapsed |
|---|---|---|---:|
| Direct | handle 08-10; wait 10-16; travel 16-22 | Sep 21 22:00Z | 840 min |
| Via Munich | handle 08-10; wait 10-13; travel 13-18; handle 18-19; wait 19-20; travel 20-22 | Sep 21 22:00Z | 840 min |
| Via Strasbourg | handle 08-10; wait 10-11; travel 11-14; handle 14-15; wait 15-18; travel 18-23 | Sep 21 23:00Z | 900 min |

Traffic on the direct lane adds 180 minutes: its arrival becomes Sep 22 01:00Z (1,020 min); Munich becomes first. A manager then adds 180 minutes to Munich handling: ready there becomes Sep 21 22:00Z, after the 19:30Z cut-off, so next departure is Sep 22 20:00Z; arrival Sep 22 22:00Z (2,280 min). Strasbourg now wins. Closing Strasbourg's onward lane through Sep 24 leaves the delayed direct path as first. These outcomes are independent of algorithm implementation and must not be rewritten to match a faulty engine.

## 10. Saved-plan progression and clock changes (audit F2)

New searches require ready_at >= evaluation_at. Existing plans retain their original ready_at; internal recomputation must not invoke that new-search check. Evaluation time advances before departure without moving the shipment back to the beginning of origin handling.

Each plan stores OriginProgress: recorded_at, frozen_segments, completed_work_minutes, handling_complete and first_mode. Before a clock advance, materialize the origin timeline prefix from the previous projection up to the new evaluation instant, capped before departure. Freeze already elapsed handling and waiting with their original reasons; split a segment at the boundary if necessary. If time is still before ready_at, prefix is empty. In this prototype origin processing follows the prior accepted projection; this is simulated execution, not a physical tracking feed.

For pending handling, recompute the required total origin work from current node rules/events and subtract completed_work_minutes, clamped to zero. Start only the remaining work at max(evaluation_at, original ready_at). Do not charge the whole handling duration again. If handling was already complete, a later change in its duration does not undo completed work; add a warning that the change applies to future shipments. A manager-requested rework workflow is beyond v2. If no clock time advanced, completed work is unchanged and ordinary event recalculation still applies.

For new alternative bookings, compare max(evaluation_at, recomputed processing completion) to the candidate departure cut-off; never propose a new booking with a past cut-off or departure. For the already selected booking, retain evidence that the original cut-off was met; passing that cut-off while waiting does not cancel an already booked shipment. Delays that make its handling finish after the actual departure invalidate it. Before its cut-off is reached, the existing standard eligibility check remains applicable. This booking-status distinction must be covered in tests.

The original selected lane/departure sequence remains fixed for projections. Alternative plans prepend the frozen prefix and append remaining handling, waits and travel; total elapsed duration still starts at the original ready_at. New alternatives preserve the initial transport mode so completed mode-specific origin handling is not reused for a different mode. Creating a new request is required for a first-mode change. No current seed alternative requires that change.

When evaluation_at >= the selected first departure, transition to outside_demo_scope before trying to re-search. At exact equality it is already outside the pre-dispatch scope. No recorded progress implies live GPS. Future inactive endpoints/hubs/lanes produce blocked/infeasible business results, not exceptions that undo the valid administrative change.

Counterexample regression: save ready 08:00Z, origin handling 120 min, first departure 16:00Z. Advance to 09:00Z: freeze 60 min of origin work, perform only 60 more minutes, keep the original 22:00Z arrival and total 840 min. Advance to 15:30Z: retain booked direct 16:00 service even though its 15:00 cut-off passed; do not offer it as a new alternative booking. At 16:00Z mark outside_demo_scope.

## 11. Live provider inputs

The same engine runs on a live dataset, but its clock, provider observations and sample schedule dates are isolated from the fixed demo. Follow MAP_AND_LIVE_DATA.md for exact-departure event matching, source provenance, request budgets, weather policy and stale-data treatment. Calculate from cached, validated observations only. The routing engine must never fetch a weather/traffic URL while enumerating paths.
