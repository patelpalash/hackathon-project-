# Transit Planner — Prototype Backend (v2.0.0)

A logistics transit routing and disruption management backend adhering to the Transit Planner 2.0.0 specification. Combines core scheduled graph search, fixed-point event delay iteration, calendar-aware pauses, origin progress management, SQLite persistence, and external provider adapters (Open-Meteo, TomTom, Operator Bulletins).

---

## Capabilities & Architecture

- **Branch-to-Branch Routing**:
  - Pure arithmetic scheduled routing: origin handling, scheduled transit, connection waiting, and transfer limits ($\le 5$ lanes).
  - Cycle-free path enumeration with 14-day search horizon.
  - Cutoff enforcement: `ready_after_handling <= departure - cutoff_minutes`.
  - Pause-aware travel algorithm handling recurring calendar pauses (e.g. Sunday road pause on `L_FRA_HAM`).
  - Strict tie-breaking and canonical JSON SHA-256 route ID generation.
- **Disruption & Incident Engine**:
  - Monotonic fixed-point iteration for additive delays with correlation-key grouping (`max` within incident group, `sum` across different groups).
  - Scoped handling delays (`additional_handling_minutes`) and travel delays (`additional_travel_minutes`).
  - Active lane closures and departure cancellations.
- **Manager Decisions & Saved Plans**:
  - Saved transport plans with automatic projection updates on schedule, event, or clock changes.
  - Review triggers: infeasible selected itinerary, deadline breach, or an alternative arriving $\ge 30$ minutes earlier.
  - Manager actions (`accept_route`, `keep_selected`, `defer`) with immutable `ReviewEvidence` audit records.
  - Section 10 `OriginProgress` handling: materializes frozen origin timeline prefix on clock advance; protects already-booked departures while forbidding past cutoffs for new bookings; transitions to `outside_demo_scope` upon departure.
- **Provider Adapters (Antigravity)**:
  - **Open-Meteo**: Endpoint forecast queries, normalized observations with raw digests; default `advisory_only`, configurable `demo_thresholds`.
  - **TomTom**: Commercial truck routing via Calculate Route API, `trafficDelayInSeconds` conversion, geometry extraction, truthful `not_configured` when API key is missing.
  - **Operator Bulletins**: JSON feed parser with server-side trust validation.
  - **Provider Orchestrator**: Request budget enforcement (max 20 per cycle, concurrency 3, 8s timeout).
- **Persistence & Wire Contract**:
  - SQLite with WAL mode, foreign keys, and atomic snapshot verification.
  - Strict idempotency receipts for mutations.
  - 100% compliance with `docs/contracts/openapi.json` and uniform `Error` envelopes.

---

## Quick Start (Windows PowerShell)

### 1. Prerequisites
- Python 3.11+ (Python 3.13 tested)
- Git

### 2. Environment Setup
```powershell
# Create virtual environment
py -m venv .venv

# Activate and install dependencies
.\.venv\Scripts\pip install -e .
# Or directly install requirements:
.\.venv\Scripts\pip install fastapi "uvicorn[standard]" pydantic pandas httpx jsonschema tzdata pytest pytest-asyncio
```

### 3. Initialize Database and Import CSVs
```powershell
.\.venv\Scripts\python -m backend.app.cli init --source-dir data/raw --mode demo
```

### 4. Run the Server
```powershell
# Option A: One-click launcher
.\scripts\start-demo.ps1

# Option B: Direct CLI
.\.venv\Scripts\python -m backend.app.cli serve --host 127.0.0.1 --port 8000 --mode demo
```
API is accessible at: `http://127.0.0.1:8000/api`
Interactive Swagger Docs: `http://127.0.0.1:8000/docs`

---

## Running Tests

All 28 automated tests verify pure routing scenarios (S0–S7), engine rules, provider adapters, and audit regressions (F1–F6):

```powershell
# Run complete test suite
.\.venv\Scripts\pytest backend/tests/ -v

# Run specification validator
.\.venv\Scripts\python docs/tools/validate_spec.py
```

---

## Project Structure

```
backend/
├── app/
│   ├── api/          # FastAPI routers, lifespan, error envelopes
│   ├── contracts/    # provider_protocol.py
│   ├── domain/       # Pydantic models matching openapi.json schemas
│   ├── engine/       # Pure Python routing, time, calendar, and event math
│   ├── providers/    # Open-Meteo, TomTom, Operator Bulletins, Orchestrator
│   ├── services/     # Plan service, clock service, data importer
│   └── storage/      # SQLite connection, schema, transactional repository
└── tests/
    ├── api/          # End-to-end API contract tests
    ├── engine/       # Acceptance scenarios S0-S7 & engine rule tests
    ├── providers/    # Provider mock & failure mode tests
    └── regression/   # Audit findings F1-F6 regression tests
```
