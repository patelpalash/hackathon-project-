# Transit frontend

React + TypeScript + Vite prototype connected to the existing FastAPI backend. Includes a MapLibre map, scheduled route comparison and timeline, editable React Flow network, manager incident reporting and plan decisions, source data, provider status, and demo controls.

## Run locally

From the repository root, start the backend:

```powershell
.\.venv\Scripts\python.exe -m backend.app.cli serve --host 127.0.0.1 --port 8000 --mode demo
```

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Vite proxies `/api` to port 8000. Select **Find routes** for the initial Frankfurt → Kempten comparison. Save a route, open **Disruptions & review**, and apply a traffic scenario to try the manager review workflow.

`npm run build` creates `frontend/dist`. The backend can serve the compiled frontend after restarting. No frontend API key is required. The basemap needs internet; schematic fallback remains available when map services or WebGL fail.

## Backend contract

The implemented backend differs from the original planning contract (`plan_id` instead of `id`, `handle` instead of `handling`, different provider status fields). This frontend uses the actual FastAPI contract, captured in `openapi.runtime.json`:

```powershell
# From the repository root
.\.venv\Scripts\python.exe frontend/scripts/export_contract.py
cd frontend
npm run types
```

API failures are displayed rather than replaced with fixture results. Polling compares calculation, plan and integration revisions; searches cancel obsolete requests. Manager decisions hold the reviewed snapshot and reject stale submissions. All time inputs convert from the facility timezone rather than the browser timezone.

Prototype limitations: map connections use the backend's schematic geometry; this is not turn-by-turn truck navigation. The live provider limitations in `../BACKEND_REVIEW.md` also apply. Public deployment and production authentication are outside this prototype.
