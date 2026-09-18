# Acceptance and regression checks

Use docs/fixtures/acceptance.json as expected results, not as runtime results. Reset fixture state between independent cases. S1-S3 specify cumulative event sets; a test should load exactly the named events. The simulation clock is specified per case. Future fixture requests are intentional. No machine current date should affect outcomes.

## Expected numerical scenarios

| Case | Setup | Expected |
|---|---|---|
| S0 | No events; FRA -> KEM ready Sep 21 08Z | Direct 22Z / 840 min; Munich 22Z / 840; Strasbourg 23Z / 900, in that order |
| S1 | Traffic direct +180 | Munich 22Z / 840; Strasbourg 23Z / 900; direct Sep 22 01Z / 1020 |
| S2 | S1 plus Munich handling +180 | Strasbourg Sep 21 23Z / 900; direct Sep 22 01Z / 1020; Munich Sep 22 22Z / 2280 |
| S3 | S2 plus Strasbourg closure through Sep 24 00Z | Direct Sep 22 01Z / 1020; Munich Sep 22 22Z / 2280; Strasbourg Sep 24 23Z / 5220 |
| S4 | Ready Sep 21 13Z; no events | Direct handling finishes exactly at 15Z cut-off; arrives 22Z / 540 min |
| S5 | Ready Sep 21 13:01Z | Direct misses cut-off; Sep 22 22Z / 1979 min |
| S6 | FRA -> HAM ready Sep 26 08Z | Depart Sat 18Z; 4h travel +24h calendar pause +4h travel; arrive Sep 28 02Z /2520 min |
| S7 | IST branch -> KEM ready Sep 21 06Z, clock 05Z | Air/road chain via FRA direct arrives Sep 22 22Z /2400 min; alternative paths in JSON |

S3's Strasbourg option can wait until reopening and remain feasible inside the search horizon. Do not mistake a temporary closure for permanent network deletion. Baseline initial ranking chooses direct on equal arrival because it has fewer transfers.

## Engine tests (Codex/Antigravity)

1. No self-routes, missing nodes, inactive endpoint, negative duration or malformed offset. Verify exact Error shape.
2. Both 2026-09-21T10:00:00+02:00 and 08:00:00Z produce the same FRA result. A local non-Z +03:00 offset for that Frankfurt date is rejected.
3. At cut-off equality the service is catchable; one minute after is not.
4. Departure validity is inclusive on departure date. Arrival after valid_to is allowed. Outside dates are rejected as occurrences.
5. Same-node handling charged once; destination handling not charged. Increase destination's stored handling and prove the result is unchanged under branch-to-branch scope.
6. Multiple departures on a lane: evaluate later feasible departures too. Include an artificial later service whose event exposure causes earlier arrival to catch incorrect pruning.
7. Cycles are never returned; max five lanes and 14-day horizon enforced; search-limit exhaustion is an error rather than a supposedly complete result.
8. Sunday pause exact boundaries and overlap merging; air unaffected; another road lane without that rule unaffected.
9. DST unit fixtures independent of main seed validity: Europe/Berlin 2026-03-29 02:30 does not exist; 2026-10-25 02:30 chooses first occurrence (00:30Z). Full-day blocked duration can differ from 24 hours across DST.
10. Event interval ending exactly at departure does not overlap travel; an event beginning before arrival does. An event outside the route's scope does not alter it.
11. Duplicate same-incident delay estimates of 120 and 180 contribute 180, not 300. Different explicit incident groups of 120 and 180 contribute 300. Correction supersedes an earlier version.
12. Pending report has no operational effect; accepting its revision causes recalculation. Withdrawal reverses its contribution without deleting audit history.
13. Unknown-ended closure remains blocking after review_due_at; warning becomes overdue. Finite closure allows later departures after reopening.
14. Added delay exposes a later event window; verify the additional group is evaluated once. Calendar waits and event work must not be double-counted.
15. selected_projection preserves fixed departure occurrences. A missed intermediate connection makes the selected itinerary infeasible even when a later same-path search route exists.
16. Final timestamps monotonic and all segments contiguous; total=sum(segment durations)=arrival-ready. No zero-duration rendered segments.
17. All outbound FRA->KEM-reachable lanes closed indefinitely (direct, FRA_MUC, FRA_STR): no_feasible_route, no fabricated alternative. The HAM dead end must not become an invented HAM->KEM link.
18. Road-only from Istanbul to Kempten: no feasible path because the only connecting international seed service is air.

## API/persistence tests (Codex/Antigravity)

- All 18 operations have the required fields, status codes and envelope. Use JSON-schema validation against the checked contract for representative responses, not only Python model assertions.
- GETs never change snapshot, plan_revision or decision count. Searches may store a snapshot but do not change app revision.
- Schedule mutation changes one global schedule revision; event mutation changes one event revision. Changed plan views get new plan revisions. Idempotent repeat does neither.
- Same mutation ID and same request return the prior response; same ID with changed body gives 409. Check retries of POST plans, events and decisions.
- A stale snapshot, plan revision or event version cannot overwrite a newer state. Concurrent conflicting accepts result in one success and one conflict.
- accept_route must reference a current returned alternative; do not accept client-invented itinerary IDs. keep_selected on infeasible route returns ROUTE_INFEASIBLE.
- Simulate a failure during recalculation/storage and verify event/edit/revision/decision are all rolled back. The UI must not show a successful half-write.
- Save/edit/event/decision survive restarting the process. Initialization does not reset the database.
- Reset changes dataset_id and clears plans, mutations, searches, events and decisions. A request from the previous dataset cannot be applied to the reset state.
- Clock cannot go backwards; reaching departure marks saved plan outside_demo_scope. No automatic rerouting from the origin after departure.
- Missing source files appear as import issues without fabricated counts. Final provided dataset import reconciles row counts and hashes; originals unchanged.

## Browser walkthrough (Claude, real API)

1. Fresh launch and reset. Header shows simulation clock, source labeling and API online.
2. Calculate default FRA->KEM. Cards show 14h/14h/15h. Select each; network and timeline agree.
3. Save direct as "Judge demo". Apply traffic preset. Without clicking Calculate, current direct ETA updates to Sep 22 01Z, Munich recommendation appears.
4. Accept Munich with reason. Selected plan and history update exactly once.
5. Apply Munich handling preset or enter equivalent accepted manager report. Selected Munich connection becomes infeasible, Strasbourg is recommended.
6. Try Keep current: disabled/infeasible explained. Accept Strasbourg with a reason; reload and see both decisions and the selection persist.
7. Apply Strasbourg closure. Updated alternatives show delayed direct before waiting for reopening. Review and accept direct.
8. Open another session and change a lane, then attempt acceptance using stale state in the first. Show a refresh-required conflict; do not silently accept.
9. Reset; ready time 15:00 Frankfurt local catches the direct cut-off after handling; 15:01 misses it. Show revised timeline.
10. Stop backend. Visible connection error appears; no fake route refresh. Restart and recover persisted state.
11. Run packaged frontend/backend with internet disconnected after installation; all required screens and calculations still work.
12. Keyboard-tab through the main form and review dialog; inspect at 1280x720 and 1440x900 for clipped controls/labels.

## Pass criteria

All numerical fixtures, critical state/approval/persistence cases and the real browser workflow pass. Target search/recompute <2 seconds on seed data; record actual timing and machine context. No accuracy percentage is claimed. A known limitation is documented; an essential broken calculation or nonfunctional GUI action is fixed before calling the prototype complete.


## Version-2 mandatory audit and integration regressions

- F1: open two browser sessions; create a plan and accept/defer/keep in one. The other refreshes via plans_revision without changing calculation Snapshot. Unrelated decisions do not invalidate an active search.
- F2: ready08Z/origin handling120/depart16Z; advance09Z -> 60 minutes remain and arrival stays22Z. At15:30 retain the already booked16Z departure but do not permit a new booking after15Z cut-off. At16Z transition outside_demo_scope. No double-counted handling or past-departure recommendation.
- F3: base08-09; same incident60min then a stronger180min report beginning09:30 -> finish12Z, not10Z and not13Z. Repeated iterations must be idempotent.
- F4: disable MUC_HUB; remove its path from fresh search and invalidate a saved selection. Disable a saved origin -> blocked state, not rollback of the admin edit. Reactivation restores eligible paths.
- F5: capacity_example values reconcile to imported disposition/relations. Missing source returns null; frontend must not retain a previous sample as current.
- F6: record an approval; change lane duration/events and restart. Historical review_evidence retains exactly the previous ETA, timeline and sources.
- Map: validate lon/lat order, geometry provenance and selected route synchronization; test production worker, required attribution, tile failure and WebGL fallback.
- Providers: no key -> not_configured; malformed/missing/unit errors -> visible failure; 429/backoff bounded; identical polls -> no duplicate effect; traffic/weather same group -> max not sum; exact-departure effect never leaks to next day.
- Mode: provider observations cannot enter deterministic demo. Live clock cannot be set by preset controls. Operator feed self-declared trust is ignored. Weather advisory_only does not secretly add minutes.
- Merge: a clean checkout with common contracts can install/build/run both parts; independent package locks and documented env examples work; no secrets or dependency folders in commits.

The artifact validator checks schemas, fixtures and a few independent arithmetic oracles. The above state, provider and browser cases must run against the actual implementation before claiming runtime correctness.
