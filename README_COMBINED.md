# Transit — combined hackathon prototype

This version combines the Codex-style planner, Scenario Studio and manager workflow with the latest ZIP's shipment dashboard, historical analytics, cost/fuel estimates and MapLibre/OSRM road routes. The original Codex project remains separate.

## Open the running version

- Frontend: http://127.0.0.1:5175/
- Backend API docs: http://127.0.0.1:8003/docs
- Run `powershell -File .\start.ps1` from this folder to start locally. Requires Node/npm and Python 3.11–3.13. Dependencies install on first launch. Logs go in `.runtime`.

## Judge demo (3 minutes)

1. Open Route planner. Choose Karlsruhe → Dresden. Set a weekday departure and a deadline two days later. Calculate routes.
2. Select an alternative: its real road polyline, intermediate hub, destination distance, detour, ETA, fuel and cost appear together. Every option is a planning estimate, not a booked carrier departure.
3. Apply Heavy traffic in Scenario Studio. It adds 180 minutes to that direct corridor and automatically recalculates. A transfer alternative may become faster. Events are labelled simulations. Resolve the event to remove its effect.
4. Save a selected plan for review. Open Control room, select that shipment and review recalculated options. Enter a reason; accept, keep or defer. Accept writes the selected plan to the shipment. Deadline misses require an explicit acknowledgement. Changed conditions invalidate old approvals.
5. In Weather lab enter Heavy Snow, visibility 500 m, wind 35 km/h, HIGH severity at a route facility. Choose an observation window covering the planned journey. Save or edit the record. The common weather engine generates the alert and route delay; dashboard and hubs show matching alerts. LOW/clear records can resolve the alert without a live API key.
6. Use Load Saturday demo. Select Via Chemnitz (when OSRM supplies this corridor). Show Saturday arrival, Weekend Hold through Sunday, and Monday onward movement.
7. Show Network intelligence and Assumptions to explain exactly which inputs are measured, derived or simulated.

## Fixes and implementation

- `backend/app/hub_selection.py`: road corridor screening, operational/capacity eligibility, road detour verification, nearest-destination priority. No forced Heilbronn intermediary. Up to three suitable alternatives; no invented hub when road routing is unavailable.
- `backend/app/weekend.py` and `restrictions.py`: Saturday intermediate arrival → Monday eligibility; Sunday full-day business restriction; holiday chaining and Europe/Berlin daylight-saving handling.
- `backend/app/weather_rules.py`: provider-neutral thresholds, explicit observation windows, one worst-case observation per leg. Estimated delays 120/45 minutes.
- `backend/app/eta.py`: single journey calculation shared by route search, shipments and manager replanning; road geometry/distance, weather, event and weekend timeline components.
- `backend/app/operations.py`: atomic local persistence for observations, events and decisions; planning revisions; single-process synchronization.
- `backend/app/shipments.py`: selected-option persistence, forced scheduling correction, stale option rejection, previous plan preserved during review.
- `backend/app/assumptions.json`: edit this one file to update the in-app Assumptions section.
- `frontend/src/combined.css`: Codex-inspired responsive visual system; original data views remain available.
- `frontend/src/components/LiveMap.tsx`: road geometry preserved even when the basemap/WebGL is unavailable.

## Honest boundaries

The dataset does not provide timed departure schedules or measured hub processing times. City coordinates, the original Heilbronn central-hub mapping, and branch transfer eligibility are assumptions. Stuttgart is a clearly documented supplementary demonstration hub. OSRM uses standard road routing, not truck-certified routing. Historical reliability is derived from spillover, not actual arrival-time accuracy. The holiday simplification is not a jurisdiction-complete legal engine. Full Sunday hold is a requested BUSINESS rule.

TomTom traffic integration requires a backend TOMTOM_API_KEY. Without a key, traffic is NOT_CONFIGURED and routing falls back to OSRM. Open-Meteo forecast weather works without a key. Scenario traffic/political closures and manually entered weather are explicitly manual/simulated. Political closures affect a facility, not an unmodelled entire road corridor. External routing needs internet; offline routes are clearly labelled approximate and return no unverified intermediate hub. No shipment is actually dispatched. Manager authorization here is a demo role, without login.

Storage is local JSON for a single backend process. Saved plans/events/weather/decisions survive restart. The ordinary activity feed is in-memory. Existing older saved shipments can be recalculated from Control room. Replanning is intentionally limited to pre-dispatch shipments. Estimates may have positive and negative trade-offs; savings are not guaranteed.

## Live map, optimization and historical comparison

- Map layers: weather, traffic flow, incidents and facilities. Click markers for source, conditions and timestamps; click alternatives to compare. Fit route, fullscreen and manual refresh are available.
- Forecast preview: planned passage, now, +3/+6/+12 hours. Preview changes only the overlay; current traffic layers are hidden for future previews.
- Planner ETAs refresh every 2 minutes while the page is active and inputs are unchanged. The selected alternative is preserved if still available. Saved plans are not silently dispatched or replaced.
- Weather samples use Open-Meteo hourly forecasts, cached for 15 minutes. Severity-to-delay rules remain prototype assumptions. Unavailable/out-of-range forecasts are labelled.
- TomTom routing uses truck dimensions, gross weight and traffic. Provider delay is included exactly once. Current incidents are sampled near the route; this is not complete corridor coverage. Predictions are not vehicle GPS tracking.
- Choose Fastest arrival, Lowest cost within deadline, or Balanced. Balanced ranks transport euros + transit hours × €50; this is a value-of-time assumption, not a billed charge. If every option misses the deadline, the UI says so.
- Save recommended saves the first-ranked route for manager review. Save plan saves the selected alternative. Saved comparison snapshots supply signed cost/time/fuel estimates against the same direct-route baseline.
- Historical costs from disposition.csv are normalized by historical loading metres, then allocated to the shipment. Unmatched routes show clearly labelled reference lanes. There are no historical arrival timestamps, so historical time savings are unavailable.

### Enable traffic

Set TOMTOM_API_KEY in the environment of the backend before starting it; for example, in your own PowerShell terminal:

```powershell
$env:TOMTOM_API_KEY = 'your-key'
powershell -File .\start.ps1
```

If the backend is already running, restart that backend process with the variable set. Keys remain on the backend; do not put them in frontend VITE variables or commit them. The key must have routing and traffic access. Account limits and external availability apply. Provider failures fall back to labelled estimates.

## Focused verification

Frontend production build passed. Four targeted backend checks passed for cost optimization/saved history comparison, counting provider traffic delay once, forecast conversion, and scenario recalculation/stale decision handling. The running browser also displayed real Open-Meteo forecast markers, real OSRM road geometry, signed route trade-offs and historical cost comparisons. Live TomTom responses could not be verified without a configured key. No broad test suite was run for this update.
