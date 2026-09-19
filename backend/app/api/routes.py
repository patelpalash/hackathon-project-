"""FastAPI route handlers adhering to docs/contracts/openapi.json and docs/API_CONTRACT.md."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from ..domain.models import (
    Health,
    State,
    Network,
    DataSummary,
    SearchRequest,
    SearchResponse,
    Route,
    Diagnostic,
    LaneUpdate,
    LaneMutationResult,
    NodeUpdate,
    NodeMutationResult,
    EventList,
    CreateEvent,
    ReviseEvent,
    EventMutationResult,
    Event,
    PlanList,
    CreatePlan,
    PlanView,
    DecisionList,
    DecisionRequest,
    DecisionResult,
    ApplyPreset,
    AdvanceClock,
    ResetRequest,
    MapGeometry,
    Integrations,
    ObservationList,
    RefreshIntegrations,
    RefreshResult,
    Snapshot,
)
from ..storage.repository import Repository, ConcurrencyError
from ..engine.time_utils import parse_iso_dt, to_iso_utc, validate_input_time_string
from ..engine.route_search import search_routes
from ..services.plan_service import PlanService
from ..services.clock_service import ClockService
from ..services.data_importer import seed_network_and_geometries
from ..providers.orchestrator import ProviderOrchestrator

router = APIRouter(prefix="/api")

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"

def get_repo(request: Request) -> Repository:
    return request.app.state.repo

def get_plan_service(request: Request) -> PlanService:
    return request.app.state.plan_service

def get_clock_service(request: Request) -> ClockService:
    return request.app.state.clock_service

def get_orchestrator(request: Request) -> ProviderOrchestrator:
    return request.app.state.orchestrator

# 1. Health
@router.get("/health", response_model=Health)
def get_health(repo: Repository = Depends(get_repo)):
    state = repo.get_state()
    return Health(
        status="ok",
        database="connected",
        simulation_clock=state.simulation_clock,
        mode=state.mode,
        dataset_id=state.snapshot.dataset_id,
    )

# 2. State
@router.get("/state", response_model=State)
def get_state(repo: Repository = Depends(get_repo)):
    return repo.get_state()

# 3. Network
@router.get("/network", response_model=Network)
def get_network(repo: Repository = Depends(get_repo)):
    return repo.get_network()

# 4. Data Summary
@router.get("/data-summary", response_model=DataSummary)
def get_data_summary(repo: Repository = Depends(get_repo)):
    return repo.get_data_summary()

# 5. Search
@router.post("/routes/search", response_model=SearchResponse)
def post_search(
    req: SearchRequest,
    repo: Repository = Depends(get_repo),
):
    state = repo.get_state()
    network = repo.get_network()
    clock_dt = parse_iso_dt(state.simulation_clock)

    # Origin and destination check
    if req.origin_id == req.destination_id:
        raise ConcurrencyError("VALIDATION_ERROR", "Origin and destination must differ")

    nodes_by_id = {n.id: n for n in network.nodes}
    origin_node = nodes_by_id.get(req.origin_id)
    if not origin_node or not origin_node.active:
        raise ConcurrencyError("VALIDATION_ERROR", f"Origin {req.origin_id} is inactive or does not exist")

    dest_node = nodes_by_id.get(req.destination_id)
    if not dest_node or not dest_node.active:
        raise ConcurrencyError("VALIDATION_ERROR", f"Destination {req.destination_id} is inactive or does not exist")

    # Time validation
    norm_ready_dt, time_err = validate_input_time_string(req.ready_at, origin_node.timezone)
    if time_err:
        if "TIMEZONE_MISMATCH" in time_err:
            raise ConcurrencyError("TIMEZONE_MISMATCH", time_err)
        raise ConcurrencyError("VALIDATION_ERROR", time_err)

    if norm_ready_dt < clock_dt:
        raise ConcurrencyError("PAST_READY_TIME", f"ready_at ({req.ready_at}) must be >= simulation clock ({state.simulation_clock})")

    if req.arrival_deadline:
        norm_dl_dt, dl_err = validate_input_time_string(req.arrival_deadline, dest_node.timezone)
        if dl_err:
            raise ConcurrencyError("VALIDATION_ERROR", f"Invalid arrival_deadline: {dl_err}")
        if norm_dl_dt < norm_ready_dt:
            raise ConcurrencyError("VALIDATION_ERROR", "arrival_deadline must be >= ready_at")

    # Perform search
    events = repo.get_events()
    routes, diags = search_routes(network, req, events, clock_dt)

    status_str = "feasible" if routes else "no_feasible_route"
    search_id = f"search-{uuid.uuid4().hex[:8]}"

    resp = SearchResponse(
        snapshot=state.snapshot,
        search_id=search_id,
        status=status_str,
        routes=routes,
        diagnostics=diags,
    )

    repo.store_search(search_id, req, resp)
    repo.conn.commit()
    return resp

# 6. Update Lane
@router.patch("/lanes/{lane_id}", response_model=LaneMutationResult)
def patch_lane(
    lane_id: str,
    update: LaneUpdate,
    repo: Repository = Depends(get_repo),
    plan_service: PlanService = Depends(get_plan_service),
):
    cached = repo.check_idempotency(update.mutation_id, update)
    if cached:
        return LaneMutationResult.model_validate(cached)

    repo.verify_snapshot(update.expected_snapshot)
    lane = repo.update_lane(lane_id, update.active, update.duration_minutes, update.departures)

    # Recompute plans synchronously
    plan_service.recompute_all_plans()

    result = LaneMutationResult(
        snapshot=repo.get_snapshot(),
        lane=lane,
        mutation_id=update.mutation_id,
    )
    repo.record_receipt(update.mutation_id, update, result.model_dump())
    repo.conn.commit()
    return result

# 7. Update Node
@router.patch("/nodes/{node_id}", response_model=NodeMutationResult)
def patch_node(
    node_id: str,
    update: NodeUpdate,
    repo: Repository = Depends(get_repo),
    plan_service: PlanService = Depends(get_plan_service),
):
    cached = repo.check_idempotency(update.mutation_id, update)
    if cached:
        return NodeMutationResult.model_validate(cached)

    repo.verify_snapshot(update.expected_snapshot)
    node = repo.update_node(node_id, update.active, update.processing_minutes)

    # Recompute plans synchronously
    plan_service.recompute_all_plans()

    result = NodeMutationResult(
        snapshot=repo.get_snapshot(),
        node=node,
        mutation_id=update.mutation_id,
    )
    repo.record_receipt(update.mutation_id, update, result.model_dump())
    repo.conn.commit()
    return result

# 8. Get Events
@router.get("/events", response_model=EventList)
def get_events(repo: Repository = Depends(get_repo)):
    return EventList(snapshot=repo.get_snapshot(), events=repo.get_events())

def validate_event_input(event: Any, state: State, network: Network):
    """Validate semantic rules beyond json schema."""
    if event.source_kind == "provider":
        raise ConcurrencyError("PROVIDER_SOURCE_RESERVED", "source_kind 'provider' is reserved for adapter-internal ingestion")

    if len(event.reason.strip()) < 3 or not event.correlation_key.strip() or not event.external_id.strip() or not event.source_reference.strip():
        raise ConcurrencyError("VALIDATION_ERROR", "Reason and source identity must be nonblank")
    delay_effects = {"additional_travel_minutes", "additional_handling_minutes"}
    if event.effect_type in delay_effects and event.effect_minutes is None:
        raise ConcurrencyError("VALIDATION_ERROR", "Delay events require effect_minutes")
    if event.effect_type not in delay_effects and event.effect_minutes is not None:
        raise ConcurrencyError("VALIDATION_ERROR", "Closure and cancellation events require null effect_minutes")

    clock_dt = parse_iso_dt(state.simulation_clock)
    obs_dt = parse_iso_dt(event.observed_at)
    if obs_dt > clock_dt:
        raise ConcurrencyError("VALIDATION_ERROR", "observed_at cannot be in the future relative to simulation clock")

    vf_dt = parse_iso_dt(event.valid_from)
    if event.valid_until:
        vu_dt = parse_iso_dt(event.valid_until)
        if vu_dt <= vf_dt:
            raise ConcurrencyError("VALIDATION_ERROR", "valid_until must be > valid_from")
    else:
        if not event.review_due_at:
            raise ConcurrencyError("VALIDATION_ERROR", "review_due_at is mandatory when valid_until is null")

    if event.review_due_at:
        rd_dt = parse_iso_dt(event.review_due_at)
        if rd_dt <= obs_dt:
            raise ConcurrencyError("VALIDATION_ERROR", "review_due_at must be > observed_at")

    nodes_by_id = {n.id: n for n in network.nodes}
    lanes_by_id = {l.id: l for l in network.lanes}

    if event.target_kind == "node":
        if event.target_id not in nodes_by_id:
            raise ConcurrencyError("VALIDATION_ERROR", f"Unknown node target_id {event.target_id}")
        if event.effect_type != "additional_handling_minutes":
            raise ConcurrencyError("VALIDATION_ERROR", f"Node targets only support additional_handling_minutes, got {event.effect_type}")
        if event.applies_to_departure_at is not None:
            raise ConcurrencyError("VALIDATION_ERROR", "applies_to_departure_at is invalid for node targets")
    elif event.target_kind == "lane":
        if event.target_id not in lanes_by_id:
            raise ConcurrencyError("VALIDATION_ERROR", f"Unknown lane target_id {event.target_id}")
        lane = lanes_by_id[event.target_id]
        if event.mode != lane.mode:
            raise ConcurrencyError("VALIDATION_ERROR", f"Event mode {event.mode} does not match lane mode {lane.mode}")
        if event.effect_type == "additional_handling_minutes":
            raise ConcurrencyError("VALIDATION_ERROR", "Lane targets cannot use additional_handling_minutes")

# 9. Create Event
@router.post("/events", response_model=EventMutationResult, status_code=status.HTTP_201_CREATED)
def post_event(
    body: CreateEvent,
    repo: Repository = Depends(get_repo),
    plan_service: PlanService = Depends(get_plan_service),
):
    cached = repo.check_idempotency(body.mutation_id, body)
    if cached:
        return EventMutationResult.model_validate(cached)

    repo.verify_snapshot(body.expected_snapshot)
    state = repo.get_state()
    network = repo.get_network()
    validate_event_input(body.event, state, network)
    if body.event.lifecycle_status != "active":
        raise ConcurrencyError("VALIDATION_ERROR", "New events must be active")

    event_id = f"event-{uuid.uuid4().hex[:8]}"
    event = repo.insert_event_version(
        event_id=event_id,
        version=1,
        inp=body.event,
        reported_by="demo-manager",
    )

    # Synchronous plan recomputation
    plan_service.recompute_all_plans()

    result = EventMutationResult(
        snapshot=repo.get_snapshot(),
        event=event,
        mutation_id=body.mutation_id,
    )
    repo.record_receipt(body.mutation_id, body, result.model_dump())
    repo.conn.commit()
    return result

# 10. Revise Event
@router.post("/events/{event_id}/revisions", response_model=EventMutationResult, status_code=status.HTTP_201_CREATED)
def post_event_revision(
    event_id: str,
    body: ReviseEvent,
    repo: Repository = Depends(get_repo),
    plan_service: PlanService = Depends(get_plan_service),
):
    cached = repo.check_idempotency(body.mutation_id, body)
    if cached:
        return EventMutationResult.model_validate(cached)

    repo.verify_snapshot(body.expected_snapshot)
    events = repo.get_events()
    existing = next((e for e in events if e.id == event_id), None)
    if not existing:
        raise ConcurrencyError("NOT_FOUND", f"Event {event_id} not found")

    if existing.version != body.expected_version:
        raise ConcurrencyError(
            "EVENT_VERSION_CONFLICT",
            f"Expected version {body.expected_version} does not match current version {existing.version}",
            current_snapshot=repo.get_snapshot(),
        )

    state = repo.get_state()
    network = repo.get_network()
    validate_event_input(body.event, state, network)
    identity_fields = ("type", "source_kind", "external_id", "source_reference",
                       "target_kind", "target_id", "mode")
    if any(getattr(existing, field) != getattr(body.event, field) for field in identity_fields):
        raise ConcurrencyError("VALIDATION_ERROR", "Event identity and source cannot change in a revision")

    new_version = existing.version + 1
    event = repo.insert_event_version(
        event_id=event_id,
        version=new_version,
        inp=body.event,
        reported_by="demo-manager",
    )

    plan_service.recompute_all_plans()

    result = EventMutationResult(
        snapshot=repo.get_snapshot(),
        event=event,
        mutation_id=body.mutation_id,
    )
    repo.record_receipt(body.mutation_id, body, result.model_dump())
    repo.conn.commit()
    return result

# 11. Get Plans
@router.get("/plans", response_model=PlanList)
def get_plans(repo: Repository = Depends(get_repo)):
    state = repo.get_state()
    return PlanList(
        snapshot=state.snapshot,
        plans_revision=state.plans_revision,
        plans=repo.get_plans(),
    )

# 12. Create Plan
@router.post("/plans", response_model=PlanView, status_code=status.HTTP_201_CREATED)
def post_plan(
    body: CreatePlan,
    plan_service: PlanService = Depends(get_plan_service),
):
    return plan_service.create_plan_from_search(
        mutation_id=body.mutation_id,
        expected_snapshot=body.expected_snapshot,
        search_id=body.search_id,
        route_id=body.route_id,
        name=body.name,
    )

# 13. Get Plan View
@router.get("/plans/{plan_id}", response_model=PlanView)
def get_plan_view(plan_id: str, repo: Repository = Depends(get_repo)):
    plan = repo.get_plan(plan_id)
    if not plan:
        raise ConcurrencyError("NOT_FOUND", f"Plan {plan_id} not found")
    return plan

# 14. Get Decisions
@router.get("/plans/{plan_id}/decisions", response_model=DecisionList)
def get_decisions(plan_id: str, repo: Repository = Depends(get_repo)):
    plan = repo.get_plan(plan_id)
    if not plan:
        raise ConcurrencyError("NOT_FOUND", f"Plan {plan_id} not found")
    return DecisionList(plan_id=plan_id, decisions=repo.get_decisions(plan_id))

# 15. Record Decision
@router.post("/plans/{plan_id}/decisions", response_model=DecisionResult, status_code=status.HTTP_201_CREATED)
def post_decision(
    plan_id: str,
    body: DecisionRequest,
    plan_service: PlanService = Depends(get_plan_service),
):
    plan, decision = plan_service.apply_decision(
        plan_id=plan_id,
        mutation_id=body.mutation_id,
        expected_snapshot=body.expected_snapshot,
        expected_plan_revision=body.expected_plan_revision,
        actor=body.actor,
        action=body.action,
        reason=body.reason,
        route_id=body.route_id,
    )
    return DecisionResult(plan=plan, decision=decision, mutation_id=body.mutation_id)

# 16. Demo Presets
@router.post("/demo/presets", response_model=EventMutationResult)
def post_preset(
    body: ApplyPreset,
    repo: Repository = Depends(get_repo),
    plan_service: PlanService = Depends(get_plan_service),
):
    cached = repo.check_idempotency(body.mutation_id, body)
    if cached:
        return EventMutationResult.model_validate(cached)

    repo.verify_snapshot(body.expected_snapshot)
    state = repo.get_state()
    if state.mode != "demo":
        raise ConcurrencyError("MODE_MISMATCH", "Presets only available in demo mode")

    presets_path = DOCS_DIR / "fixtures" / "presets.json"
    if not presets_path.exists():
        raise ConcurrencyError("NOT_FOUND", "Presets fixture not found")

    raw_presets = json.loads(presets_path.read_text(encoding="utf-8"))
    preset_data = raw_presets.get(body.preset_id)
    if not preset_data:
        raise ConcurrencyError("NOT_FOUND", f"Unknown preset {body.preset_id}")

    # Check if already applied
    events = repo.get_events()
    existing = next((e for e in events if e.id == preset_data["id"]), None)
    if existing:
        # Return existing event without adding duplicate delay
        res = EventMutationResult(
            snapshot=repo.get_snapshot(),
            event=existing,
            mutation_id=body.mutation_id,
        )
        repo.record_receipt(body.mutation_id, body, res.model_dump())
        repo.conn.commit()
        return res

    event = repo.insert_event_version(
        event_id=preset_data["id"],
        version=1,
        inp=Event.model_validate(preset_data),
        reported_by=preset_data.get("reported_by", "demo-feed"),
    )

    plan_service.recompute_all_plans()

    res = EventMutationResult(
        snapshot=repo.get_snapshot(),
        event=event,
        mutation_id=body.mutation_id,
    )
    repo.record_receipt(body.mutation_id, body, res.model_dump())
    repo.conn.commit()
    return res

# 17. Demo Clock
@router.post("/demo/clock", response_model=State)
def post_clock(
    body: AdvanceClock,
    clock_service: ClockService = Depends(get_clock_service),
):
    return clock_service.advance_demo_clock(
        mutation_id=body.mutation_id,
        expected_snapshot=body.expected_snapshot,
        target_clock_iso=body.target_clock,
    )

# 18. Demo Reset
@router.post("/demo/reset", response_model=State)
def post_reset(
    body: ResetRequest,
    repo: Repository = Depends(get_repo),
):
    state = repo.get_state()
    if state.mode != "demo":
        raise ConcurrencyError("MODE_MISMATCH", "Reset only permitted in demo mode")

    new_dataset_id = f"demo-dataset-{uuid.uuid4().hex[:8]}"
    seed_network_and_geometries(
        conn=repo.conn,
        dataset_id=new_dataset_id,
        simulation_clock="2026-09-21T07:00:00Z",
        mode="demo",
        force_reset=True,
    )
    return repo.get_state()

# 19. Map Geometry
@router.get("/map/geometry", response_model=MapGeometry)
def get_map_geometry(repo: Repository = Depends(get_repo)):
    return repo.get_map_geometry()

# 20. Integrations
@router.get("/integrations", response_model=Integrations)
def get_integrations(repo: Repository = Depends(get_repo)):
    return repo.get_integrations()

# 21. Observations
@router.get("/integrations/observations", response_model=ObservationList)
def get_observations(repo: Repository = Depends(get_repo)):
    state = repo.get_state()
    obs = repo.get_observations(limit=100)
    return ObservationList(
        snapshot=state.snapshot,
        integrations_revision=state.integrations_revision,
        observations=obs,
    )

# 22. Integrations Refresh
@router.post("/integrations/refresh", response_model=RefreshResult)
async def post_integrations_refresh(
    body: RefreshIntegrations,
    repo: Repository = Depends(get_repo),
    orchestrator: ProviderOrchestrator = Depends(get_orchestrator),
    plan_service: PlanService = Depends(get_plan_service),
):
    cached = repo.check_idempotency(body.mutation_id, body)
    if cached:
        return RefreshResult.model_validate(cached)

    repo.verify_snapshot(body.expected_snapshot)
    state = repo.get_state()
    if state.mode == "demo":
        raise ConcurrencyError("MODE_MISMATCH", "Integrations refresh is not supported in demo mode")

    # Fetch outside write lock
    batches = await orchestrator.poll_all()

    # Ingest inside transaction
    obs_count, ev_count = orchestrator.ingest_batches(batches)
    if ev_count > 0:
        plan_service.recompute_all_plans()

    now_iso = to_iso_utc(datetime.now(timezone.utc))
    res = RefreshResult(
        snapshot=repo.get_snapshot(),
        integrations_revision=repo.get_state().integrations_revision,
        refreshed_at=now_iso,
        observations_created=obs_count,
        events_proposed=ev_count,
    )
    repo.record_receipt(body.mutation_id, body, res.model_dump())
    repo.conn.commit()
    return res
