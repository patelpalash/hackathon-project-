# Version-2 audit resolution register

These are specification corrections, not claims that application code is implemented or tested. The original version-1 ZIP is preserved. All six findings have explicit contract/rule changes and required regression cases in this pack.

| Finding | Change | Required verification |
|---|---|---|
| F1: invisible plan decisions across sessions | State.plans_revision outside calculation Snapshot; UI refresh compares it | Create and decide in tab A; tab B refreshes without a lane/event/clock change |
| F2: clock invalidates saved request | OriginProgress, internal recomputation, frozen prefix, separate booking cut-off policy and exact departure boundary | 08Z ready -> 09Z evaluation leaves baseline ETA unchanged; no past new booking; outside scope at 16Z |
| F3: stronger report in same group ignored | Iterate group-to-maximum mapping values and interval to stability | 08-09 base +60 then same-group +180 at09:30 finishes12:00 |
| F4: inactive intermediate hub | Every node/edge active; saved invalid endpoint gives business blocked state | Disabling Munich removes its route and affects saved projection |
| F5: capacity card lacks API | Typed nullable CapacityExample inside DataSummary | Imported example changes update the card; missing example is unavailable |
| F6: insufficient approval evidence | Immutable ReviewEvidence inside Decision plus stored snapshot | Later time/event edits cannot change earlier approved ETA/timeline |
| G1: map absent | Required MapLibre/OpenFreeMap view, typed geometry, fallback, attribution and map tests | Production map works online and core demo works after tile/WebGL failure |
| G2: live ingestion absent | Open-Meteo/TomTom/operator adapters and protocol; source/status/observation APIs; isolated live mode | No-key state, actual configured fetch, stale/error paths and no contamination of demo |
| G3: scope/time risk | Dependency gates; early complete workflow; explicit provider credentials and remaining limitations | Merge/test each gate; report unfinished work rather than claiming a full product |

Live traffic depends on a configured key and network. Weather-to-delay conversion remains an explicit illustrative policy, not a learned or validated ETA model. Political/administrative automation needs a configured trusted operator feed; a generic news-to-closure inference is deliberately excluded. These boundaries are visible in the UI and do not disappear because a map is present.
