"""Domain models matching docs/contracts/openapi.json specification."""
from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime
import re

RFC3339_REGEX = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$"
)

class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

class Snapshot(ContractModel):
    dataset_id: str = Field(..., min_length=1)
    schedule_revision: int = Field(..., ge=0)
    event_revision: int = Field(..., ge=0)
    clock_revision: int = Field(..., ge=0)

class State(ContractModel):
    api_version: str = Field("2.0.0", min_length=1)
    snapshot: Snapshot
    simulation_clock: str
    demo_mode: bool
    mode: Literal["demo", "live"]
    plans_revision: int = Field(0, ge=0)
    integrations_revision: int = Field(0, ge=0)

class Health(ContractModel):
    status: Literal["ok", "degraded", "unhealthy"]
    database: Literal["connected", "error"]
    simulation_clock: str
    mode: Literal["demo", "live"]
    dataset_id: str

class ErrorDetail(ContractModel):
    field: Optional[str] = None
    message: str
    code: Optional[str] = None

class ErrorBody(ContractModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)
    trace_id: str
    current_snapshot: Optional[Snapshot] = None

class Error(ContractModel):
    error: ErrorBody

class Node(ContractModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    type: Literal["hub", "branch", "hand_over"]
    country: str = Field(..., min_length=2, max_length=2)
    timezone: str = Field(..., min_length=1)
    latitude: float
    longitude: float
    processing_minutes: int = Field(..., ge=0)
    active: bool
    provenance: str = Field(..., min_length=1)

class DepartureRule(ContractModel):
    id: str = Field(..., min_length=1)
    weekdays: list[int] = Field(..., min_length=1, max_length=7)
    local_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    cutoff_minutes: int = Field(..., ge=0)

class Lane(ContractModel):
    id: str = Field(..., min_length=1)
    from_node_id: str = Field(..., min_length=1)
    to_node_id: str = Field(..., min_length=1)
    mode: Literal["road", "air"]
    duration_minutes: int = Field(..., ge=1)
    active: bool
    valid_from: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    valid_to: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    departures: list[DepartureRule] = Field(default_factory=list)
    provenance: str = Field(..., min_length=1)

class CalendarRule(ContractModel):
    id: str = Field(..., min_length=1)
    lane_id: str = Field(..., min_length=1)
    mode: Literal["road", "air"]
    timezone: str = Field(..., min_length=1)
    weekday: int = Field(..., ge=1, le=7)
    start_local_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_next_day_local_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    action: Literal["pause_travel"]
    provenance: str = Field(..., min_length=1)

class ServiceProfile(ContractModel):
    id: str = Field(..., min_length=1)
    allowed_modes: list[Literal["road", "air"]] = Field(..., min_length=1)
    max_lanes: int = Field(..., ge=1)
    scope: Literal["branch_to_branch"]

class Network(ContractModel):
    snapshot: Snapshot
    nodes: list[Node]
    lanes: list[Lane]
    calendar_rules: list[CalendarRule]
    service_profiles: list[ServiceProfile]

class Reason(ContractModel):
    code: Literal[
        "NODE_HANDLING",
        "EVENT_HANDLING_DELAY",
        "WAIT_DEPARTURE",
        "MISSED_CUTOFF",
        "LANE_TRAVEL",
        "EVENT_TRAVEL_DELAY",
        "CALENDAR_PAUSE",
    ]
    minutes: int = Field(..., ge=0)
    description: str
    event_ids: list[str] = Field(default_factory=list)

class Segment(ContractModel):
    segment_index: int = Field(..., ge=0)
    type: Literal["handle", "travel", "wait"]
    node_id: Optional[str] = None
    lane_id: Optional[str] = None
    start_at: str
    end_at: str
    duration_minutes: int = Field(..., ge=1)
    reasons: list[Reason] = Field(default_factory=list)

class Route(ContractModel):
    id: str = Field(..., min_length=24, max_length=24)
    lane_ids: list[str]
    departure_times: list[str]
    arrival_at: str
    total_minutes: int = Field(..., ge=1)
    transfer_count: int = Field(..., ge=0)
    segments: list[Segment]
    explanation: list[str] = Field(default_factory=list)

class Diagnostic(ContractModel):
    category: Literal["connectivity", "closure", "calendar", "cutoff", "profile", "limit"]
    code: Literal[
        "CLOSED_LANE",
        "CANCELLED_DEPARTURE",
        "INACTIVE_LANE",
        "OUTSIDE_VALIDITY",
        "HORIZON_EXCEEDED",
        "DISCONNECTED",
        "MISSED_CUTOFF",
        "PROFILE_REJECTED",
        "SEARCH_LIMIT",
    ]
    message: str
    target_id: Optional[str] = None

class SearchRequest(ContractModel):
    origin_id: str = Field(..., min_length=1)
    destination_id: str = Field(..., min_length=1)
    ready_at: str
    service_profile_id: str = Field(..., min_length=1)
    max_results: int = Field(3, ge=1, le=10)
    arrival_deadline: Optional[str] = None

class SearchResponse(ContractModel):
    snapshot: Snapshot
    search_id: str = Field(..., min_length=1)
    status: Literal["feasible", "no_feasible_route"]
    routes: list[Route] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)

class LaneUpdate(ContractModel):
    mutation_id: str = Field(..., min_length=1)
    expected_snapshot: Snapshot
    active: Optional[bool] = None
    duration_minutes: Optional[int] = Field(None, ge=1)
    departures: Optional[list[DepartureRule]] = None

class NodeUpdate(ContractModel):
    mutation_id: str = Field(..., min_length=1)
    expected_snapshot: Snapshot
    active: Optional[bool] = None
    processing_minutes: Optional[int] = Field(None, ge=0)

class LaneMutationResult(ContractModel):
    snapshot: Snapshot
    lane: Lane
    mutation_id: str

class NodeMutationResult(ContractModel):
    snapshot: Snapshot
    node: Node
    mutation_id: str

class EventInput(ContractModel):
    type: Literal["traffic", "weather", "political", "operational"]
    source_kind: Literal["manager", "demo_feed", "provider"]
    external_id: str = Field(..., min_length=1)
    source_reference: str = Field(..., min_length=1)
    observed_at: str
    valid_from: str
    valid_until: Optional[str] = None
    review_due_at: Optional[str] = None
    target_kind: Literal["node", "lane"]
    target_id: str = Field(..., min_length=1)
    mode: Literal["road", "air"]
    effect_type: Literal[
        "additional_travel_minutes",
        "additional_handling_minutes",
        "closure",
        "departure_cancellation",
    ]
    effect_minutes: Optional[int] = Field(None, ge=0)
    verification_status: Literal["pending", "accepted"]
    lifecycle_status: Literal["active", "withdrawn"]
    correlation_key: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=3, max_length=1000)
    applies_to_departure_at: Optional[str] = None
    observation_id: Optional[str] = None

class Event(EventInput):
    id: str = Field(..., min_length=1)
    version: int = Field(..., ge=1)
    reported_by: str = Field(..., min_length=1)
    received_at: str
    review_overdue: bool

class CreateEvent(ContractModel):
    mutation_id: str = Field(..., min_length=1)
    expected_snapshot: Snapshot
    event: EventInput

class ReviseEvent(ContractModel):
    mutation_id: str = Field(..., min_length=1)
    expected_snapshot: Snapshot
    expected_version: int = Field(..., ge=1)
    event: EventInput

class EventMutationResult(ContractModel):
    snapshot: Snapshot
    event: Event
    mutation_id: str

class EventList(ContractModel):
    snapshot: Snapshot
    events: list[Event]

class CreatePlan(ContractModel):
    mutation_id: str = Field(..., min_length=1)
    expected_snapshot: Snapshot
    search_id: str = Field(..., min_length=1)
    route_id: str = Field(..., min_length=24, max_length=24)
    name: str = Field(..., min_length=1, max_length=100)

class OriginProgress(ContractModel):
    plan_id: str = Field(..., min_length=1)
    recorded_at: str
    frozen_segments: list[Segment] = Field(default_factory=list)
    completed_work_minutes: int = Field(..., ge=0)
    handling_complete: bool
    first_mode: Literal["road", "air"]

class ReviewEvidence(ContractModel):
    reviewed_snapshot: Snapshot
    selected_itinerary: Route
    selected_projection: Optional[Route] = None
    proposed_itinerary: Optional[Route] = None
    network_snapshot: Network
    applied_event_versions: list[dict[str, Any]] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)

class Decision(ContractModel):
    id: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    actor: str = Field(..., min_length=1)
    action: Literal["accept_route", "keep_selected", "defer"]
    reason: str = Field(..., min_length=3, max_length=1000)
    selected_route_id: Optional[str] = None
    superseded_route_id: Optional[str] = None
    decided_at: str
    review_evidence: ReviewEvidence

class PlanView(ContractModel):
    plan_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    status: Literal["stable", "review_required", "blocked", "outside_demo_scope"]
    created_at: str
    updated_at: str
    request: SearchRequest
    selected_itinerary: Route
    selected_projection: Optional[Route] = None
    alternative_recommendations: list[Route] = Field(default_factory=list)
    decisions_count: int = Field(0, ge=0)
    latest_decision: Optional[Decision] = None
    plan_revision: int = Field(0, ge=0)
    review_reasons: list[str] = Field(default_factory=list)
    origin_progress: Optional[OriginProgress] = None

class PlanList(ContractModel):
    snapshot: Snapshot
    plans_revision: int = Field(..., ge=0)
    plans: list[PlanView] = Field(default_factory=list)

class DecisionRequest(ContractModel):
    mutation_id: str = Field(..., min_length=1)
    expected_snapshot: Snapshot
    expected_plan_revision: int = Field(..., ge=0)
    actor: str = Field(..., min_length=1)
    action: Literal["accept_route", "keep_selected", "defer"]
    route_id: Optional[str] = None
    reason: str = Field(..., min_length=3, max_length=1000)

class DecisionResult(ContractModel):
    plan: PlanView
    decision: Decision
    mutation_id: str

class DecisionList(ContractModel):
    plan_id: str = Field(..., min_length=1)
    decisions: list[Decision] = Field(default_factory=list)

class ApplyPreset(ContractModel):
    mutation_id: str = Field(..., min_length=1)
    expected_snapshot: Snapshot
    preset_id: Literal["traffic_direct", "handling_munich", "closure_strasbourg"]

class AdvanceClock(ContractModel):
    mutation_id: str = Field(..., min_length=1)
    expected_snapshot: Snapshot
    target_clock: str

class ResetRequest(ContractModel):
    confirm: Literal["RESET_DEMO"]

class SourceSummary(ContractModel):
    filename: str = Field(..., min_length=1)
    rows: Optional[int] = Field(None, ge=0)
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    issues: list[str] = Field(default_factory=list)
    sha256: Optional[str] = None

class CapacityExample(ContractModel):
    source_file: str = Field(..., min_length=1)
    relation: str = Field(..., min_length=1)
    destination: str = Field(..., min_length=1)
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    planned_trailers: int = Field(..., ge=0)
    needed_trailers: int = Field(..., ge=0)
    special_trips: int = Field(..., ge=0)
    loading_metres: float = Field(..., ge=0)
    trailer_capacity_metres: float = Field(..., gt=0)

class DataSummary(ContractModel):
    sources: list[SourceSummary] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    import_complete: bool
    capacity_example: Optional[CapacityExample] = None

class Geometry(ContractModel):
    type: Literal["LineString"]
    coordinates: list[list[float]]

class LaneGeometry(ContractModel):
    lane_id: str = Field(..., min_length=1)
    departure_at: Optional[str] = None
    geometry_kind: Literal["schematic", "provider_road"]
    geometry: Geometry
    source: str = Field(..., min_length=1)
    attribution: str = Field(..., min_length=1)
    fetched_at: Optional[str] = None
    stale: bool

class MapGeometry(ContractModel):
    snapshot: Snapshot
    integrations_revision: int = Field(..., ge=0)
    lanes: list[LaneGeometry] = Field(default_factory=list)

class ProviderStatus(ContractModel):
    name: Literal["open_meteo", "tomtom", "operator_bulletins"]
    status: Literal["ok", "not_configured", "error", "disabled", "stale"]
    last_poll_at: Optional[str] = None
    last_successful_poll_at: Optional[str] = None
    consecutive_errors: int = Field(0, ge=0)
    error_message: Optional[str] = None
    mode: Literal["demo", "live"]

class Integrations(ContractModel):
    snapshot: Snapshot
    integrations_revision: int = Field(..., ge=0)
    providers: list[ProviderStatus] = Field(default_factory=list)

class Observation(ContractModel):
    id: str = Field(..., min_length=1)
    provider: Literal["open_meteo", "tomtom", "operator_bulletins"]
    target_kind: Literal["node", "lane"]
    target_id: str = Field(..., min_length=1)
    intended_departure_at: Optional[str] = None
    observed_at: str
    fetched_at: str
    valid_from: str
    valid_until: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    raw_digest: str = Field(..., min_length=1)
    attribution: str = Field(..., min_length=1)
    stale: bool

class ObservationList(ContractModel):
    snapshot: Snapshot
    integrations_revision: int = Field(..., ge=0)
    observations: list[Observation] = Field(default_factory=list)

class RefreshIntegrations(ContractModel):
    mutation_id: str = Field(..., min_length=1)
    expected_snapshot: Snapshot

class RefreshResult(ContractModel):
    snapshot: Snapshot
    integrations_revision: int = Field(..., ge=0)
    refreshed_at: str
    observations_created: int = Field(..., ge=0)
    events_proposed: int = Field(..., ge=0)
