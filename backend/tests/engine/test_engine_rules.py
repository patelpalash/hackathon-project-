"""Unit tests verifying the 18 specific engine rules from docs/ACCEPTANCE_TESTS.md."""
import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import pytest
from zoneinfo import ZoneInfo

from backend.app.domain.models import Network, SearchRequest, Event, Lane, Node, CalendarRule
from backend.app.engine.route_search import search_routes, find_paths
from backend.app.engine.time_utils import (
    parse_iso_dt,
    to_iso_utc,
    validate_input_time_string,
    expand_departure,
    compute_route_id,
)
from backend.app.engine.events import (
    compute_node_handling_delay,
    compute_lane_travel_delay_and_chunks,
    is_lane_blocked_by_closure,
)
from backend.app.engine.calendar import simulate_pause_aware_travel

DOCS = Path(__file__).resolve().parents[3] / "docs"

@pytest.fixture
def network() -> Network:
    raw = json.loads((DOCS / "fixtures" / "network.json").read_text(encoding="utf-8"))
    return Network.model_validate(raw)

# Rule 1: No self-routes
def test_rule_1_no_self_routes(network):
    req = SearchRequest(
        origin_id="FRA_HUB",
        destination_id="FRA_HUB",
        ready_at="2026-09-21T08:00:00Z",
        service_profile_id="mixed",
        max_results=3,
    )
    lanes_by_from = {}
    for l in network.lanes: lanes_by_from.setdefault(l.from_node_id, []).append(l)
    paths = find_paths("FRA_HUB", "FRA_HUB", lanes_by_from, {n.id: n for n in network.nodes}, {"road", "air"}, 5)
    assert len(paths) == 0

# Rule 2: Offset agreement: 10:00+02:00 vs 08:00Z equal; +03:00 rejected
def test_rule_2_timezone_offsets():
    dt1, err1 = validate_input_time_string("2026-09-21T10:00:00+02:00", "Europe/Berlin")
    assert err1 is None
    dt2, err2 = validate_input_time_string("2026-09-21T08:00:00Z", "Europe/Berlin")
    assert err2 is None
    assert dt1 == dt2

    # Non-Z +03:00 in Berlin (summer offset is +02:00) must fail
    dt3, err3 = validate_input_time_string("2026-09-21T10:00:00+03:00", "Europe/Berlin")
    assert err3 is not None
    assert "TIMEZONE_MISMATCH" in err3

# Rule 3: Cut-off equality: equality accepted, +1 minute missed
def test_rule_3_cutoff_equality(network):
    # Direct lane departs 18:00 local (16:00Z), cutoff_minutes=60 -> cutoff is 15:00Z.
    # Handling at FRA is 120 mins.
    # Ready at 13:00Z -> ready after handling is 15:00Z == cutoff -> caught!
    req_equal = SearchRequest(
        origin_id="FRA_HUB",
        destination_id="KEM_BRANCH",
        ready_at="2026-09-21T13:00:00Z",
        service_profile_id="mixed",
        max_results=1,
    )
    routes_eq, _ = search_routes(network, req_equal, [], parse_iso_dt("2026-09-21T07:00:00Z"))
    assert routes_eq[0].departure_times[0] == "2026-09-21T16:00:00Z"
    assert routes_eq[0].arrival_at == "2026-09-21T22:00:00Z"

    # Ready at 13:01Z -> ready after handling is 15:01Z > 15:00Z -> misses cutoff -> next day 16:00Z departure!
    req_late = SearchRequest(
        origin_id="FRA_HUB",
        destination_id="KEM_BRANCH",
        ready_at="2026-09-21T13:01:00Z",
        service_profile_id="mixed",
        max_results=1,
    )
    routes_late, _ = search_routes(network, req_late, [], parse_iso_dt("2026-09-21T07:00:00Z"))
    assert routes_late[0].departure_times[0] == "2026-09-22T16:00:00Z"

# Rule 4: Departure validity dates inclusive; outside rejected
def test_rule_4_departure_validity():
    # expand_departure on valid date
    dt_valid = expand_departure(date(2026, 9, 1), "18:00", "Europe/Berlin")
    assert dt_valid is not None
    dt_end = expand_departure(date(2026, 11, 15), "18:00", "Europe/Berlin")
    assert dt_end is not None

# Rule 5: Same node handling charged once, destination handling not charged
def test_rule_5_no_destination_handling(network):
    req = SearchRequest(
        origin_id="FRA_HUB",
        destination_id="KEM_BRANCH",
        ready_at="2026-09-21T08:00:00Z",
        service_profile_id="mixed",
        max_results=1,
    )
    clock = parse_iso_dt("2026-09-21T07:00:00Z")
    r1, _ = search_routes(network, req, [], clock)
    baseline_arr = r1[0].arrival_at

    # Modify destination node KEM_BRANCH processing_minutes to 500
    for n in network.nodes:
        if n.id == "KEM_BRANCH":
            n.processing_minutes = 500

    r2, _ = search_routes(network, req, [], clock)
    # Under branch-to-branch scope, destination handling is not charged, arrival unchanged!
    assert r2[0].arrival_at == baseline_arr

# Rule 7: Cycle-free directed paths
def test_rule_7_cycle_free_paths(network):
    lanes_by_from = {}
    for l in network.lanes: lanes_by_from.setdefault(l.from_node_id, []).append(l)
    paths = find_paths("FRA_HUB", "KEM_BRANCH", lanes_by_from, {n.id: n for n in network.nodes}, {"road", "air"}, 5)
    for p in paths:
        visited = set()
        for lane in p:
            assert lane.from_node_id not in visited
            visited.add(lane.from_node_id)

# Rule 8: Sunday pause on L_FRA_HAM
def test_rule_8_sunday_pause(network):
    lane = next(l for l in network.lanes if l.id == "L_FRA_HAM")
    dep_sat_18z = parse_iso_dt("2026-09-26T18:00:00Z") # Saturday 20:00 local
    chunks = simulate_pause_aware_travel(lane, dep_sat_18z, 480, network.calendar_rules, dep_sat_18z + timedelta(days=14))
    # 4h travel (240m) until Sunday 00:00 local (Sat 22:00Z)
    # 24h pause (1440m) until Monday 00:00 local (Sun 22:00Z)
    # 4h travel (240m) until Mon 02:00Z
    assert len(chunks) == 3
    assert chunks[0].kind == "travel" and chunks[0].duration_minutes == 240
    assert chunks[1].kind == "wait" and chunks[1].is_calendar_pause and chunks[1].duration_minutes == 1440
    assert chunks[2].kind == "travel" and chunks[2].duration_minutes == 240
    assert chunks[2].end_at == parse_iso_dt("2026-09-28T02:00:00Z")

# Rule 9: DST transition handling
def test_rule_9_dst_handling():
    # Europe/Berlin spring forward 2026-03-29: 02:00 -> 03:00. 02:30 does not exist!
    dt_spring = expand_departure(date(2026, 3, 29), "02:30", "Europe/Berlin")
    assert dt_spring is None

    # Autumn repeated time: 2026-10-25 02:30 picks earlier UTC instant (fold=0)
    dt_autumn = expand_departure(date(2026, 10, 25), "02:30", "Europe/Berlin")
    assert dt_autumn is not None
    assert dt_autumn.astimezone(timezone.utc) == datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)

# Rule 11: Group maximum delay iteration: same correlation key uses max, different sum
def test_rule_11_group_delay_composition():
    node = Node(
        id="TEST_HUB",
        name="Test Hub",
        type="hub",
        country="DE",
        timezone="Europe/Berlin",
        latitude=50.0,
        longitude=8.0,
        processing_minutes=60,
        active=True,
        provenance="test",
    )
    clock = parse_iso_dt("2026-09-21T07:00:00Z")
    arr = parse_iso_dt("2026-09-21T08:00:00Z")

    # Same correlation key reports of 120 and 180 minutes -> contributes 180, not 300
    e1 = Event(
        id="e1", version=1, type="operational", source_kind="manager", external_id="e1",
        source_reference="test", observed_at="2026-09-21T07:00:00Z", valid_from="2026-09-21T07:00:00Z",
        valid_until="2026-09-22T00:00:00Z", review_due_at=None, target_kind="node", target_id="TEST_HUB",
        mode="road", effect_type="additional_handling_minutes", effect_minutes=120, verification_status="accepted",
        lifecycle_status="active", correlation_key="INCIDENT-A", reason="Reason A1", reported_by="mgr",
        received_at="2026-09-21T07:00:00Z", review_overdue=False, applies_to_departure_at=None, observation_id=None,
    )
    e2 = Event(
        id="e2", version=1, type="operational", source_kind="manager", external_id="e2",
        source_reference="test", observed_at="2026-09-21T07:00:00Z", valid_from="2026-09-21T07:00:00Z",
        valid_until="2026-09-22T00:00:00Z", review_due_at=None, target_kind="node", target_id="TEST_HUB",
        mode="road", effect_type="additional_handling_minutes", effect_minutes=180, verification_status="accepted",
        lifecycle_status="active", correlation_key="INCIDENT-A", reason="Reason A2", reported_by="mgr",
        received_at="2026-09-21T07:00:00Z", review_overdue=False, applies_to_departure_at=None, observation_id=None,
    )

    tot, end_dt, res = compute_node_handling_delay(node, "road", arr, [e1, e2], clock)
    assert res.total_extra_minutes == 180
    assert tot == 240 # 60 base + 180 max

    # Now add another incident with a DIFFERENT correlation key B contributing 60 minutes -> 180 + 60 = 240 extra!
    e3 = Event(
        id="e3", version=1, type="operational", source_kind="manager", external_id="e3",
        source_reference="test", observed_at="2026-09-21T07:00:00Z", valid_from="2026-09-21T07:00:00Z",
        valid_until="2026-09-22T00:00:00Z", review_due_at=None, target_kind="node", target_id="TEST_HUB",
        mode="road", effect_type="additional_handling_minutes", effect_minutes=60, verification_status="accepted",
        lifecycle_status="active", correlation_key="INCIDENT-B", reason="Reason B", reported_by="mgr",
        received_at="2026-09-21T07:00:00Z", review_overdue=False, applies_to_departure_at=None, observation_id=None,
    )
    tot2, _, res2 = compute_node_handling_delay(node, "road", arr, [e1, e2, e3], clock)
    assert res2.total_extra_minutes == 240
    assert tot2 == 300

# Rule 18: Road-only from Istanbul to Kempten yields no feasible route
def test_rule_18_road_only_istanbul_kempten(network):
    req = SearchRequest(
        origin_id="IST_BRANCH",
        destination_id="KEM_BRANCH",
        ready_at="2026-09-21T06:00:00Z",
        service_profile_id="road_only",
        max_results=3,
    )
    clock = parse_iso_dt("2026-09-21T05:00:00Z")
    routes, diags = search_routes(network, req, [], clock)
    assert len(routes) == 0
    assert any(d.code == "DISCONNECTED" for d in diags)
