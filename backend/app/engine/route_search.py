"""Core route search engine adhering to docs/ROUTING_RULES.md."""
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, NamedTuple
from ..domain.models import (
    Network,
    Node,
    Lane,
    CalendarRule,
    ServiceProfile,
    Event,
    SearchRequest,
    SearchResponse,
    Route,
    Segment,
    Diagnostic,
)
from .time_utils import (
    parse_iso_dt,
    to_iso_utc,
    minutes_between,
    compute_route_id,
    expand_departure,
)
from .calendar import is_departure_during_calendar_pause, TravelChunk
from .events import (
    compute_node_handling_delay,
    compute_lane_travel_delay_and_chunks,
    is_lane_blocked_by_closure,
    DelayGroupResult,
)
from .timeline import (
    build_handling_segment,
    build_wait_segment,
    build_travel_segments,
)

MAX_DEPARTURE_TRANSITIONS = 50000

class CandidateLeg(NamedTuple):
    lane: Lane
    departure_utc: datetime
    arrival_utc: datetime
    ready_before_wait_utc: datetime
    missed_earlier_cutoff: bool
    travel_chunks: list[TravelChunk]
    travel_delay_res: DelayGroupResult
    intermediate_handling_minutes: int
    intermediate_handling_end_utc: Optional[datetime]
    intermediate_handling_delay_res: Optional[DelayGroupResult]

class CandidateRoute(NamedTuple):
    path_lanes: list[Lane]
    legs: list[CandidateLeg]
    origin_handling_minutes: int
    origin_handling_end_utc: datetime
    origin_handling_delay_res: DelayGroupResult
    final_arrival_utc: datetime

def find_paths(
    origin_id: str,
    destination_id: str,
    lanes_by_from: dict[str, list[Lane]],
    nodes_by_id: dict[str, Node],
    allowed_modes: set[str],
    max_lanes: int,
) -> list[list[Lane]]:
    """Enumerate directed, cycle-free node paths with at most max_lanes."""
    paths: list[list[Lane]] = []

    def dfs(current_node_id: str, current_path: list[Lane], visited_nodes: set[str]):
        if len(current_path) > max_lanes:
            return
        if current_node_id == destination_id:
            if current_path:
                paths.append(list(current_path))
            return

        for lane in lanes_by_from.get(current_node_id, []):
            if not lane.active:
                continue
            if lane.mode not in allowed_modes:
                continue
            next_node_id = lane.to_node_id
            if next_node_id in visited_nodes:
                continue
            next_node = nodes_by_id.get(next_node_id)
            if not next_node or not next_node.active:
                continue

            current_path.append(lane)
            visited_nodes.add(next_node_id)
            dfs(next_node_id, current_path, visited_nodes)
            visited_nodes.remove(next_node_id)
            current_path.pop()

    dfs(origin_id, [], {origin_id})
    return paths

def evaluate_path(
    path: list[Lane],
    nodes_by_id: dict[str, Node],
    events: list[Event],
    calendar_rules: list[CalendarRule],
    ready_at_utc: datetime,
    horizon_utc: datetime,
    evaluation_clock_utc: datetime,
    counter: list[int],
) -> Optional[CandidateRoute]:
    """
    Explore eligible departure sequences for a fixed lane path.
    Returns the candidate route with the earliest final arrival, or None.
    """
    origin_node = nodes_by_id[path[0].from_node_id]
    first_mode = path[0].mode

    # Origin node handling
    orig_handling_mins, orig_handling_end_utc, orig_delay_res = compute_node_handling_delay(
        origin_node,
        first_mode,
        ready_at_utc,
        events,
        evaluation_clock_utc,
    )

    best_candidate: Optional[CandidateRoute] = None

    def search_legs(
        leg_idx: int,
        ready_for_dep_utc: datetime,
        accum_legs: list[CandidateLeg],
    ):
        nonlocal best_candidate
        if leg_idx == len(path):
            final_arrival = accum_legs[-1].arrival_utc
            if best_candidate is None or final_arrival < best_candidate.final_arrival_utc:
                best_candidate = CandidateRoute(
                    path_lanes=path,
                    legs=list(accum_legs),
                    origin_handling_minutes=orig_handling_mins,
                    origin_handling_end_utc=orig_handling_end_utc,
                    origin_handling_delay_res=orig_delay_res,
                    final_arrival_utc=final_arrival,
                )
            return

        lane = path[leg_idx]
        from_node = nodes_by_id[lane.from_node_id]
        from_zone = ZoneInfo(from_node.timezone)

        # Minimum remaining travel duration to destination as admissible heuristic
        min_rem_minutes = sum(l.duration_minutes for l in path[leg_idx:])

        # Explore departures for this lane starting from local date of ready_for_dep_utc
        start_date = ready_for_dep_utc.astimezone(from_zone).date()
        
        missed_earlier_departure_at_visit = False

        # Look up to 16 days ahead
        for day_offset in range(16):
            local_date = start_date + timedelta(days=day_offset)
            local_date_str = local_date.isoformat()
            if not (lane.valid_from <= local_date_str <= lane.valid_to):
                continue

            for dep_rule in lane.departures:
                counter[0] += 1
                if counter[0] > MAX_DEPARTURE_TRANSITIONS:
                    raise RuntimeError("SEARCH_LIMIT exceeded (over 50000 transitions)")

                dep_utc = expand_departure(local_date, dep_rule.local_time, from_node.timezone)
                if dep_utc is None:
                    continue

                # Branch-and-bound: if departure + minimum remaining duration cannot beat current best, prune
                if best_candidate is not None and dep_utc + timedelta(minutes=min_rem_minutes) >= best_candidate.final_arrival_utc:
                    return

                if local_date.isoweekday() not in dep_rule.weekdays:
                    continue

                # Calendar pause at departure
                if is_departure_during_calendar_pause(dep_utc, lane, calendar_rules):
                    continue

                cutoff_utc = dep_utc - timedelta(minutes=dep_rule.cutoff_minutes)

                # Cutoff eligibility: ready_for_dep_utc <= cutoff_utc
                if ready_for_dep_utc > cutoff_utc:
                    # Missed cutoff for this departure occurrence
                    missed_earlier_departure_at_visit = True
                    continue

                if dep_utc > horizon_utc:
                    continue

                # Travel delay and pause chunks
                work, arr_utc, chunks, trav_delay_res = compute_lane_travel_delay_and_chunks(
                    lane,
                    dep_utc,
                    events,
                    calendar_rules,
                    evaluation_clock_utc,
                    horizon_utc,
                )

                if arr_utc > horizon_utc:
                    continue

                # Check closure
                if is_lane_blocked_by_closure(lane, dep_utc, arr_utc, events, evaluation_clock_utc):
                    continue

                # Intermediate handling if not last leg
                int_handling_mins = 0
                int_handling_end: Optional[datetime] = None
                int_delay_res: Optional[DelayGroupResult] = None
                next_ready = arr_utc

                if leg_idx + 1 < len(path):
                    next_lane = path[leg_idx + 1]
                    to_node = nodes_by_id[lane.to_node_id]
                    if not to_node.active:
                        continue
                    int_handling_mins, int_handling_end, int_delay_res = compute_node_handling_delay(
                        to_node,
                        next_lane.mode,
                        arr_utc,
                        events,
                        evaluation_clock_utc,
                    )
                    next_ready = int_handling_end

                leg_record = CandidateLeg(
                    lane=lane,
                    departure_utc=dep_utc,
                    arrival_utc=arr_utc,
                    ready_before_wait_utc=ready_for_dep_utc,
                    missed_earlier_cutoff=missed_earlier_departure_at_visit,
                    travel_chunks=chunks,
                    travel_delay_res=trav_delay_res,
                    intermediate_handling_minutes=int_handling_mins,
                    intermediate_handling_end_utc=int_handling_end,
                    intermediate_handling_delay_res=int_delay_res,
                )

                accum_legs.append(leg_record)
                search_legs(leg_idx + 1, next_ready, accum_legs)
                accum_legs.pop()

                # In scheduled transit, earliest eligible departure on a given lane usually dominates;
                # however, section 1 says: explore every eligible departure sequence inside horizon;
                # we limit branching if a later departure arrives after an already found complete route.
                if best_candidate is not None and arr_utc >= best_candidate.final_arrival_utc:
                    break

    search_legs(0, orig_handling_end_utc, [])
    return best_candidate

def candidate_to_route(cand: CandidateRoute, ready_at_utc: datetime, nodes_by_id: dict[str, Node]) -> Route:
    """Assemble CandidateRoute into canonical Route model with contiguous segments."""
    lane_ids = [lane.id for lane in cand.path_lanes]
    departure_times = [to_iso_utc(leg.departure_utc) for leg in cand.legs]
    arrival_iso = to_iso_utc(cand.final_arrival_utc)
    total_minutes = minutes_between(ready_at_utc, cand.final_arrival_utc)
    transfer_count = len(lane_ids) - 1

    segments: list[Segment] = []
    seg_idx = 0

    # 1. Origin handling
    origin_node = nodes_by_id[cand.path_lanes[0].from_node_id]
    orig_seg = build_handling_segment(
        seg_idx,
        origin_node.id,
        origin_node.name,
        ready_at_utc,
        cand.origin_handling_end_utc,
        origin_node.processing_minutes,
        cand.origin_handling_delay_res,
    )
    if orig_seg:
        segments.append(orig_seg)
        seg_idx += 1

    # 2. Legs
    for i, leg in enumerate(cand.legs):
        from_node = nodes_by_id[leg.lane.from_node_id]
        
        # Departure wait segment
        if leg.departure_utc > leg.ready_before_wait_utc:
            wait_seg = build_wait_segment(
                seg_idx,
                from_node.id,
                from_node.name,
                leg.ready_before_wait_utc,
                leg.departure_utc,
                leg.missed_earlier_cutoff,
            )
            if wait_seg:
                segments.append(wait_seg)
                seg_idx += 1

        # Travel segments
        trav_segs = build_travel_segments(
            seg_idx,
            leg.lane.id,
            leg.travel_chunks,
            leg.lane.duration_minutes,
            leg.travel_delay_res,
        )
        segments.extend(trav_segs)
        seg_idx += len(trav_segs)

        # Intermediate handling segment
        if i + 1 < len(cand.legs) and leg.intermediate_handling_end_utc:
            to_node = nodes_by_id[leg.lane.to_node_id]
            int_seg = build_handling_segment(
                seg_idx,
                to_node.id,
                to_node.name,
                leg.arrival_utc,
                leg.intermediate_handling_end_utc,
                to_node.processing_minutes,
                leg.intermediate_handling_delay_res or DelayGroupResult(0, {}, [], []),
            )
            if int_seg:
                segments.append(int_seg)
                seg_idx += 1

    # Explanations
    explanation: list[str] = []
    # Origin delay note
    if cand.origin_handling_delay_res.total_extra_minutes > 0:
        for k, mins in cand.origin_handling_delay_res.group_maxima.items():
            explanation.append(f"Origin handling adds {mins} min at {origin_node.name}; group {k}.")
    for leg in cand.legs:
        if leg.travel_delay_res.total_extra_minutes > 0:
            for k, mins in leg.travel_delay_res.group_maxima.items():
                explanation.append(f"Traffic/weather adds {mins} min on lane {leg.lane.id}; group {k}.")
        for chunk in leg.travel_chunks:
            if chunk.is_calendar_pause:
                explanation.append(f"Calendar pause adds {chunk.duration_minutes} min on lane {leg.lane.id}.")

    route_id = compute_route_id(lane_ids, departure_times)

    return Route(
        id=route_id,
        lane_ids=lane_ids,
        departure_times=departure_times,
        arrival_at=arrival_iso,
        total_minutes=total_minutes,
        transfer_count=transfer_count,
        segments=segments,
        explanation=explanation,
    )

def search_routes(
    network: Network,
    request: SearchRequest,
    events: list[Event],
    evaluation_clock_utc: datetime,
) -> tuple[list[Route], list[Diagnostic]]:
    """
    Perform route search according to section 1 of docs/ROUTING_RULES.md.
    Returns (sorted_routes, diagnostics).
    """
    ready_at_utc = parse_iso_dt(request.ready_at)
    horizon_utc = ready_at_utc + timedelta(days=14)

    nodes_by_id = {n.id: n for n in network.nodes}
    lanes_by_from: dict[str, list[Lane]] = {}
    for lane in network.lanes:
        lanes_by_from.setdefault(lane.from_node_id, []).append(lane)

    origin_node = nodes_by_id.get(request.origin_id)
    dest_node = nodes_by_id.get(request.destination_id)

    diagnostics: list[Diagnostic] = []

    if not origin_node or not origin_node.active or not dest_node or not dest_node.active:
        diagnostics.append(
            Diagnostic(
                category="connectivity",
                code="INACTIVE_LANE",
                message="Origin or destination node is inactive or missing",
                target_id=request.origin_id if not origin_node or not origin_node.active else request.destination_id,
            )
        )
        return [], diagnostics

    profile = next((p for p in network.service_profiles if p.id == request.service_profile_id), None)
    if not profile:
        diagnostics.append(
            Diagnostic(
                category="profile",
                code="PROFILE_REJECTED",
                message=f"Service profile {request.service_profile_id} not found",
            )
        )
        return [], diagnostics

    allowed_modes = set(profile.allowed_modes)
    paths = find_paths(
        request.origin_id,
        request.destination_id,
        lanes_by_from,
        nodes_by_id,
        allowed_modes,
        profile.max_lanes,
    )

    if not paths:
        diagnostics.append(
            Diagnostic(
                category="connectivity",
                code="DISCONNECTED",
                message="No connected path between origin and destination with allowed modes",
            )
        )
        return [], diagnostics

    counter = [0]
    candidate_routes: list[CandidateRoute] = []

    for path in paths:
        try:
            cand = evaluate_path(
                path,
                nodes_by_id,
                events,
                network.calendar_rules,
                ready_at_utc,
                horizon_utc,
                evaluation_clock_utc,
                counter,
            )
            if cand is not None:
                candidate_routes.append(cand)
        except RuntimeError as e:
            if "SEARCH_LIMIT" in str(e):
                diagnostics.append(
                    Diagnostic(
                        category="limit",
                        code="SEARCH_LIMIT",
                        message="Search limit of 50,000 transitions exceeded",
                    )
                )
                return [], diagnostics
            raise

    if not candidate_routes:
        diagnostics.append(
            Diagnostic(
                category="closure",
                code="CLOSED_LANE",
                message="No feasible route found inside search horizon under current conditions",
            )
        )
        return [], diagnostics

    # Convert candidates to canonical Route models
    routes = [candidate_to_route(c, ready_at_utc, nodes_by_id) for c in candidate_routes]

    # Deterministic tie breaking:
    # 1. arrival_at (UTC datetime)
    # 2. transfer_count
    # 3. ','.join(lane_ids)
    # 4. departure_times sequence
    routes.sort(
        key=lambda r: (
            parse_iso_dt(r.arrival_at),
            r.transfer_count,
            ",".join(r.lane_ids),
            r.departure_times,
        )
    )

    return routes[: request.max_results], diagnostics
