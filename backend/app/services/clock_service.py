"""Simulation clock service adhering to docs/BUILD_SPEC.md."""
from datetime import datetime
from ..domain.models import State, Snapshot
from ..storage.repository import Repository, ConcurrencyError
from ..engine.time_utils import parse_iso_dt, to_iso_utc
from .plan_service import PlanService

class ClockService:
    def __init__(self, repo: Repository, plan_service: PlanService):
        self.repo = repo
        self.plan_service = plan_service

    def advance_demo_clock(
        self,
        mutation_id: str,
        expected_snapshot: Snapshot,
        target_clock_iso: str,
    ) -> State:
        # Check idempotency
        cached = self.repo.check_idempotency(mutation_id, {"target_clock": target_clock_iso})
        if cached:
            return State.model_validate(cached)

        self.repo.verify_snapshot(expected_snapshot)

        state = self.repo.get_state()
        if state.mode != "demo":
            raise ConcurrencyError("MODE_MISMATCH", "Cannot manually advance clock in live mode")

        current_dt = parse_iso_dt(state.simulation_clock)
        target_dt = parse_iso_dt(target_clock_iso)

        if target_dt < current_dt:
            raise ConcurrencyError("VALIDATION_ERROR", f"Simulation clock cannot go backward: current {state.simulation_clock}, target {target_clock_iso}")

        if target_dt == current_dt:
            # No-op, preserves revision
            resp = state.model_dump()
            self.repo.record_receipt(mutation_id, {"target_clock": target_clock_iso}, resp)
            self.repo.conn.commit()
            return state

        # Forward clock change: update simulation_clock and increment clock_revision
        norm_target_iso = to_iso_utc(target_dt)
        new_state = self.repo.advance_clock(norm_target_iso)

        # Recompute all plans synchronously
        self.plan_service.recompute_all_plans()

        final_state = self.repo.get_state()
        self.repo.record_receipt(mutation_id, {"target_clock": target_clock_iso}, final_state.model_dump())
        self.repo.conn.commit()
        return final_state
