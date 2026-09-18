"""OriginProgress and saved-plan progression adhering to docs/ROUTING_RULES.md Section 10."""
from datetime import datetime, timedelta, timezone
from typing import Optional
from ..domain.models import (
    OriginProgress,
    Segment,
    Route,
    Lane,
    Node,
    Network,
    Event,
    SearchRequest,
    Reason,
)
from .time_utils import parse_iso_dt, to_iso_utc, minutes_between
from .events import compute_node_handling_delay, compute_lane_travel_delay_and_chunks, is_lane_blocked_by_closure, DelayGroupResult
from .calendar import TravelChunk
from .timeline import build_handling_segment, build_wait_segment, build_travel_segments

def update_origin_progress(
    plan_id: str,
    previous_projection: Route,
    original_ready_at_utc: datetime,
    new_evaluation_clock_utc: datetime,
    origin_node: Node,
    first_lane: Lane,
    prior_progress: Optional[OriginProgress] = None,
) -> OriginProgress:
    """
    Materialize the origin timeline prefix from the previous projection up to the new evaluation instant,
    capped before first departure. Freeze already elapsed handling and waiting.
    """
    first_departure_utc = parse_iso_dt(previous_projection.departure_times[0])
    cap_utc = min(new_evaluation_clock_utc, first_departure_utc)

    if new_evaluation_clock_utc <= original_ready_at_utc:
        return OriginProgress(
            plan_id=plan_id,
            recorded_at=to_iso_utc(new_evaluation_clock_utc),
            frozen_segments=[],
            completed_work_minutes=0,
            handling_complete=False,
            first_mode=first_lane.mode,
        )

    frozen_segments: list[Segment] = []
    completed_work = 0
    handling_done = False

    # Iterate over segments from previous projection
    for seg in previous_projection.segments:
        seg_start = parse_iso_dt(seg.start_at)
        seg_end = parse_iso_dt(seg.end_at)

        if seg_start >= cap_utc:
            break

        # Only origin segments (handling at origin node or wait at origin node)
        if seg.node_id != origin_node.id:
            break

        if seg_end <= cap_utc:
            frozen_segments.append(seg)
            if seg.type == "handle":
                completed_work += seg.duration_minutes
        else:
            # Boundary split
            split_duration = minutes_between(seg_start, cap_utc)
            if split_duration > 0:
                # Apportion reasons for split
                split_reasons = []
                rem_to_allocate = split_duration
                for r in seg.reasons:
                    take = min(r.minutes, rem_to_allocate)
                    if take > 0:
                        split_reasons.append(
                            Reason(
                                code=r.code,
                                minutes=take,
                                description=r.description,
                                event_ids=r.event_ids,
                            )
                        )
                        rem_to_allocate -= take
                    if rem_to_allocate <= 0:
                        break

                split_seg = Segment(
                    segment_index=seg.segment_index,
                    type=seg.type,
                    node_id=seg.node_id,
                    lane_id=seg.lane_id,
                    start_at=seg.start_at,
                    end_at=to_iso_utc(cap_utc),
                    duration_minutes=split_duration,
                    reasons=split_reasons,
                )
                frozen_segments.append(split_seg)
                if seg.type == "handle":
                    completed_work += split_duration
            break

    # If completed work reached the handling duration in previous projection
    handling_segs = [s for s in previous_projection.segments if s.type == "handle" and s.node_id == origin_node.id]
    total_handling_needed = sum(s.duration_minutes for s in handling_segs)
    if completed_work >= total_handling_needed and total_handling_needed > 0:
        handling_done = True

    return OriginProgress(
        plan_id=plan_id,
        recorded_at=to_iso_utc(new_evaluation_clock_utc),
        frozen_segments=frozen_segments,
        completed_work_minutes=completed_work,
        handling_complete=handling_done,
        first_mode=first_lane.mode,
    )

def evaluate_selected_projection(
    selected_itinerary: Route,
    network: Network,
    events: list[Event],
    original_ready_at_utc: datetime,
    evaluation_clock_utc: datetime,
    progress: Optional[OriginProgress],
) -> tuple[Optional[Route], list[str]]:
    """
    Re-evaluate the fixed lane and departure sequence of a saved plan under current events/clock.
    Returns (updated_projection_route_or_none, review_reasons).
    """
    review_reasons: list[str] = []
    first_departure_utc = parse_iso_dt(selected_itinerary.departure_times[0])

    if evaluation_clock_utc >= first_departure_utc:
        return None, ["Departed or reached departure: outside demo scope"]

    nodes_by_id = {n.id: n for n in network.nodes}
    lanes_by_id = {l.id: l for l in network.lanes}

    # Check endpoints and intermediate nodes
    for lane_id in selected_itinerary.lane_ids:
        lane = lanes_by_id.get(lane_id)
        if not lane or not lane.active:
            return None, [f"Lane {lane_id} is inactive or deleted"]
        fn = nodes_by_id.get(lane.from_node_id)
        tn = nodes_by_id.get(lane.to_node_id)
        if not fn or not fn.active:
            return None, [f"Origin/hub node {lane.from_node_id} is inactive"]
        if not tn or not tn.active:
            return None, [f"Destination/hub node {lane.to_node_id} is inactive"]

    first_lane = lanes_by_id[selected_itinerary.lane_ids[0]]
    origin_node = nodes_by_id[first_lane.from_node_id]

    # Calculate origin handling
    # Compute total origin work required under current node rules & events
    total_handling_mins, orig_end_utc, orig_delay_res = compute_node_handling_delay(
        origin_node,
        first_lane.mode,
        original_ready_at_utc,
        events,
        evaluation_clock_utc,
    )

    completed_mins = progress.completed_work_minutes if progress else 0
    remaining_work = max(0, total_handling_mins - completed_mins)

    # Start only remaining work at max(evaluation_at, original_ready_at)
    effective_start = max(evaluation_clock_utc, original_ready_at_utc)
    remaining_handling_end_utc = effective_start + timedelta(minutes=remaining_work)

    # First departure cut-off check for already booked shipment:
    # "Passing that cut-off while waiting does not cancel an already booked shipment.
    # Delays that make its handling finish after the actual departure invalidate it."
    if remaining_handling_end_utc > first_departure_utc:
        return None, ["Handling completion finishes after booked first departure"]

    # Now evaluate legs
    legs_chunks: list[tuple[datetime, datetime, list[TravelChunk], DelayGroupResult]] = []
    current_ready_for_dep = remaining_handling_end_utc

    for i, lane_id in enumerate(selected_itinerary.lane_ids):
        lane = lanes_by_id[lane_id]
        dep_utc = parse_iso_dt(selected_itinerary.departure_times[i])

        if i > 0:
            # Intermediate leg: check cutoff
            dep_rule = next((d for d in lane.departures if expand_departure(dep_utc.date(), d.local_time, nodes_by_id[lane.from_node_id].timezone) == dep_utc), None)
            cutoff_mins = dep_rule.cutoff_minutes if dep_rule else 30
            cutoff_utc = dep_utc - timedelta(minutes=cutoff_mins)
            if current_ready_for_dep > cutoff_utc:
                return None, [f"Connection missed on lane {lane_id}: ready at {current_ready_for_dep} after cutoff {cutoff_utc}"]

        # Travel delay
        horizon_utc = original_ready_at_utc + timedelta(days=14)
        work, arr_utc, chunks, trav_delay_res = compute_lane_travel_delay_and_chunks(
            lane, dep_utc, events, network.calendar_rules, evaluation_clock_utc, horizon_utc
        )

        if is_lane_blocked_by_closure(lane, dep_utc, arr_utc, events, evaluation_clock_utc):
            return None, [f"Lane {lane_id} is closed by incident during traversal"]

        legs_chunks.append((dep_utc, arr_utc, chunks, trav_delay_res))
        current_ready_for_dep = arr_utc

        if i + 1 < len(selected_itinerary.lane_ids):
            to_node = nodes_by_id[lane.to_node_id]
            next_lane = lanes_by_id[selected_itinerary.lane_ids[i + 1]]
            int_mins, int_end, int_delay = compute_node_handling_delay(
                to_node, next_lane.mode, arr_utc, events, evaluation_clock_utc
            )
            current_ready_for_dep = int_end

    final_arrival_utc = legs_chunks[-1][1]
    total_minutes = minutes_between(original_ready_at_utc, final_arrival_utc)

    # Assemble segments:
    segments: list[Segment] = []
    seg_idx = 0

    # Include frozen prefix if any
    if progress and progress.frozen_segments:
        for f_seg in progress.frozen_segments:
            segments.append(
                Segment(
                    segment_index=seg_idx,
                    type=f_seg.type,
                    node_id=f_seg.node_id,
                    lane_id=f_seg.lane_id,
                    start_at=f_seg.start_at,
                    end_at=f_seg.end_at,
                    duration_minutes=f_seg.duration_minutes,
                    reasons=f_seg.reasons,
                )
            )
            seg_idx += 1

    # Remaining origin handling segment
    if remaining_work > 0:
        rem_handling_seg = build_handling_segment(
            seg_idx,
            origin_node.id,
            origin_node.name,
            effective_start,
            remaining_handling_end_utc,
            remaining_work,
            DelayGroupResult(0, {}, [], []),
        )
        if rem_handling_seg:
            segments.append(rem_handling_seg)
            seg_idx += 1

    # Wait until first departure
    if legs_chunks[0][0] > remaining_handling_end_utc:
        w_seg = build_wait_segment(
            seg_idx,
            origin_node.id,
            origin_node.name,
            remaining_handling_end_utc,
            legs_chunks[0][0],
            missed_earlier_cutoff=False,
        )
        if w_seg:
            segments.append(w_seg)
            seg_idx += 1

    # Legs
    for i, (dep_utc, arr_utc, chunks, trav_delay) in enumerate(legs_chunks):
        lane_id = selected_itinerary.lane_ids[i]
        lane = lanes_by_id[lane_id]
        trav_segs = build_travel_segments(
            seg_idx,
            lane_id,
            chunks,
            lane.duration_minutes,
            trav_delay,
        )
        segments.extend(trav_segs)
        seg_idx += len(trav_segs)

        if i + 1 < len(legs_chunks):
            # Intermediate handling
            to_node = nodes_by_id[lane.to_node_id]
            next_lane = lanes_by_id[selected_itinerary.lane_ids[i + 1]]
            int_mins, int_end, int_delay = compute_node_handling_delay(
                to_node, next_lane.mode, arr_utc, events, evaluation_clock_utc
            )
            int_seg = build_handling_segment(
                seg_idx,
                to_node.id,
                to_node.name,
                arr_utc,
                int_end,
                to_node.processing_minutes,
                int_delay,
            )
            if int_seg:
                segments.append(int_seg)
                seg_idx += 1
            next_dep_utc = legs_chunks[i + 1][0]
            if next_dep_utc > int_end:
                w_seg = build_wait_segment(
                    seg_idx,
                    to_node.id,
                    to_node.name,
                    int_end,
                    next_dep_utc,
                    missed_earlier_cutoff=False,
                )
                if w_seg:
                    segments.append(w_seg)
                    seg_idx += 1

    route = Route(
        id=selected_itinerary.id,
        lane_ids=selected_itinerary.lane_ids,
        departure_times=selected_itinerary.departure_times,
        arrival_at=to_iso_utc(final_arrival_utc),
        total_minutes=total_minutes,
        transfer_count=selected_itinerary.transfer_count,
        segments=segments,
        explanation=selected_itinerary.explanation,
    )
    return route, review_reasons
