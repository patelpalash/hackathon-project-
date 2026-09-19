"""Plan service managing saved plans, synchronous recalculation, and manager decisions."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from ..domain.models import (
    PlanView,
    Route,
    SearchRequest,
    SearchResponse,
    Snapshot,
    Decision,
    ReviewEvidence,
    DecisionRequest,
)
from ..storage.repository import Repository, ConcurrencyError
from ..engine.time_utils import parse_iso_dt, to_iso_utc, minutes_between
from ..engine.route_search import search_routes
from ..engine.origin_progress import update_origin_progress, evaluate_selected_projection
from ..engine.events import is_event_applicable

EARLIER_ALTERNATIVE_THRESHOLD_MINUTES = 30
MAX_DEMO_PLANS = 25

class PlanService:
    def __init__(self, repo: Repository):
        self.repo = repo

    def create_plan_from_search(
        self,
        mutation_id: str,
        expected_snapshot: Snapshot,
        search_id: str,
        route_id: str,
        name: str,
    ) -> PlanView:
        # Check idempotency
        cached = self.repo.check_idempotency(mutation_id, {"search_id": search_id, "route_id": route_id, "name": name})
        if cached:
            return PlanView.model_validate(cached)

        self.repo.verify_snapshot(expected_snapshot)

        # Check demo plan limit
        existing_plans = self.repo.get_plans()
        if len(existing_plans) >= MAX_DEMO_PLANS:
            raise ConcurrencyError("DEMO_PLAN_LIMIT", f"Demo plan limit of {MAX_DEMO_PLANS} reached")

        search_data = self.repo.get_search(search_id)
        if not search_data:
            raise ConcurrencyError("NOT_FOUND", f"Stored search {search_id} not found")

        req, resp, stored_snap = search_data
        # Ensure search snapshot matches current
        if stored_snap != expected_snapshot:
            raise ConcurrencyError("STALE_SNAPSHOT", "Search was performed against an earlier snapshot; please repeat search")

        selected_route = next((r for r in resp.routes if r.id == route_id), None)
        if not selected_route:
            raise ConcurrencyError("NOT_FOUND", f"Route {route_id} not found in search results")

        now_iso = to_iso_utc(datetime.now(timezone.utc))
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"

        # Initial alternatives from search
        alts = [r for r in resp.routes if r.id != route_id]

        plan = PlanView(
            plan_id=plan_id,
            name=name.strip(),
            status="stable",
            created_at=now_iso,
            updated_at=now_iso,
            request=req,
            selected_itinerary=selected_route,
            selected_projection=selected_route,
            alternative_recommendations=alts,
            decisions_count=0,
            latest_decision=None,
            plan_revision=1,
            review_reasons=[],
            origin_progress=None,
        )

        self.repo.save_plan(plan, increment_plans_revision=True)
        self.repo.record_receipt(mutation_id, {"search_id": search_id, "route_id": route_id, "name": name}, plan.model_dump())
        self.repo.conn.commit()
        return plan

    def recompute_all_plans(self) -> int:
        """
        Synchronously recalculate all saved plans on any mutation (event, schedule, clock).
        Returns number of plans whose computed state changed.
        """
        plans = self.repo.get_plans()
        if not plans:
            return 0

        network = self.repo.get_network()
        events = self.repo.get_events()
        state = self.repo.get_state()
        clock_utc = parse_iso_dt(state.simulation_clock)

        nodes_by_id = {n.id: n for n in network.nodes}
        lanes_by_id = {l.id: l for l in network.lanes}

        changed_count = 0
        now_iso = to_iso_utc(datetime.now(timezone.utc))

        for plan in plans:
            old_dump = plan.model_dump(exclude={"updated_at"})
            first_dep_utc = parse_iso_dt(plan.selected_itinerary.departure_times[0])

            # Check outside_demo_scope
            if clock_utc >= first_dep_utc:
                plan.status = "outside_demo_scope"
                plan.selected_projection = None
                plan.review_reasons = ["First departure time reached or passed: outside demo scope"]
                plan.alternative_recommendations = []
            else:
                # Update origin progress
                first_lane = lanes_by_id.get(plan.selected_itinerary.lane_ids[0])
                origin_node = nodes_by_id.get(plan.request.origin_id)
                if first_lane and origin_node:
                    ref_route = plan.selected_projection or plan.selected_itinerary
                    progress = update_origin_progress(
                        plan.plan_id,
                        ref_route,
                        parse_iso_dt(plan.request.ready_at),
                        clock_utc,
                        origin_node,
                        first_lane,
                        plan.origin_progress,
                    )
                    plan.origin_progress = progress

                # Re-evaluate selected projection
                proj, review_reasons = evaluate_selected_projection(
                    plan.selected_itinerary,
                    network,
                    events,
                    parse_iso_dt(plan.request.ready_at),
                    clock_utc,
                    plan.origin_progress,
                )
                plan.selected_projection = proj

                # Search alternatives
                # Section 10: internal recomputation does not check ready_at >= clock
                routes, diags = search_routes(network, plan.request, events, clock_utc)
                alts = [r for r in routes if r.id != plan.selected_itinerary.id]
                plan.alternative_recommendations = alts

                # Status determination
                if proj is None:
                    # Selected is infeasible
                    if alts:
                        plan.status = "review_required"
                        review_reasons.append("Current itinerary is infeasible under updated conditions; alternatives available.")
                    else:
                        plan.status = "blocked"
                        review_reasons.append("Current itinerary is infeasible and no alternative paths exist.")
                else:
                    # Selected is feasible
                    # Check deadline
                    deadline_breached = False
                    if plan.request.arrival_deadline:
                        dl_dt = parse_iso_dt(plan.request.arrival_deadline)
                        if parse_iso_dt(proj.arrival_at) > dl_dt:
                            deadline_breached = True
                            review_reasons.append("Projected arrival breaches the arrival deadline.")

                    # Check 30-minute threshold: is an alternative at least 30 mins earlier?
                    earlier_alt = False
                    proj_arr = parse_iso_dt(proj.arrival_at)
                    for alt in alts:
                        alt_arr = parse_iso_dt(alt.arrival_at)
                        if minutes_between(alt_arr, proj_arr) >= EARLIER_ALTERNATIVE_THRESHOLD_MINUTES:
                            earlier_alt = True
                            review_reasons.append(f"Alternative {alt.id[:8]} arrives at least 30 minutes earlier ({alt.arrival_at}).")
                            break

                    if deadline_breached or earlier_alt:
                        plan.status = "review_required"
                    else:
                        plan.status = "stable"

                plan.review_reasons = review_reasons

            new_dump = plan.model_dump(exclude={"updated_at"})
            if old_dump != new_dump:
                plan.plan_revision += 1
                plan.updated_at = now_iso
                self.repo.save_plan(plan, increment_plans_revision=False)
                changed_count += 1

        if changed_count > 0:
            self.repo.conn.execute("UPDATE app_state SET plans_revision = plans_revision + 1 WHERE id = 1;")
            self.repo.conn.commit()

        return changed_count

    def apply_decision(
        self,
        plan_id: str,
        mutation_id: str,
        expected_snapshot: Snapshot,
        expected_plan_revision: int,
        actor: str,
        action: str,
        reason: str,
        route_id: Optional[str] = None,
    ) -> tuple[PlanView, Decision]:
        # Idempotency
        cached = self.repo.check_idempotency(mutation_id, {
            "plan_id": plan_id,
            "action": action,
            "reason": reason,
            "route_id": route_id,
        })
        if cached:
            return PlanView.model_validate(cached["plan"]), Decision.model_validate(cached["decision"])

        self.repo.verify_snapshot(expected_snapshot)

        plan = self.repo.get_plan(plan_id)
        if not plan:
            raise ConcurrencyError("NOT_FOUND", f"Plan {plan_id} not found")

        if plan.plan_revision != expected_plan_revision:
            raise ConcurrencyError(
                "STALE_PLAN",
                f"Plan revision changed (expected {expected_plan_revision}, current {plan.plan_revision}). Refresh before deciding.",
                current_snapshot=self.repo.get_snapshot(),
            )

        if plan.status == "outside_demo_scope":
            raise ConcurrencyError("OUTSIDE_DEMO_SCOPE", "Cannot modify or review a plan that has departed or is outside demo scope")

        if not reason or len(reason.strip()) < 3:
            raise ConcurrencyError("VALIDATION_ERROR", "A reason of at least 3 nonblank characters is required")

        superseded_route_id = plan.selected_itinerary.id
        selected_route_id = None
        proposed_itinerary: Optional[Route] = None
        now_iso = to_iso_utc(datetime.now(timezone.utc))

        if action == "accept_route":
            if not route_id:
                raise ConcurrencyError("VALIDATION_ERROR", "route_id is required when action is accept_route")
            target_route = next((r for r in plan.alternative_recommendations if r.id == route_id), None)
            if not target_route:
                raise ConcurrencyError("VALIDATION_ERROR", f"route_id {route_id} not found among current recommendations")

            # Update plan selection
            plan.selected_itinerary = target_route
            plan.selected_projection = target_route
            plan.status = "stable"
            plan.review_reasons = []
            selected_route_id = target_route.id
            proposed_itinerary = target_route

        elif action == "keep_selected":
            if route_id is not None:
                raise ConcurrencyError("VALIDATION_ERROR", "route_id must be null for keep_selected")
            if plan.selected_projection is None:
                raise ConcurrencyError("ROUTE_INFEASIBLE", "Cannot keep current route because it is infeasible under current conditions")
            # Dismisses review
            plan.status = "stable"
            selected_route_id = plan.selected_itinerary.id

        elif action == "defer":
            if route_id is not None:
                raise ConcurrencyError("VALIDATION_ERROR", "route_id must be null for defer")
            # Keeps current status, records acknowledgment
        else:
            raise ConcurrencyError("VALIDATION_ERROR", f"Invalid decision action {action}")

        # Assemble immutable ReviewEvidence
        network = self.repo.get_network()
        state = self.repo.get_state()
        clock_utc = parse_iso_dt(state.simulation_clock)
        applicable_events = [e for e in self.repo.get_events() if is_event_applicable(e, clock_utc)]

        evidence = ReviewEvidence(
            reviewed_snapshot=expected_snapshot,
            selected_itinerary=plan.selected_itinerary,
            selected_projection=plan.selected_projection,
            proposed_itinerary=proposed_itinerary,
            network_snapshot=network,
            applied_event_versions=[{"event_id": e.id, "version": e.version} for e in applicable_events],
            observation_ids=[e.observation_id for e in applicable_events if e.observation_id],
        )

        decision_id = f"dec-{uuid.uuid4().hex[:8]}"
        decision = Decision(
            id=decision_id,
            plan_id=plan.plan_id,
            actor=actor.strip(),
            action=action,
            reason=reason.strip(),
            selected_route_id=selected_route_id,
            superseded_route_id=superseded_route_id if action == "accept_route" else None,
            decided_at=now_iso,
            review_evidence=evidence,
        )

        plan.decisions_count += 1
        plan.latest_decision = decision
        plan.plan_revision += 1
        plan.updated_at = now_iso

        self.repo.insert_decision(decision)
        self.repo.save_plan(plan, increment_plans_revision=True)

        resp = {"plan": plan.model_dump(), "decision": decision.model_dump(), "mutation_id": mutation_id}
        self.repo.record_receipt(mutation_id, {
            "plan_id": plan_id,
            "action": action,
            "reason": reason,
            "route_id": route_id,
        }, resp)
        self.repo.conn.commit()

        return plan, decision
