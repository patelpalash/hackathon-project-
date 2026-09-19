"""SQLite database connection and schema setup adhering to docs/BUILD_SPEC.md."""
import sqlite3
from pathlib import Path
import os
from contextlib import contextmanager

DEFAULT_DEMO_DB = Path(__file__).resolve().parents[3] / "data" / "runtime" / "transit-demo.db"
DEFAULT_LIVE_DB = Path(__file__).resolve().parents[3] / "data" / "runtime" / "transit-live.db"

def get_db_path(mode: str = "demo") -> Path:
    override = os.environ.get("TRANSIT_DB_PATH")
    if override:
        p = Path(override)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    target = DEFAULT_LIVE_DB if mode == "live" else DEFAULT_DEMO_DB
    target.parent.mkdir(parents=True, exist_ok=True)
    return target

def create_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    dataset_id TEXT NOT NULL,
    schedule_revision INTEGER NOT NULL DEFAULT 1,
    event_revision INTEGER NOT NULL DEFAULT 0,
    clock_revision INTEGER NOT NULL DEFAULT 0,
    plans_revision INTEGER NOT NULL DEFAULT 0,
    integrations_revision INTEGER NOT NULL DEFAULT 0,
    simulation_clock TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('demo', 'live'))
);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    country TEXT NOT NULL,
    timezone TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    processing_minutes INTEGER NOT NULL,
    active INTEGER NOT NULL,
    provenance TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lanes (
    id TEXT PRIMARY KEY,
    from_node_id TEXT NOT NULL,
    to_node_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    active INTEGER NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT NOT NULL,
    departures_json TEXT NOT NULL,
    provenance TEXT NOT NULL,
    FOREIGN KEY(from_node_id) REFERENCES nodes(id),
    FOREIGN KEY(to_node_id) REFERENCES nodes(id)
);

CREATE TABLE IF NOT EXISTS calendar_rules (
    id TEXT PRIMARY KEY,
    lane_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    timezone TEXT NOT NULL,
    weekday INTEGER NOT NULL,
    start_local_time TEXT NOT NULL,
    end_next_day_local_time TEXT NOT NULL,
    action TEXT NOT NULL,
    provenance TEXT NOT NULL,
    FOREIGN KEY(lane_id) REFERENCES lanes(id)
);

CREATE TABLE IF NOT EXISTS service_profiles (
    id TEXT PRIMARY KEY,
    allowed_modes_json TEXT NOT NULL,
    max_lanes INTEGER NOT NULL,
    scope TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_versions (
    event_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    type TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    review_due_at TEXT,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    effect_type TEXT NOT NULL,
    effect_minutes INTEGER,
    verification_status TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL,
    correlation_key TEXT NOT NULL,
    reason TEXT NOT NULL,
    reported_by TEXT NOT NULL,
    received_at TEXT NOT NULL,
    review_overdue INTEGER NOT NULL,
    applies_to_departure_at TEXT,
    observation_id TEXT,
    PRIMARY KEY (event_id, version)
);

CREATE TABLE IF NOT EXISTS searches (
    search_id TEXT PRIMARY KEY,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    plan_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    request_json TEXT NOT NULL,
    selected_itinerary_json TEXT NOT NULL,
    selected_projection_json TEXT,
    alternative_recommendations_json TEXT NOT NULL,
    decisions_count INTEGER NOT NULL DEFAULT 0,
    latest_decision_json TEXT,
    plan_revision INTEGER NOT NULL DEFAULT 0,
    review_reasons_json TEXT NOT NULL,
    origin_progress_json TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    selected_route_id TEXT,
    superseded_route_id TEXT,
    decided_at TEXT NOT NULL,
    review_evidence_json TEXT NOT NULL,
    FOREIGN KEY(plan_id) REFERENCES plans(plan_id)
);

CREATE TABLE IF NOT EXISTS provider_observations (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    intended_departure_at TEXT,
    observed_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    metrics_json TEXT NOT NULL,
    raw_digest TEXT NOT NULL,
    attribution TEXT NOT NULL,
    stale INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_statuses (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    last_poll_at TEXT,
    last_successful_poll_at TEXT,
    consecutive_errors INTEGER NOT NULL,
    error_message TEXT,
    mode TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lane_geometries (
    lane_id TEXT NOT NULL,
    departure_at TEXT,
    geometry_kind TEXT NOT NULL,
    coordinates_json TEXT NOT NULL,
    source TEXT NOT NULL,
    attribution TEXT NOT NULL,
    fetched_at TEXT,
    stale INTEGER NOT NULL,
    PRIMARY KEY (lane_id, departure_at)
);

CREATE TABLE IF NOT EXISTS mutation_receipts (
    mutation_id TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_summaries (
    filename TEXT PRIMARY KEY,
    rows INTEGER,
    date_from TEXT,
    date_to TEXT,
    issues_json TEXT NOT NULL,
    sha256 TEXT
);

CREATE TABLE IF NOT EXISTS capacity_examples (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    source_file TEXT NOT NULL,
    relation TEXT NOT NULL,
    destination TEXT NOT NULL,
    date TEXT NOT NULL,
    planned_trailers INTEGER NOT NULL,
    needed_trailers INTEGER NOT NULL,
    special_trips INTEGER NOT NULL,
    loading_metres REAL NOT NULL,
    trailer_capacity_metres REAL NOT NULL
);
"""

def init_db(conn: sqlite3.Connection):
    """Execute SQLite schema."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()
