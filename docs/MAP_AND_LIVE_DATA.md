# Map and live-data specification, version 2.0.0

## Included integrations and their boundaries

| Purpose | Selected technology | Configuration |
|---|---|---|
| Main geographic map | MapLibre GL JS, npm package maplibre-gl | Bundled with frontend; not an ETA engine |
| Online basemap | OpenFreeMap Liberty | https://tiles.openfreemap.org/styles/liberty; keep its attribution visible |
| Weather observations/forecasts | Open-Meteo forecast endpoint | Server-side adapter; endpoint/account must match permitted use |
| Road geometry and traffic delay | TomTom Calculate Route | Server-side TOMTOM_API_KEY; never a VITE_ variable |
| Border, strike and political/administrative notices | Operator bulletin adapter + manager report | Optional allowlisted JSON feed; no unsupported automatic inference from news headlines |

Official references checked during this update: [MapLibre](https://maplibre.org/maplibre-gl-js/docs/), [OpenFreeMap quick start](https://openfreemap.org/quick_start/), [Open-Meteo](https://open-meteo.com/en/docs), [Open-Meteo usage options](https://open-meteo.com/en/pricing), [TomTom Calculate Route](https://docs.tomtom.com/routing-api/documentation/tomtom-maps/v1/calculate-route). These references establish capabilities and input/output meanings. Poll intervals, delay rules and all seed timings below are our proposed prototype choices.

MapLibre renders geometry and tiles. It does not supply traffic or compute logistics schedules. TomTom road alternatives do not create a new carrier departure. The engine still chooses only the modeled scheduled lanes. Coordinates are approximate demo facility locations, not verified depot entrances; show that provenance.

## Map behavior (Claude)

Mount a single MapLibre instance in a component with an explicit nonzero container height. Install/import its CSS and bundle its worker using the chosen version's documented Vite recipe; test the production build, not only dev mode. Remove map/listeners on unmount and avoid a new map per React render. Pin the tested version. Use a ResizeObserver for drawer/layout changes.

GeoJSON always uses [longitude, latitude] in EPSG:4326. Use GET /api/map/geometry for LaneGeometry records; each geometry is tagged schematic or provider_road. Demo straight connections and air legs are dashed and labeled schematic. Real road geometry is used only when the provider returned it for the mapped lane. Never bend invented points around roads and label them actual navigation.

Render facility markers by node type, selected lane sequence in blue, available alternatives in neutral lines and disrupted targets in amber/red. Popups show lane/node name, selected ETA context, provenance, observation time and freshness. A lane-scoped incident is a corridor highlight, not a pin claiming the exact location of an accident. A node-scoped incident can use the node coordinates. Link map selection, route cards and timeline through stable IDs. fitBounds on first result/explicit Fit route, not every polling refresh. Clicks on alternate geometry select the matching route card without changing a saved plan.

Keep attribution visible; provider road data also carries the attribution returned in LaneGeometry. Do not use public demo tiles as a production availability guarantee. If style/tiles fail, use a bundled background-only MapLibre style with local markers/lines and an explicit "Basemap unavailable; schematic coordinates" label. If WebGL is unavailable, fall back to the existing React Flow schematic. Continue form/timeline/API operation. Do not bulk-download tiles to implement this fallback. Printed maps must preserve attribution; if rendering unavailable, print the itinerary/timeline instead.

## Demo and live modes

Mode is chosen when launching the backend: TRANSIT_MODE=demo or live. Use separate data/runtime/transit-demo.db and transit-live.db by default, distinct dataset IDs and no cross-mode event copy. The frontend reads State.mode and displays it prominently. Changing mode requires restarting against the other database; v2 has no hidden in-place conversion of saved plans.

Demo mode is the repeatable September fixture clock. Provider adapters are disabled, presets work, and synthetic event provenance is mandatory. Online basemap tiles may still load but do not imply live operational data.

Live mode advances evaluation time from wall clock rounded down to whole minutes through a single server worker, never through GET requests. Sample recurring schedules are initialized for local today through today+60 days and labeled "sample schedules with live conditions". Do not imply they are current carrier services. User times use the live date. Demo clock/preset endpoints return 422 MODE_MISMATCH. Demo reset requires demo mode; live database reset is an explicit local CLI maintenance operation, not a judge button.

Live provider failures do not activate demo presets. Results show which inputs are live, stale, assumed or missing. Missing TomTom key gives not_configured; weather is handled according to the configured endpoint. External services need internet; core demo and fallback visualization remain usable offline. Do not claim a live integration was verified merely because its stub works.

## Provider orchestration (Codex + Antigravity)

Codex owns the scheduler, storage/revision transactions and normalization acceptance. Antigravity owns provider adapters and their isolated tests. Their Python interface is frozen in contracts/provider_protocol.py. Adapters return observations, proposed normalized events and geometry without writing the database. They do not import the routing engine or serve HTTP endpoints. Codex validates all returned records against the wire schema and scoped policies before committing.

Poll weather every 15 minutes, traffic every 5 minutes and configured operator bulletins every 10 minutes. Poll only the nine nodes and the next two scheduled road departures per lane within 24 hours; cap traffic requests at 20 per cycle and concurrency at 3. These are configurable request budgets, not provider service guarantees. Deduplicate targets across saved plans. No provider request is allowed in the route-search inner loop.

Network fetches happen outside database transactions. Use an eight-second request timeout, bounded retries (at most two, honoring Retry-After), redacted logs and backoff on 429/5xx. A failed provider returns an explicit status; retain last observation with stale labels. Stale transport estimates are not fresh evidence. A late batch must be discarded if dataset or relevant lane configuration changed during fetch; do not overwrite a manager edit with data computed for old endpoints.

Observation IDs are deterministic hashes of provider, target, departure, effective time and normalized values; identical polls are no-ops. Only operationally changed normalized effects increment event_revision; provider health/fetch metadata changes increment integrations_revision. Every changed plan increments its plan_revision; one transaction changing any plan increments plans_revision once.

Store provider observations with fetched_at, observed_at, source URL, raw-response digest, units, intended departure and validity. Do not retain/redistribute full provider payloads beyond what configured usage permits. Demo provider fixtures are authored synthetic responses, not unlicensed captures. A provider fetch URL is allowlisted configuration, never a free-form URL submitted by a map popup.

## Traffic normalization

Call TomTom Calculate Route for the configured road-lane endpoints/approved via points and its exact planned departure. Use the documented traffic-enabled option and request extra travel-time fields when supported. Select truck mode with documented representative vehicle settings, explicitly marked assumptions. Geometries returned from a road service remain advisory and do not establish complete truck compliance.

The adapter reads summary.trafficDelayInSeconds, a delay relative to free-flow according to the provider's traffic information; convert to additional minutes with ceil(max(0, seconds)/60). Do not use a closest-road-point Flow Segment sample as if it were the whole lane. Missing/nonfinite fields do not become zero.

For this prototype, lane.duration_minutes is explicitly the nominal movement baseline excluding dynamic traffic. This is a modeling assumption, not a calibration from the supplied CSVs. The provider's total travel time is shown separately in Observation.metrics; it is not added to our full baseline. Explain any discrepancy between the carrier-style assumed duration and the provider road estimate. This avoids accidentally adding the entire travel time twice.

Create an accepted provider additional_travel_minutes event with applies_to_departure_at equal to the requested occurrence, observation_id set and valid_from equal to departure. valid_until covers that occurrence's anticipated traversal plus 24 hours; the exact-departure selector prevents it affecting another day's service. review_due_at is fetched_at +15 minutes. After it becomes overdue, retain the effect with an explicit stale-estimate warning until corrected/withdrawn; never call it live. Do not infer a closure from a generic HTTP error or empty result. Confirmed closures need explicitly scoped bulletin/manager evidence.

Correlate all dynamic road-condition penalties for the same lane/occurrence as road-conditions:<lane-id>:<departure-UTC>. Weather policy and traffic penalties use max within that group, not sum, to reduce double counting. Distinct confirmed additional operations such as border handling can use an explicitly different group. This max policy is a transparent prototype approximation, not a claim to isolate causal delays precisely.

## Weather normalization

Fetch hourly precipitation, snowfall, wind_gusts_10m and weather_code for the mapped lane endpoint locations; request UTC and retain returned units. Evaluate only forecast hours overlapping the planned lane traversal and only within the returned forecast horizon. Endpoint samples are incomplete corridor coverage: label them as such and never describe them as an exact weather measurement along every road segment.

Automatically produce an advisory when an endpoint/hour has heavy precipitation or high gusts. An optional explicit WEATHER_DELAY_POLICY=demo_thresholds adds an assumed extra 30 minutes for hourly precipitation >=10 mm or 45 minutes for gusts >=80 km/h; take the maximum, not their sum. The default policy is advisory_only until the team deliberately enables the documented demo thresholds. This is a user-visible assumption, not a validated weather-to-delay model. Snowfall creates an advisory/review item rather than an invented automatic closure.

When the delay policy is enabled, accepted events use the same road-conditions correlation key as traffic, an exact departure selector, and a reason stating the observation plus the assumption that converted it into minutes. Otherwise return observations only, with map warnings and no ETA penalty. A manager may add a structured confirmed delay/closure. Record the policy/version in reason and source_reference. Expired/out-of-horizon forecasts show unavailable rather than zero risk.

## Political/administrative inputs

Provide a documented operator JSON feed envelope (fixtures/operator-bulletin.json). Each record specifies external ID, source reference, observed time, target lane, validity, effect and reason. An allowlisted feed can be polled automatically; unverified reports enter pending review. A trusted=true claim inside remote content is ignored: trust is server configuration. An accepted operator closure applies automatically and reroutes affected plans, while changing the selected dispatch plan still requires the manager.

No general-purpose political-news API is promised. News text is not converted into country risk scores or automatic lane closures. If no operator feed is configured, status=disabled and manager reporting remains available; do not pretend this is live political monitoring.

## API additions and ownership

GET /api/integrations returns statuses; GET /api/integrations/observations returns at most 100 latest normalized records sorted deterministically; GET /api/map/geometry returns one schematic/default geometry per lane plus any cached occurrence-specific provider geometry. The UI selects the exact occurrence geometry when available, otherwise the lane default.

POST /api/integrations/refresh is a manual retry in live mode, not the only way polling occurs. It validates expected_snapshot at dispatch. Fetch outside the write transaction, then reject with 409 if dataset/schedule changed; clock-only advancement is handled by committing against the latest clock and returning the resulting snapshot. New provider events get current observation/receipt provenance and cannot be injected via ordinary manager POST /api/events with source_kind=provider. Those writes are adapter-internal only.

## Required verification

Validate [lon,lat] order; map cleanup under React StrictMode; production worker loading; coordinate/selection consistency; attribution; tile outage and WebGL fallback. Adapter tests cover normal response, missing field, timeout, invalid units, 429, stale observation, repeated response deduplication, and absence of a key. Compare raw seconds against displayed minutes. Prove provider observations cannot contaminate demo fixtures, traffic/weather same-group effects are not summed, and all live failures remain visible. Run a real provider smoke test only when configured and report whether it actually succeeded.
