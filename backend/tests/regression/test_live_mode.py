"""Live mode must use current dates and a server-maintained clock."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from backend.app.services.clock_service import ClockService
from backend.app.services.data_importer import seed_network_and_geometries
from backend.app.services.plan_service import PlanService
from backend.app.storage.database import create_connection
from backend.app.storage.repository import Repository
from backend.app.engine.time_utils import parse_iso_dt, to_iso_utc


def test_live_seed_and_clock_use_current_time():
    with TemporaryDirectory() as directory:
        conn = create_connection(Path(directory) / "live.db")
        try:
            seed_network_and_geometries(conn, dataset_id="live-test", mode="live")
            repo = Repository(conn)
            state = repo.get_state()
            now = datetime.now(timezone.utc)
            assert state.mode == "live"
            assert abs((now - parse_iso_dt(state.simulation_clock)).total_seconds()) < 60
            network = repo.get_network()
            nodes = {node.id: node for node in network.nodes}
            for lane in network.lanes:
                today = now.astimezone(ZoneInfo(nodes[lane.from_node_id].timezone)).date()
                assert lane.valid_from == today.isoformat()
                assert lane.valid_to == (today + timedelta(days=60)).isoformat()

            old_clock = to_iso_utc(now - timedelta(minutes=3))
            conn.execute("UPDATE app_state SET simulation_clock = ? WHERE id = 1", (old_clock,))
            conn.commit()
            updated = ClockService(repo, PlanService(repo)).advance_live_clock()
            assert updated.snapshot.clock_revision == 1
            assert parse_iso_dt(updated.simulation_clock) > parse_iso_dt(old_clock)
            assert ClockService(repo, PlanService(repo)).advance_live_clock().snapshot.clock_revision == 1
        finally:
            conn.close()
