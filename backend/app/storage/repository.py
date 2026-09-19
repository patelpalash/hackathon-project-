"""Repository implementing durable transactions, snapshot checking and idempotency."""
import sqlite3
import os
import json
import hashlib
import uuid
from typing import Any, Optional
from datetime import datetime, timezone

from ..domain.models import (
    Snapshot,
    State,
    Node,
    Lane,
    CalendarRule,
    ServiceProfile,
    Network,
    Event,
    EventInput,
    PlanView,
    Decision,
    ReviewEvidence,
    OriginProgress,
    Observation,
    LaneGeometry,
    MapGeometry,
    ProviderStatus,
    Integrations,
    SourceSummary,
    CapacityExample,
    DataSummary,
    SearchRequest,
    SearchResponse,
    DepartureRule,
    Geometry,
    Route,
)
from ..engine.time_utils import parse_iso_dt, to_iso_utc

class ConcurrencyError(Exception):
    def __init__(self, code: str, message: str, current_snapshot: Optional[Snapshot] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.current_snapshot = current_snapshot

class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_state(self) -> State:
        cur = self.conn.execute("SELECT * FROM app_state WHERE id = 1;")
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Database not initialized: app_state missing")
        snap = Snapshot(
            dataset_id=row["dataset_id"],
            schedule_revision=row["schedule_revision"],
            event_revision=row["event_revision"],
            clock_revision=row["clock_revision"],
        )
        return State(
            api_version="2.0.0",
            snapshot=snap,
            simulation_clock=row["simulation_clock"],
            demo_mode=(row["mode"] == "demo"),
            mode=row["mode"],
            plans_revision=row["plans_revision"],
            integrations_revision=row["integrations_revision"],
        )

    def get_snapshot(self) -> Snapshot:
        return self.get_state().snapshot

    def verify_snapshot(self, expected: Snapshot):
        current = self.get_snapshot()
        if (
            current.dataset_id != expected.dataset_id
            or current.schedule_revision != expected.schedule_revision
            or current.event_revision != expected.event_revision
            or current.clock_revision != expected.clock_revision
        ):
            raise ConcurrencyError(
                code="STALE_SNAPSHOT",
                message="Conditions changed. Refresh before submitting.",
                current_snapshot=current,
            )

    def compute_request_hash(self, req_obj: Any) -> str:
        data = req_obj.model_dump(mode="json") if hasattr(req_obj, "model_dump") else req_obj
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def check_idempotency(self, mutation_id: str, req_obj: Any) -> Optional[dict]:
        cur = self.conn.execute("SELECT request_hash, response_json FROM mutation_receipts WHERE mutation_id = ?;", (mutation_id,))
        row = cur.fetchone()
        if not row:
            return None
        current_hash = self.compute_request_hash(req_obj)
        if row["request_hash"] != current_hash:
            raise ConcurrencyError(
                code="IDEMPOTENCY_CONFLICT",
                message=f"Mutation ID {mutation_id} reused with different request payload",
                current_snapshot=self.get_snapshot(),
            )
        return json.loads(row["response_json"])

    def record_receipt(self, mutation_id: str, req_obj: Any, resp_dict: dict):
        req_hash = self.compute_request_hash(req_obj)
        resp_json = json.dumps(resp_dict, sort_keys=True, separators=(",", ":"))
        now_iso = to_iso_utc(datetime.now(timezone.utc))
        self.conn.execute(
            "INSERT INTO mutation_receipts (mutation_id, request_hash, response_json, created_at) VALUES (?, ?, ?, ?);",
            (mutation_id, req_hash, resp_json, now_iso),
        )

    def get_network(self) -> Network:
        snap = self.get_snapshot()
        # Nodes
        nodes = []
        for r in self.conn.execute("SELECT * FROM nodes ORDER BY id;"):
            nodes.append(
                Node(
                    id=r["id"],
                    name=r["name"],
                    type=r["type"],
                    country=r["country"],
                    timezone=r["timezone"],
                    latitude=r["latitude"],
                    longitude=r["longitude"],
                    processing_minutes=r["processing_minutes"],
                    active=bool(r["active"]),
                    provenance=r["provenance"],
                )
            )
        # Lanes
        lanes = []
        for r in self.conn.execute("SELECT * FROM lanes ORDER BY id;"):
            deps_raw = json.loads(r["departures_json"])
            deps = [DepartureRule.model_validate(d) for d in deps_raw]
            lanes.append(
                Lane(
                    id=r["id"],
                    from_node_id=r["from_node_id"],
                    to_node_id=r["to_node_id"],
                    mode=r["mode"],
                    duration_minutes=r["duration_minutes"],
                    active=bool(r["active"]),
                    valid_from=r["valid_from"],
                    valid_to=r["valid_to"],
                    departures=deps,
                    provenance=r["provenance"],
                )
            )
        # Calendar rules
        cal_rules = []
        for r in self.conn.execute("SELECT * FROM calendar_rules ORDER BY id;"):
            cal_rules.append(
                CalendarRule(
                    id=r["id"],
                    lane_id=r["lane_id"],
                    mode=r["mode"],
                    timezone=r["timezone"],
                    weekday=r["weekday"],
                    start_local_time=r["start_local_time"],
                    end_next_day_local_time=r["end_next_day_local_time"],
                    action=r["action"],
                    provenance=r["provenance"],
                )
            )
        # Service profiles
        profiles = []
        for r in self.conn.execute("SELECT * FROM service_profiles ORDER BY id;"):
            profiles.append(
                ServiceProfile(
                    id=r["id"],
                    allowed_modes=json.loads(r["allowed_modes_json"]),
                    max_lanes=r["max_lanes"],
                    scope=r["scope"],
                )
            )
        return Network(
            snapshot=snap,
            nodes=nodes,
            lanes=lanes,
            calendar_rules=cal_rules,
            service_profiles=profiles,
        )

    def update_node(self, node_id: str, active: Optional[bool], processing_minutes: Optional[int]) -> Node:
        cur = self.conn.execute("SELECT * FROM nodes WHERE id = ?;", (node_id,))
        row = cur.fetchone()
        if not row:
            raise ConcurrencyError("NOT_FOUND", f"Node {node_id} not found")

        new_active = row["active"] if active is None else (1 if active else 0)
        new_proc = row["processing_minutes"] if processing_minutes is None else processing_minutes

        self.conn.execute(
            "UPDATE nodes SET active = ?, processing_minutes = ? WHERE id = ?;",
            (new_active, new_proc, node_id),
        )
        self.conn.execute("UPDATE app_state SET schedule_revision = schedule_revision + 1 WHERE id = 1;")
        
        cur = self.conn.execute("SELECT * FROM nodes WHERE id = ?;", (node_id,))
        r = cur.fetchone()
        return Node(
            id=r["id"],
            name=r["name"],
            type=r["type"],
            country=r["country"],
            timezone=r["timezone"],
            latitude=r["latitude"],
            longitude=r["longitude"],
            processing_minutes=r["processing_minutes"],
            active=bool(r["active"]),
            provenance=r["provenance"],
        )

    def update_lane(self, lane_id: str, active: Optional[bool], duration_minutes: Optional[int], departures: Optional[list[DepartureRule]]) -> Lane:
        cur = self.conn.execute("SELECT * FROM lanes WHERE id = ?;", (lane_id,))
        row = cur.fetchone()
        if not row:
            raise ConcurrencyError("NOT_FOUND", f"Lane {lane_id} not found")

        new_active = row["active"] if active is None else (1 if active else 0)
        new_dur = row["duration_minutes"] if duration_minutes is None else duration_minutes
        new_deps = (
            row["departures_json"]
            if departures is None
            else json.dumps([d.model_dump() for d in departures])
        )

        self.conn.execute(
            "UPDATE lanes SET active = ?, duration_minutes = ?, departures_json = ? WHERE id = ?;",
            (new_active, new_dur, new_deps, lane_id),
        )
        self.conn.execute("UPDATE app_state SET schedule_revision = schedule_revision + 1 WHERE id = 1;")

        cur = self.conn.execute("SELECT * FROM lanes WHERE id = ?;", (lane_id,))
        r = cur.fetchone()
        return Lane(
            id=r["id"],
            from_node_id=r["from_node_id"],
            to_node_id=r["to_node_id"],
            mode=r["mode"],
            duration_minutes=r["duration_minutes"],
            active=bool(r["active"]),
            valid_from=r["valid_from"],
            valid_to=r["valid_to"],
            departures=[DepartureRule.model_validate(d) for d in json.loads(r["departures_json"])],
            provenance=r["provenance"],
        )

    def get_events(self) -> list[Event]:
        """Fetch latest version of each event."""
        sql = """
        SELECT e.* FROM event_versions e
        INNER JOIN (
            SELECT event_id, MAX(version) as max_v
            FROM event_versions
            GROUP BY event_id
        ) m ON e.event_id = m.event_id AND e.version = m.max_v
        ORDER BY e.observed_at ASC, e.event_id ASC;
        """
        events = []
        for r in self.conn.execute(sql):
            events.append(
                Event(
                    id=r["event_id"],
                    version=r["version"],
                    type=r["type"],
                    source_kind=r["source_kind"],
                    external_id=r["external_id"],
                    source_reference=r["source_reference"],
                    observed_at=r["observed_at"],
                    valid_from=r["valid_from"],
                    valid_until=r["valid_until"],
                    review_due_at=r["review_due_at"],
                    target_kind=r["target_kind"],
                    target_id=r["target_id"],
                    mode=r["mode"],
                    effect_type=r["effect_type"],
                    effect_minutes=r["effect_minutes"],
                    verification_status=r["verification_status"],
                    lifecycle_status=r["lifecycle_status"],
                    correlation_key=r["correlation_key"],
                    reason=r["reason"],
                    reported_by=r["reported_by"],
                    received_at=r["received_at"],
                    review_overdue=bool(r["review_overdue"]),
                    applies_to_departure_at=r["applies_to_departure_at"],
                    observation_id=r["observation_id"],
                )
            )
        return events

    def insert_event_version(self, event_id: str, version: int, inp: EventInput, reported_by: str) -> Event:
        now_iso = to_iso_utc(datetime.now(timezone.utc))
        review_overdue = False
        if inp.review_due_at:
            state = self.get_state()
            clock_dt = parse_iso_dt(state.simulation_clock)
            due_dt = parse_iso_dt(inp.review_due_at)
            review_overdue = (clock_dt > due_dt)

        self.conn.execute(
            """
            INSERT INTO event_versions (
                event_id, version, type, source_kind, external_id, source_reference,
                observed_at, valid_from, valid_until, review_due_at,
                target_kind, target_id, mode, effect_type, effect_minutes,
                verification_status, lifecycle_status, correlation_key, reason,
                reported_by, received_at, review_overdue, applies_to_departure_at, observation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                event_id,
                version,
                inp.type,
                inp.source_kind,
                inp.external_id,
                inp.source_reference,
                inp.observed_at,
                inp.valid_from,
                inp.valid_until,
                inp.review_due_at,
                inp.target_kind,
                inp.target_id,
                inp.mode,
                inp.effect_type,
                inp.effect_minutes,
                inp.verification_status,
                inp.lifecycle_status,
                inp.correlation_key,
                inp.reason,
                reported_by,
                now_iso,
                1 if review_overdue else 0,
                inp.applies_to_departure_at,
                inp.observation_id,
            ),
        )
        self.conn.execute("UPDATE app_state SET event_revision = event_revision + 1 WHERE id = 1;")

        return Event(
            id=event_id,
            version=version,
            type=inp.type,
            source_kind=inp.source_kind,
            external_id=inp.external_id,
            source_reference=inp.source_reference,
            observed_at=inp.observed_at,
            valid_from=inp.valid_from,
            valid_until=inp.valid_until,
            review_due_at=inp.review_due_at,
            target_kind=inp.target_kind,
            target_id=inp.target_id,
            mode=inp.mode,
            effect_type=inp.effect_type,
            effect_minutes=inp.effect_minutes,
            verification_status=inp.verification_status,
            lifecycle_status=inp.lifecycle_status,
            correlation_key=inp.correlation_key,
            reason=inp.reason,
            reported_by=reported_by,
            received_at=now_iso,
            review_overdue=review_overdue,
            applies_to_departure_at=inp.applies_to_departure_at,
            observation_id=inp.observation_id,
        )

    def store_search(self, search_id: str, req: SearchRequest, resp: SearchResponse):
        snap = self.get_snapshot()
        now_iso = to_iso_utc(datetime.now(timezone.utc))
        self.conn.execute(
            "INSERT INTO searches (search_id, request_json, response_json, snapshot_json, created_at) VALUES (?, ?, ?, ?, ?);",
            (
                search_id,
                json.dumps(req.model_dump()),
                json.dumps(resp.model_dump()),
                json.dumps(snap.model_dump()),
                now_iso,
            ),
        )

    def get_search(self, search_id: str) -> Optional[tuple[SearchRequest, SearchResponse, Snapshot]]:
        cur = self.conn.execute("SELECT request_json, response_json, snapshot_json FROM searches WHERE search_id = ?;", (search_id,))
        row = cur.fetchone()
        if not row:
            return None
        req = SearchRequest.model_validate_json(row["request_json"])
        resp = SearchResponse.model_validate_json(row["response_json"])
        snap = Snapshot.model_validate_json(row["snapshot_json"])
        return req, resp, snap

    def get_plans(self) -> list[PlanView]:
        plans = []
        for r in self.conn.execute("SELECT * FROM plans ORDER BY plan_id;"):
            plans.append(self._row_to_plan_view(r))
        return plans

    def get_plan(self, plan_id: str) -> Optional[PlanView]:
        cur = self.conn.execute("SELECT * FROM plans WHERE plan_id = ?;", (plan_id,))
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_plan_view(row)

    def _row_to_plan_view(self, r: sqlite3.Row) -> PlanView:
        return PlanView(
            plan_id=r["plan_id"],
            name=r["name"],
            status=r["status"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            request=SearchRequest.model_validate_json(r["request_json"]),
            selected_itinerary=Route.model_validate_json(r["selected_itinerary_json"]),
            selected_projection=Route.model_validate_json(r["selected_projection_json"]) if r["selected_projection_json"] else None,
            alternative_recommendations=[Route.model_validate(x) for x in json.loads(r["alternative_recommendations_json"])],
            decisions_count=r["decisions_count"],
            latest_decision=Decision.model_validate_json(r["latest_decision_json"]) if r["latest_decision_json"] else None,
            plan_revision=r["plan_revision"],
            review_reasons=json.loads(r["review_reasons_json"]),
            origin_progress=OriginProgress.model_validate_json(r["origin_progress_json"]) if r["origin_progress_json"] else None,
        )

    def save_plan(self, plan: PlanView, increment_plans_revision: bool = True):
        self.conn.execute(
            """
            INSERT INTO plans (
                plan_id, name, status, created_at, updated_at,
                request_json, selected_itinerary_json, selected_projection_json,
                alternative_recommendations_json, decisions_count, latest_decision_json,
                plan_revision, review_reasons_json, origin_progress_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(plan_id) DO UPDATE SET
                name = excluded.name,
                status = excluded.status,
                updated_at = excluded.updated_at,
                selected_itinerary_json = excluded.selected_itinerary_json,
                selected_projection_json = excluded.selected_projection_json,
                alternative_recommendations_json = excluded.alternative_recommendations_json,
                decisions_count = excluded.decisions_count,
                latest_decision_json = excluded.latest_decision_json,
                plan_revision = excluded.plan_revision,
                review_reasons_json = excluded.review_reasons_json,
                origin_progress_json = excluded.origin_progress_json;
            """,
            (
                plan.plan_id,
                plan.name,
                plan.status,
                plan.created_at,
                plan.updated_at,
                json.dumps(plan.request.model_dump()),
                json.dumps(plan.selected_itinerary.model_dump()),
                json.dumps(plan.selected_projection.model_dump()) if plan.selected_projection else None,
                json.dumps([r.model_dump() for r in plan.alternative_recommendations]),
                plan.decisions_count,
                json.dumps(plan.latest_decision.model_dump()) if plan.latest_decision else None,
                plan.plan_revision,
                json.dumps(plan.review_reasons),
                json.dumps(plan.origin_progress.model_dump()) if plan.origin_progress else None,
            ),
        )
        if increment_plans_revision:
            self.conn.execute("UPDATE app_state SET plans_revision = plans_revision + 1 WHERE id = 1;")

    def insert_decision(self, decision: Decision):
        self.conn.execute(
            """
            INSERT INTO decisions (
                id, plan_id, actor, action, reason,
                selected_route_id, superseded_route_id, decided_at, review_evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                decision.id,
                decision.plan_id,
                decision.actor,
                decision.action,
                decision.reason,
                decision.selected_route_id,
                decision.superseded_route_id,
                decision.decided_at,
                json.dumps(decision.review_evidence.model_dump()),
            ),
        )

    def get_decisions(self, plan_id: str) -> list[Decision]:
        decisions = []
        for r in self.conn.execute("SELECT * FROM decisions WHERE plan_id = ? ORDER BY decided_at ASC, id ASC;", (plan_id,)):
            decisions.append(
                Decision(
                    id=r["id"],
                    plan_id=r["plan_id"],
                    actor=r["actor"],
                    action=r["action"],
                    reason=r["reason"],
                    selected_route_id=r["selected_route_id"],
                    superseded_route_id=r["superseded_route_id"],
                    decided_at=r["decided_at"],
                    review_evidence=ReviewEvidence.model_validate_json(r["review_evidence_json"]),
                )
            )
        return decisions

    def advance_clock(self, target_clock_iso: str) -> State:
        self.conn.execute(
            "UPDATE app_state SET simulation_clock = ?, clock_revision = clock_revision + 1 WHERE id = 1;",
            (target_clock_iso,),
        )
        return self.get_state()

    def get_map_geometry(self) -> MapGeometry:
        snap = self.get_snapshot()
        cur = self.conn.execute("SELECT integrations_revision FROM app_state WHERE id = 1;")
        int_rev = cur.fetchone()[0]
        lanes = []
        for r in self.conn.execute("SELECT * FROM lane_geometries ORDER BY lane_id, departure_at;"):
            lanes.append(
                LaneGeometry(
                    lane_id=r["lane_id"],
                    departure_at=r["departure_at"],
                    geometry_kind=r["geometry_kind"],
                    geometry=Geometry.model_validate_json(r["coordinates_json"]),
                    source=r["source"],
                    attribution=r["attribution"],
                    fetched_at=r["fetched_at"],
                    stale=bool(r["stale"]),
                )
            )
        return MapGeometry(snapshot=snap, integrations_revision=int_rev, lanes=lanes)

    def upsert_lane_geometry(self, lg: LaneGeometry):
        self.conn.execute(
            """
            INSERT INTO lane_geometries (
                lane_id, departure_at, geometry_kind, coordinates_json,
                source, attribution, fetched_at, stale
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(lane_id, departure_at) DO UPDATE SET
                geometry_kind = excluded.geometry_kind,
                coordinates_json = excluded.coordinates_json,
                source = excluded.source,
                attribution = excluded.attribution,
                fetched_at = excluded.fetched_at,
                stale = excluded.stale;
            """,
            (
                lg.lane_id,
                lg.departure_at,
                lg.geometry_kind,
                json.dumps(lg.geometry.model_dump()),
                lg.source,
                lg.attribution,
                lg.fetched_at,
                1 if lg.stale else 0,
            ),
        )
        self.conn.execute("UPDATE app_state SET integrations_revision = integrations_revision + 1 WHERE id = 1;")

    def get_integrations(self) -> Integrations:
        snap = self.get_snapshot()
        state = self.get_state()
        stored = {}
        for row in self.conn.execute("SELECT * FROM provider_statuses;"):
            stored[row["name"]] = ProviderStatus(
                name=row["name"], status=row["status"],
                last_poll_at=row["last_poll_at"],
                last_successful_poll_at=row["last_successful_poll_at"],
                consecutive_errors=row["consecutive_errors"],
                error_message=row["error_message"], mode=row["mode"],
            )
        providers = []
        for name in ("open_meteo", "tomtom", "operator_bulletins"):
            if name in stored:
                providers.append(stored[name])
                continue
            if state.mode == "demo":
                initial_status = "disabled"
            elif name == "tomtom" and not os.environ.get("TOMTOM_API_KEY"):
                initial_status = "not_configured"
            elif name == "operator_bulletins" and not os.environ.get("OPERATOR_BULLETIN_FEED"):
                initial_status = "disabled"
            else:
                initial_status = "stale"
            providers.append(ProviderStatus(name=name, status=initial_status,
                                            consecutive_errors=0, mode=state.mode))
        return Integrations(snapshot=snap, integrations_revision=state.integrations_revision, providers=providers)

    def store_provider_status(self, status: ProviderStatus):
        self.conn.execute("""
            INSERT INTO provider_statuses (name, status, last_poll_at, last_successful_poll_at,
                consecutive_errors, error_message, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                status = excluded.status, last_poll_at = excluded.last_poll_at,
                last_successful_poll_at = excluded.last_successful_poll_at,
                consecutive_errors = excluded.consecutive_errors,
                error_message = excluded.error_message, mode = excluded.mode;
        """, (status.name, status.status, status.last_poll_at, status.last_successful_poll_at,
              status.consecutive_errors, status.error_message, status.mode))

    def get_observations(self, limit: int = 100) -> list[Observation]:
        obs = []
        for r in self.conn.execute("SELECT * FROM provider_observations ORDER BY observed_at DESC, id ASC LIMIT ?;", (limit,)):
            obs.append(
                Observation(
                    id=r["id"],
                    provider=r["provider"],
                    target_kind=r["target_kind"],
                    target_id=r["target_id"],
                    intended_departure_at=r["intended_departure_at"],
                    observed_at=r["observed_at"],
                    fetched_at=r["fetched_at"],
                    valid_from=r["valid_from"],
                    valid_until=r["valid_until"],
                    metrics=json.loads(r["metrics_json"]),
                    raw_digest=r["raw_digest"],
                    attribution=r["attribution"],
                    stale=bool(r["stale"]),
                )
            )
        return obs

    def store_observation(self, obs: Observation) -> bool:
        cursor = self.conn.execute(
            """
            INSERT INTO provider_observations (
                id, provider, target_kind, target_id, intended_departure_at,
                observed_at, fetched_at, valid_from, valid_until, metrics_json,
                raw_digest, attribution, stale
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING;
            """,
            (
                obs.id,
                obs.provider,
                obs.target_kind,
                obs.target_id,
                obs.intended_departure_at,
                obs.observed_at,
                obs.fetched_at,
                obs.valid_from,
                obs.valid_until,
                json.dumps(obs.metrics),
                obs.raw_digest,
                obs.attribution,
                1 if obs.stale else 0,
            ),
        )
        return cursor.rowcount > 0

    def get_data_summary(self) -> DataSummary:
        sources = []
        for r in self.conn.execute("SELECT * FROM source_summaries ORDER BY filename;"):
            sources.append(
                SourceSummary(
                    filename=r["filename"],
                    rows=r["rows"],
                    date_from=r["date_from"],
                    date_to=r["date_to"],
                    issues=json.loads(r["issues_json"]),
                    sha256=r["sha256"],
                )
            )
        # Capacity example
        cap_ex = None
        cur = self.conn.execute("SELECT * FROM capacity_examples WHERE id = 1;")
        cr = cur.fetchone()
        if cr:
            cap_ex = CapacityExample(
                source_file=cr["source_file"],
                relation=cr["relation"],
                destination=cr["destination"],
                date=cr["date"],
                planned_trailers=cr["planned_trailers"],
                needed_trailers=cr["needed_trailers"],
                special_trips=cr["special_trips"],
                loading_metres=cr["loading_metres"],
                trailer_capacity_metres=cr["trailer_capacity_metres"],
            )
        assumptions = [
            "Source CSV data contains historical operational volume, not carrier timetables or ETA labels.",
            "Nine nodes and ten lanes are synthetic prototype assumptions.",
            "Traffic delay converted to additional minutes with ceil(trafficDelayInSeconds/60).",
            "Weather default policy is advisory_only.",
        ]
        return DataSummary(
            sources=sources,
            assumptions=assumptions,
            import_complete=len(sources) >= 7,
            capacity_example=cap_ex,
        )
