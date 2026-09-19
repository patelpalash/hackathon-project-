"""FastAPI main application entrypoint with lifespan, CORS, and OpenAPI error envelope."""
import uuid
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..domain.models import Error, ErrorBody, ErrorDetail
from ..storage.database import get_db_path, create_connection, init_db
from ..storage.repository import Repository, ConcurrencyError
from ..services.data_importer import seed_network_and_geometries, inspect_and_import_csvs, DATA_RAW_DIR
from ..services.plan_service import PlanService
from ..services.clock_service import ClockService
from ..providers.orchestrator import ProviderOrchestrator
from .routes import router

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"

STATUS_CODE_MAP = {
    "NOT_FOUND": 404,
    "STALE_SNAPSHOT": 409,
    "STALE_PLAN": 409,
    "EVENT_VERSION_CONFLICT": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "ROUTE_INFEASIBLE": 409,
    "VALIDATION_ERROR": 422,
    "TIMEZONE_MISMATCH": 422,
    "PAST_READY_TIME": 422,
    "DEMO_PLAN_LIMIT": 422,
    "OUTSIDE_DEMO_SCOPE": 422,
    "MODE_MISMATCH": 422,
    "PROVIDER_SOURCE_RESERVED": 422,
    "SEARCH_LIMIT": 503,
    "STORAGE_UNAVAILABLE": 503,
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    mode = os.environ.get("TRANSIT_MODE", "demo").lower()
    db_path = get_db_path(mode)
    conn = create_connection(db_path)
    init_db(conn)

    # Auto seed demo network and inspect data if empty
    cur = conn.execute("SELECT id FROM app_state WHERE id = 1;")
    if not cur.fetchone():
        seed_network_and_geometries(conn, dataset_id=f"{mode}-seed-1", mode=mode)
        if DATA_RAW_DIR.exists():
            inspect_and_import_csvs(conn, DATA_RAW_DIR)

    repo = Repository(conn)
    plan_service = PlanService(repo)
    clock_service = ClockService(repo, plan_service)
    orchestrator = ProviderOrchestrator(repo)

    app.state.db_conn = conn
    app.state.repo = repo
    app.state.plan_service = plan_service
    app.state.clock_service = clock_service
    app.state.orchestrator = orchestrator

    yield

    conn.close()

app = FastAPI(
    title="Transit Planner Prototype API",
    version="2.0.0",
    description="Frozen hackathon contract. All listed object properties are required.",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception Handlers adhering to OpenAPI Error envelope
@app.exception_handler(ConcurrencyError)
async def concurrency_error_handler(request: Request, exc: ConcurrencyError):
    http_status = STATUS_CODE_MAP.get(exc.code, 400)
    trace_id = f"trace-{uuid.uuid4().hex[:8]}"
    snap = exc.current_snapshot
    if snap is None and hasattr(request.app.state, "repo"):
        try:
            snap = request.app.state.repo.get_snapshot()
        except Exception:
            pass

    body = Error(
        error=ErrorBody(
            code=exc.code,
            message=exc.message,
            details=[],
            trace_id=trace_id,
            current_snapshot=snap,
        )
    )
    return JSONResponse(status_code=http_status, content=body.model_dump())

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    trace_id = f"trace-{uuid.uuid4().hex[:8]}"
    details = []
    for err in exc.errors():
        field_str = " -> ".join(str(loc) for loc in err.get("loc", []))
        details.append(ErrorDetail(field=field_str, message=err.get("msg", "Invalid value"), code=err.get("type")))

    snap = None
    if hasattr(request.app.state, "repo"):
        try:
            snap = request.app.state.repo.get_snapshot()
        except Exception:
            pass

    body = Error(
        error=ErrorBody(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details=details,
            trace_id=trace_id,
            current_snapshot=snap,
        )
    )
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=body.model_dump())

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    trace_id = f"trace-{uuid.uuid4().hex[:8]}"
    code_str = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
    snap = None
    if hasattr(request.app.state, "repo"):
        try:
            snap = request.app.state.repo.get_snapshot()
        except Exception:
            pass

    body = Error(
        error=ErrorBody(
            code=code_str,
            message=str(exc.detail),
            details=[],
            trace_id=trace_id,
            current_snapshot=snap,
        )
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump())

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    trace_id = f"trace-{uuid.uuid4().hex[:8]}"
    snap = None
    if hasattr(request.app.state, "repo"):
        try:
            snap = request.app.state.repo.get_snapshot()
        except Exception:
            pass

    body = Error(
        error=ErrorBody(
            code="INTERNAL_ERROR",
            message="Internal server error",
            details=[],
            trace_id=trace_id,
            current_snapshot=snap,
        )
    )
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=body.model_dump())

# Include API router
app.include_router(router)

# Catch-all for undefined /api routes: return JSON 404, never fallback to index.html
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
async def api_404_catchall(request: Request, path: str):
    trace_id = f"trace-{uuid.uuid4().hex[:8]}"
    snap = None
    if hasattr(request.app.state, "repo"):
        try:
            snap = request.app.state.repo.get_snapshot()
        except Exception:
            pass

    body = Error(
        error=ErrorBody(
            code="NOT_FOUND",
            message=f"Endpoint /api/{path} not found",
            details=[],
            trace_id=trace_id,
            current_snapshot=snap,
        )
    )
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=body.model_dump())

# Minimal landing page when no compiled frontend is present
if not FRONTEND_DIST.exists():
    @app.get("/", response_class=HTMLResponse)
    async def landing_page():
        return """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Transit Planner</title>
  <style>
    body{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#0b1020;color:#eef2ff;display:grid;min-height:100vh;place-items:center}
    main{max-width:760px;padding:48px}
    h1{font-size:clamp(2.4rem,7vw,4.8rem);margin:0 0 16px}
    p{color:#b9c2dd;font-size:1.1rem;line-height:1.6}
    a{display:inline-block;margin:10px 10px 0 0;padding:12px 18px;border-radius:10px;background:#eef2ff;color:#0b1020;text-decoration:none;font-weight:700}
  </style>
</head>
<body><main>
  <h1>Transit Planner</h1>
  <p>Hackathon routing and disruption-management prototype. The FastAPI backend is live and ready for demo traffic.</p>
  <a href="/docs">Open API Docs</a><a href="/api/health">Health Check</a>
</main></body>
</html>"""

# Static frontend fallback for packaged demo
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        target_file = FRONTEND_DIST / full_path
        if target_file.is_file():
            return FileResponse(str(target_file))
        index_file = FRONTEND_DIST / "index.html"
        if index_file.is_file():
            return FileResponse(str(index_file))
        return JSONResponse(status_code=404, content={"message": "Not found"})
