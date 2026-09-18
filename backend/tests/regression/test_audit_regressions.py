"""Audit regression test suite verifying findings F1-F6 and Section 10 counterexamples."""
import json
from datetime import datetime, timedelta
import pytest

from backend.app.domain.models import SearchRequest, Event, Node
from backend.app.storage.repository import Repository
from backend.app.services.plan_service import PlanService
from backend.app.services.clock_service import ClockService
from backend.app.engine.time_utils import parse_iso_dt, to_iso_utc
from backend.app.engine.events import compute_node_handling_delay

def test_f1_plans_revision_independent_of_calculation_snapshot(temp_db):
    repo: Repository = temp_db["repo"]
    plan_service: PlanService = temp_db["plan_service"]

    # Initial snapshot
    snap0 = repo.get_snapshot()
    state0 = repo.get_state()
    assert state0.plans_revision == 0

    # Search and create plan
    req = SearchRequest(
        origin_id="FRA_HUB",
        destination_id="KEM_BRANCH",
        ready_at="2026-09-21T08:00:00Z",
        service_profile_id="mixed",
        max_results=3,
    )
    from backend.app.engine.route_search import search_routes
    routes, _ = search_routes(repo.get_network(), req, repo.get_events(), parse_iso_dt(state0.simulation_clock))
    search_id = "s-1"
    from backend.app.domain.models import SearchResponse
    repo.store_search(search_id, req, SearchResponse(snapshot=snap0, search_id=search_id, status="feasible", routes=routes))

    # Create plan -> increments plans_revision, NOT calculation snapshot
    plan = plan_service.create_plan_from_search(
        mutation_id="m-create-plan",
        expected_snapshot=snap0,
        search_id=search_id,
        route_id=routes[0].id,
        name="Test Plan",
    )
    state1 = repo.get_state()
    assert state1.plans_revision == 1
    assert state1.snapshot.schedule_revision == snap0.schedule_revision
    assert state1.snapshot.event_revision == snap0.event_revision
    assert state1.snapshot.clock_revision == snap0.clock_revision

    # Apply decision -> increments plans_revision again
    plan_updated, decision = plan_service.apply_decision(
        plan_id=plan.plan_id,
        mutation_id="m-dec-1",
        expected_snapshot=state1.snapshot,
        expected_plan_revision=plan.plan_revision,
        actor="demo-manager",
        action="keep_selected",
        reason="Keeping feasible route",
    )
    state2 = repo.get_state()
    assert state2.plans_revision == 2
    # Calculation revisions unchanged!
    assert state2.snapshot.schedule_revision == snap0.schedule_revision
    assert state2.snapshot.event_revision == snap0.event_revision
    assert state2.snapshot.clock_revision == snap0.clock_revision

def test_f2_origin_progress_and_clock_advance(temp_db):
    repo: Repository = temp_db["repo"]
    plan_service: PlanService = temp_db["plan_service"]
    clock_service: ClockService = temp_db["clock_service"]

    # Section 10 counterexample:
    # Ready 08:00Z, origin handling 120min, first departure 16:00Z.
    # Initial clock 07:00Z.
    state0 = repo.get_state()
    req = SearchRequest(
        origin_id="FRA_HUB",
        destination_id="KEM_BRANCH",
        ready_at="2026-09-21T08:00:00Z",
        service_profile_id="mixed",
        max_results=3,
    )
    from backend.app.engine.route_search import search_routes
    routes, _ = search_routes(repo.get_network(), req, repo.get_events(), parse_iso_dt(state0.simulation_clock))
    search_id = "s-f2"
    from backend.app.domain.models import SearchResponse
    repo.store_search(search_id, req, SearchResponse(snapshot=state0.snapshot, search_id=search_id, status="feasible", routes=routes))

    # Select direct route (departs 16:00Z, arrives 22:00Z, total 840 mins)
    direct_route = next(r for r in routes if r.lane_ids == ["L_FRA_KEM"])
    plan = plan_service.create_plan_from_search(
        mutation_id="m-f2-1",
        expected_snapshot=state0.snapshot,
        search_id=search_id,
        route_id=direct_route.id,
        name="Direct Plan",
    )
    assert plan.selected_projection.arrival_at == "2026-09-21T22:00:00Z"
    assert plan.selected_projection.total_minutes == 840

    # Advance clock to 09:00Z: freeze 60 min of origin handling, 60 min remain, arrival stays 22:00Z
    state_09z = clock_service.advance_demo_clock(
        mutation_id="m-clk-09",
        expected_snapshot=repo.get_snapshot(),
        target_clock_iso="2026-09-21T09:00:00Z",
    )
    plan_09z = repo.get_plan(plan.plan_id)
    assert plan_09z.origin_progress.completed_work_minutes == 60
    assert plan_09z.selected_projection is not None
    assert plan_09z.selected_projection.arrival_at == "2026-09-21T22:00:00Z"
    assert plan_09z.selected_projection.total_minutes == 840

    # Advance to 15:30Z: 15:00Z cutoff passed, but retain already booked direct 16:00 service!
    state_1530z = clock_service.advance_demo_clock(
        mutation_id="m-clk-1530",
        expected_snapshot=repo.get_snapshot(),
        target_clock_iso="2026-09-21T15:30:00Z",
    )
    plan_1530z = repo.get_plan(plan.plan_id)
    assert plan_1530z.selected_projection is not None
    assert plan_1530z.selected_projection.arrival_at == "2026-09-21T22:00:00Z"

    # Advance to 16:00Z: reaching departure marks outside_demo_scope!
    state_16z = clock_service.advance_demo_clock(
        mutation_id="m-clk-16",
        expected_snapshot=repo.get_snapshot(),
        target_clock_iso="2026-09-21T16:00:00Z",
    )
    plan_16z = repo.get_plan(plan.plan_id)
    assert plan_16z.status == "outside_demo_scope"
    assert plan_16z.selected_projection is None

def test_f3_stronger_report_same_group_stability():
    # Base 08-09 (60m). Incident +60m from 08:00 to 10:00.
    # Stronger report in same correlation key +180m beginning 09:30 through 13:00.
    # Should finish at 12:00Z (08:00 + 60 base + 180 max = 12:00), not 10:00Z and not 13:00Z.
    node = Node(
        id="N_F3", name="Hub F3", type="hub", country="DE", timezone="UTC",
        latitude=50.0, longitude=8.0, processing_minutes=60, active=True, provenance="test"
    )
    clock = parse_iso_dt("2026-09-21T07:00:00Z")
    arr = parse_iso_dt("2026-09-21T08:00:00Z")

    e1 = Event(
        id="e1", version=1, type="operational", source_kind="manager", external_id="e1",
        source_reference="test", observed_at="2026-09-21T07:00:00Z", valid_from="2026-09-21T08:00:00Z",
        valid_until="2026-09-21T10:00:00Z", review_due_at=None, target_kind="node", target_id="N_F3",
        mode="road", effect_type="additional_handling_minutes", effect_minutes=60, verification_status="accepted",
        lifecycle_status="active", correlation_key="INCIDENT-SAME", reason="Report 1", reported_by="mgr",
        received_at="2026-09-21T07:00:00Z", review_overdue=False, applies_to_departure_at=None, observation_id=None,
    )
    e2 = Event(
        id="e2", version=1, type="operational", source_kind="manager", external_id="e2",
        source_reference="test", observed_at="2026-09-21T07:00:00Z", valid_from="2026-09-21T09:30:00Z",
        valid_until="2026-09-21T13:00:00Z", review_due_at=None, target_kind="node", target_id="N_F3",
        mode="road", effect_type="additional_handling_minutes", effect_minutes=180, verification_status="accepted",
        lifecycle_status="active", correlation_key="INCIDENT-SAME", reason="Report 2 (stronger)", reported_by="mgr",
        received_at="2026-09-21T07:00:00Z", review_overdue=False, applies_to_departure_at=None, observation_id=None,
    )

    tot, end_dt, res = compute_node_handling_delay(node, "road", arr, [e1, e2], clock)
    assert res.total_extra_minutes == 180
    assert tot == 240 # 60 base + 180 max
    assert end_dt == parse_iso_dt("2026-09-21T12:00:00Z")

def test_f4_inactive_intermediate_hub(temp_db):
    repo: Repository = temp_db["repo"]
    plan_service: PlanService = temp_db["plan_service"]

    # Initial search with MUC_HUB active
    req = SearchRequest(
        origin_id="FRA_HUB",
        destination_id="KEM_BRANCH",
        ready_at="2026-09-21T08:00:00Z",
        service_profile_id="mixed",
        max_results=3,
    )
    from backend.app.engine.route_search import search_routes
    routes, _ = search_routes(repo.get_network(), req, repo.get_events(), parse_iso_dt("2026-09-21T07:00:00Z"))
    assert any(any("MUC" in l for l in r.lane_ids) for r in routes)

    # Disable MUC_HUB
    repo.update_node("MUC_HUB", active=False, processing_minutes=None)
    routes_after, _ = search_routes(repo.get_network(), req, repo.get_events(), parse_iso_dt("2026-09-21T07:00:00Z"))
    # Munich path must not appear in fresh search
    assert not any(any("MUC" in l for l in r.lane_ids) for r in routes_after)

def test_f5_capacity_example_api(temp_db):
    repo: Repository = temp_db["repo"]
    summary = repo.get_data_summary()
    assert summary.capacity_example is not None
    assert summary.capacity_example.source_file == "disposition.csv"
    assert summary.capacity_example.relation == "R01"
    assert summary.capacity_example.destination == "Hamburg"
    assert summary.capacity_example.date == "2024-01-04"
    assert summary.capacity_example.planned_trailers == 4
    assert summary.capacity_example.needed_trailers == 5
    assert summary.capacity_example.special_trips == 1
    assert summary.capacity_example.loading_metres == 55.5
    assert summary.capacity_example.trailer_capacity_metres == 13.6

def test_f6_immutable_review_evidence(temp_db):
    repo: Repository = temp_db["repo"]
    plan_service: PlanService = temp_db["plan_service"]

    # Create plan and decide
    state = repo.get_state()
    req = SearchRequest(
        origin_id="FRA_HUB",
        destination_id="KEM_BRANCH",
        ready_at="2026-09-21T08:00:00Z",
        service_profile_id="mixed",
        max_results=3,
    )
    from backend.app.engine.route_search import search_routes
    from backend.app.domain.models import SearchResponse
    routes, _ = search_routes(repo.get_network(), req, repo.get_events(), parse_iso_dt(state.simulation_clock))
    repo.store_search("s-f6", req, SearchResponse(snapshot=state.snapshot, search_id="s-f6", status="feasible", routes=routes))

    plan = plan_service.create_plan_from_search("m-f6-p", state.snapshot, "s-f6", routes[0].id, "F6 Plan")
    plan, dec = plan_service.apply_decision(
        plan_id=plan.plan_id,
        mutation_id="m-f6-d",
        expected_snapshot=repo.get_snapshot(),
        expected_plan_revision=plan.plan_revision,
        actor="manager",
        action="keep_selected",
        reason="Initial approval",
    )
    initial_approved_arrival = dec.review_evidence.selected_itinerary.arrival_at

    # Now mutate lane duration or add heavy delay event
    repo.update_lane("L_FRA_KEM", active=None, duration_minutes=999, departures=None)
    plan_service.recompute_all_plans()

    # Verify that stored decision review_evidence remains completely identical
    decisions = repo.get_decisions(plan.plan_id)
    assert decisions[0].review_evidence.selected_itinerary.arrival_at == initial_approved_arrival
    assert decisions[0].review_evidence.selected_itinerary.arrival_at == "2026-09-21T22:00:00Z"
