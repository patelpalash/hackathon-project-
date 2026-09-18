# Transit Planner — updated implementation plan 2.0.0

Start with docs/START_HERE.md. This document and the version-2 pack replace tentative decisions in the original plan. The original ZIP remains archived separately. This pack is ready for implementation; it is not the implemented GUI.

## Goal

Calculate plausible transport arrival times through scheduled connections, explain travel/handling/waiting and compare feasible alternatives. Include weather/traffic and concrete political/operational disruptions, automatic recalculation, and manager review of changes to a saved transport plan.

Initial scope is branch-to-branch. Pickup and final consignee delivery, in-transit GPS rerouting and full legal/driver compliance are not implemented by this prototype. The supplied brief permits mock routes and sample rules. Its 48h versus70h example explains the problem but is not the expected answer for our separate numerical fixtures.

## Technology and people

Claude builds React/TypeScript/Vite frontend, MapLibre geographic map with OpenFreeMap and React Flow schedule management. Codex builds FastAPI/Pydantic/Python scheduling, SQLite, events, manager decisions and repository integration. Antigravity builds provider adapters and independent backend regressions in separate owned folders. MERGE_GUIDE.md prevents simultaneous writes and defines branch/merge order.

Live adapters: Open-Meteo weather; TomTom road traffic/geometry with a server-side key; optional operator bulletin feed and manager reports for verified closures/strikes. MapLibre itself does not calculate traffic. Weather-to-delay thresholds are explicit illustrative assumptions; the default is an advisory. No generic political-news penalty is invented. Demo and live datasets stay separate.

## Supplied data

| CSV | Rows | Use |
|---|---:|---|
| disposition.csv | 19,980 | Daily trailer/volume context, 2024-01-02 through2026-08-31 |
| relationen.csv | 30 | Destinations, distances and capacity/cost context |
| kalender.csv | 1,050 | Local calendar context, not a universal operating calendar |
| stoerungen.csv | 7 | Historical volume disruptions; percentages are not time delays |
| kundenstamm.csv | 820 | Customer context |
| kundensignale.csv | 72 | Customer announcements |
| vertriebsereignisse.csv | 188 | Sales/customer events |

These files do not supply route departure schedules or actual shipment arrival histories. Nine locations and ten directed connections are explicitly synthetic fixtures, with up to three feasible alternatives. Preserve source inputs; never manufacture an ETA training dataset from trailer counts. The typed source-example endpoint shows the Hamburg capacity example from its imported record.

## Build sequence

Shared contracts -> one real browser/API search -> complete routing and MapLibre -> automatic disruption and human review -> live adapter integration -> clean merge and final verification. WORK_PACKAGES.md and three prompts define exact ownership. Original source files are included for private team handoff; no API keys are included.

## Corrections included

Independent plan-change refresh; correct pre-dispatch clock progression; delay-group convergence; inactive intermediate-node handling; structured capacity example; immutable evidence of manager approvals. See AUDIT_RESOLUTIONS.md and acceptance tests. These are specified corrections; implementation tests must still prove the resulting application behavior.
