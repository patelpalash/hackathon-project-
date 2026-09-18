"""Pytest configuration and shared test fixtures."""
import os
import tempfile
from pathlib import Path
import pytest
import pytest_asyncio
import httpx

from backend.app.storage.database import create_connection, init_db
from backend.app.storage.repository import Repository
from backend.app.services.data_importer import seed_network_and_geometries, inspect_and_import_csvs, DATA_RAW_DIR
from backend.app.services.plan_service import PlanService
from backend.app.services.clock_service import ClockService
from backend.app.providers.orchestrator import ProviderOrchestrator
from backend.app.api.main import app

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = create_connection(Path(path))
    seed_network_and_geometries(conn, dataset_id="test-dataset-1", mode="demo", force_reset=True)
    if DATA_RAW_DIR.exists():
        inspect_and_import_csvs(conn, DATA_RAW_DIR)
    repo = Repository(conn)
    plan_service = PlanService(repo)
    clock_service = ClockService(repo, plan_service)
    orchestrator = ProviderOrchestrator(repo)

    yield {
        "conn": conn,
        "repo": repo,
        "plan_service": plan_service,
        "clock_service": clock_service,
        "orchestrator": orchestrator,
    }

    conn.close()
    try:
        os.remove(path)
    except Exception:
        pass

@pytest_asyncio.fixture
async def api_client(temp_db):
    app.state.db_conn = temp_db["conn"]
    app.state.repo = temp_db["repo"]
    app.state.plan_service = temp_db["plan_service"]
    app.state.clock_service = temp_db["clock_service"]
    app.state.orchestrator = temp_db["orchestrator"]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
