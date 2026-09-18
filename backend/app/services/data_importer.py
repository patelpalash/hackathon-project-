"""Source data import and database initialization adhering to docs/BUILD_SPEC.md."""
import csv
import hashlib
import json
from pathlib import Path
from typing import Optional
import sqlite3
import pandas as pd

from ..storage.database import init_db
from ..engine.time_utils import to_iso_utc

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"
DATA_RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"

EXPECTED_ROW_COUNTS = {
    "disposition.csv": 19980,
    "relationen.csv": 30,
    "kalender.csv": 1050,
    "stoerungen.csv": 7,
    "kundenstamm.csv": 820,
    "kundensignale.csv": 72,
    "vertriebsereignisse.csv": 188,
}

def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def inspect_and_import_csvs(conn: sqlite3.Connection, source_dir: Path) -> dict:
    """Inspect all CSV files in source_dir, record findings in source_summaries and capacity_examples."""
    findings = {}

    for filename, exp_count in EXPECTED_ROW_COUNTS.items():
        file_path = source_dir / filename
        if not file_path.exists():
            # Record missing file finding
            conn.execute(
                """
                INSERT INTO source_summaries (filename, rows, date_from, date_to, issues_json, sha256)
                VALUES (?, NULL, NULL, NULL, ?, NULL)
                ON CONFLICT(filename) DO UPDATE SET
                    rows = excluded.rows,
                    date_from = excluded.date_from,
                    date_to = excluded.date_to,
                    issues_json = excluded.issues_json,
                    sha256 = excluded.sha256;
                """,
                (filename, json.dumps([f"File {filename} not found in source directory"])),
            )
            continue

        sha = compute_file_sha256(file_path)
        issues: list[str] = []

        # Parse CSV with pandas
        try:
            df = pd.read_csv(file_path, encoding="utf-8-sig")
            row_count = len(df)
            if row_count != exp_count:
                issues.append(f"Row count {row_count} differs from baseline fixture {exp_count}")

            date_from = None
            date_to = None

            # Identify date columns
            date_cols = [c for c in df.columns if "datum" in c or c in ("von", "date", "gilt_von", "vertragsbeginn")]
            if date_cols:
                primary_date = date_cols[0]
                valid_dates = pd.to_datetime(df[primary_date].dropna(), errors="coerce")
                if not valid_dates.empty:
                    date_from = valid_dates.min().strftime("%Y-%m-%d")
                    date_to = valid_dates.max().strftime("%Y-%m-%d")

            # Quality findings
            if filename == "kundenstamm.csv":
                if "top30" in df.columns:
                    top30_count = int(df["top30"].sum())
                    if top30_count != 30:
                        issues.append(f"top30 flag count is {top30_count} (expected 31 documented anomaly)")

            elif filename == "kundensignale.csv":
                if "gilt_bis" in df.columns:
                    missing_ends = int(df["gilt_bis"].isna().sum())
                    if missing_ends > 0:
                        issues.append(f"{missing_ends} signals have missing end dates (indefinite)")

            conn.execute(
                """
                INSERT INTO source_summaries (filename, rows, date_from, date_to, issues_json, sha256)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(filename) DO UPDATE SET
                    rows = excluded.rows,
                    date_from = excluded.date_from,
                    date_to = excluded.date_to,
                    issues_json = excluded.issues_json,
                    sha256 = excluded.sha256;
                """,
                (filename, row_count, date_from, date_to, json.dumps(issues), sha),
            )
            findings[filename] = {"rows": row_count, "issues": issues, "sha256": sha}

        except Exception as e:
            conn.execute(
                """
                INSERT INTO source_summaries (filename, rows, date_from, date_to, issues_json, sha256)
                VALUES (?, NULL, NULL, NULL, ?, ?)
                ON CONFLICT(filename) DO UPDATE SET
                    rows = excluded.rows,
                    date_from = excluded.date_from,
                    date_to = excluded.date_to,
                    issues_json = excluded.issues_json,
                    sha256 = excluded.sha256;
                """,
                (filename, json.dumps([f"Error parsing {filename}: {str(e)}"]), sha),
            )

    # Extract CapacityExample (Hamburg example)
    disp_path = source_dir / "disposition.csv"
    rel_path = source_dir / "relationen.csv"
    if disp_path.exists() and rel_path.exists():
        try:
            disp_df = pd.read_csv(disp_path, encoding="utf-8-sig")
            rel_df = pd.read_csv(rel_path, encoding="utf-8-sig")

            # Target: 2024-01-04 for R01
            match = disp_df[(disp_df["datum"] == "2024-01-04") & (disp_df["relation"] == "R01")]
            if not match.empty:
                row = match.iloc[0]
                rel_match = rel_df[rel_df["relation"] == "R01"]
                dest = "Hamburg"
                cap = 13.6
                if not rel_match.empty:
                    dest = str(rel_match.iloc[0]["ziel_niederlassung"])
                    cap = float(rel_match.iloc[0]["kapazitaet_ldm"])

                conn.execute("DELETE FROM capacity_examples WHERE id = 1;")
                conn.execute(
                    """
                    INSERT INTO capacity_examples (
                        id, source_file, relation, destination, date,
                        planned_trailers, needed_trailers, special_trips,
                        loading_metres, trailer_capacity_metres
                    ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        "disposition.csv",
                        "R01",
                        dest,
                        "2024-01-04",
                        int(row["trailer_geplant"]),
                        int(row["trailer_benoetigt"]),
                        int(row["sonderfahrten"]),
                        float(row["lademeter_aufkommen"]),
                        cap,
                    ),
                )
        except Exception as e:
            print(f"Warning: could not extract capacity example: {e}")

    conn.commit()
    return findings

def seed_network_and_geometries(
    conn: sqlite3.Connection,
    dataset_id: str = "seed-demo-1",
    simulation_clock: str = "2026-09-21T07:00:00Z",
    mode: str = "demo",
    force_reset: bool = False,
):
    """Seed initial network nodes, lanes, calendar rules, service profiles, and map geometries."""
    init_db(conn)

    # Check if app_state exists
    cur = conn.execute("SELECT id FROM app_state WHERE id = 1;")
    if cur.fetchone() and not force_reset:
        return

    # Clear operational tables on reset
    conn.execute("DELETE FROM app_state;")
    conn.execute("DELETE FROM nodes;")
    conn.execute("DELETE FROM lanes;")
    conn.execute("DELETE FROM calendar_rules;")
    conn.execute("DELETE FROM service_profiles;")
    conn.execute("DELETE FROM event_versions;")
    conn.execute("DELETE FROM searches;")
    conn.execute("DELETE FROM plans;")
    conn.execute("DELETE FROM decisions;")
    conn.execute("DELETE FROM lane_geometries;")
    conn.execute("DELETE FROM mutation_receipts;")

    # Initialize app_state
    conn.execute(
        """
        INSERT INTO app_state (
            id, dataset_id, schedule_revision, event_revision, clock_revision,
            plans_revision, integrations_revision, simulation_clock, mode
        ) VALUES (1, ?, 1, 0, 0, 0, 0, ?, ?);
        """,
        (dataset_id, simulation_clock, mode),
    )

    # Load network fixture
    net_path = DOCS_DIR / "fixtures" / "network.json"
    if net_path.exists():
        raw_net = json.loads(net_path.read_text(encoding="utf-8"))

        for node in raw_net["nodes"]:
            conn.execute(
                """
                INSERT INTO nodes (
                    id, name, type, country, timezone, latitude, longitude,
                    processing_minutes, active, provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    node["id"],
                    node["name"],
                    node["type"],
                    node["country"],
                    node["timezone"],
                    node["latitude"],
                    node["longitude"],
                    node["processing_minutes"],
                    1 if node["active"] else 0,
                    node["provenance"],
                ),
            )

        for lane in raw_net["lanes"]:
            deps_json = json.dumps(lane["departures"])
            conn.execute(
                """
                INSERT INTO lanes (
                    id, from_node_id, to_node_id, mode, duration_minutes,
                    active, valid_from, valid_to, departures_json, provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    lane["id"],
                    lane["from_node_id"],
                    lane["to_node_id"],
                    lane["mode"],
                    lane["duration_minutes"],
                    1 if lane["active"] else 0,
                    lane["valid_from"],
                    lane["valid_to"],
                    deps_json,
                    lane["provenance"],
                ),
            )

        for rule in raw_net["calendar_rules"]:
            conn.execute(
                """
                INSERT INTO calendar_rules (
                    id, lane_id, mode, timezone, weekday,
                    start_local_time, end_next_day_local_time, action, provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    rule["id"],
                    rule["lane_id"],
                    rule["mode"],
                    rule["timezone"],
                    rule["weekday"],
                    rule["start_local_time"],
                    rule["end_next_day_local_time"],
                    rule["action"],
                    rule["provenance"],
                ),
            )

        for prof in raw_net["service_profiles"]:
            conn.execute(
                """
                INSERT INTO service_profiles (id, allowed_modes_json, max_lanes, scope)
                VALUES (?, ?, ?, ?);
                """,
                (prof["id"], json.dumps(prof["allowed_modes"]), prof["max_lanes"], prof["scope"]),
            )

    # Load map geometry fixture
    geom_path = DOCS_DIR / "fixtures" / "map-geometry.json"
    if geom_path.exists():
        raw_geom = json.loads(geom_path.read_text(encoding="utf-8"))
        for lg in raw_geom["lanes"]:
            conn.execute(
                """
                INSERT INTO lane_geometries (
                    lane_id, departure_at, geometry_kind, coordinates_json,
                    source, attribution, fetched_at, stale
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    lg["lane_id"],
                    lg["departure_at"],
                    lg["geometry_kind"],
                    json.dumps(lg["geometry"]),
                    lg["source"],
                    lg["attribution"],
                    lg["fetched_at"],
                    1 if lg["stale"] else 0,
                ),
            )

    conn.commit()
