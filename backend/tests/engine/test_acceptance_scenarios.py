"""Acceptance tests verifying scenarios S0-S7 from docs/fixtures/acceptance.json."""
import json
from pathlib import Path
import pytest
from datetime import datetime

from backend.app.domain.models import Network, SearchRequest, Event
from backend.app.engine.route_search import search_routes
from backend.app.engine.time_utils import parse_iso_dt

DOCS = Path(__file__).resolve().parents[3] / "docs"

@pytest.fixture
def base_network() -> Network:
    raw = json.loads((DOCS / "fixtures" / "network.json").read_text(encoding="utf-8"))
    return Network.model_validate(raw)

@pytest.fixture
def presets() -> dict[str, Event]:
    raw = json.loads((DOCS / "fixtures" / "presets.json").read_text(encoding="utf-8"))
    return {v["id"]: Event.model_validate(v) for v in raw.values()}

@pytest.fixture
def acceptance_cases() -> list[dict]:
    raw = json.loads((DOCS / "fixtures" / "acceptance.json").read_text(encoding="utf-8"))
    return raw["cases"]

def test_acceptance_scenarios(base_network, presets, acceptance_cases):
    for case in acceptance_cases:
        case_id = case["id"]
        clock_utc = parse_iso_dt(case["simulation_clock"])
        req = SearchRequest.model_validate(case["request"])
        
        # Load named events
        case_events = [presets[eid] for eid in case["event_ids"]]

        routes, diagnostics = search_routes(
            network=base_network,
            request=req,
            events=case_events,
            evaluation_clock_utc=clock_utc,
        )

        expected_routes = case["expected_routes"]
        assert len(routes) == len(expected_routes), f"Case {case_id}: expected {len(expected_routes)} routes, got {len(routes)}"

        for i, (actual, expected) in enumerate(zip(routes, expected_routes)):
            assert actual.lane_ids == expected["lane_ids"], (
                f"Case {case_id} route {i}: expected lanes {expected['lane_ids']}, got {actual.lane_ids}"
            )
            assert actual.arrival_at == expected["arrival_at"], (
                f"Case {case_id} route {i}: expected arrival {expected['arrival_at']}, got {actual.arrival_at}"
            )
            assert actual.total_minutes == expected["total_minutes"], (
                f"Case {case_id} route {i}: expected total_minutes {expected['total_minutes']}, got {actual.total_minutes}"
            )

            # Check segment continuity and sum of durations
            cursor = parse_iso_dt(req.ready_at)
            sum_durations = 0
            for seg in actual.segments:
                assert parse_iso_dt(seg.start_at) == cursor, f"Case {case_id} route {i}: gap in segment start"
                end = parse_iso_dt(seg.end_at)
                assert seg.duration_minutes > 0
                assert sum(r.minutes for r in seg.reasons) == seg.duration_minutes, (
                    f"Case {case_id} route {i}: reason sum mismatch in segment {seg.segment_index}"
                )
                cursor = end
                sum_durations += seg.duration_minutes

            assert sum_durations == actual.total_minutes
            assert cursor == parse_iso_dt(actual.arrival_at)
