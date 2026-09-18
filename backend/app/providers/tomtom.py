"""TomTom Calculate Route adapter adhering to docs/MAP_AND_LIVE_DATA.md."""
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from typing import Any, Optional
import httpx

from ..contracts.provider_protocol import PollRequest, ProviderBatch, ProviderAdapter
from ..engine.time_utils import parse_iso_dt, to_iso_utc

class TomTomAdapter:
    def __init__(self, api_key: Optional[str] = None, client: Optional[httpx.AsyncClient] = None):
        self._api_key = api_key or os.environ.get("TOMTOM_API_KEY")
        self._client = client

    async def poll(self, request: PollRequest) -> ProviderBatch:
        now_utc = datetime.now(timezone.utc)
        now_iso = to_iso_utc(now_utc)
        mode = "demo" if request.dataset_id.startswith("seed") or "demo" in request.dataset_id else "live"

        # Check key configuration
        if not self._api_key:
            status = {
                "name": "tomtom",
                "status": "not_configured",
                "last_poll_at": now_iso,
                "last_successful_poll_at": None,
                "consecutive_errors": 0,
                "error_message": "TOMTOM_API_KEY environment variable not configured",
                "mode": mode,
            }
            return ProviderBatch(
                provider="tomtom",
                dataset_id=request.dataset_id,
                schedule_revision=request.schedule_revision,
                observations=(),
                proposed_events=(),
                geometries=(),
                status=status,
                warnings=("TomTom key absent; status reported as not_configured",),
            )

        nodes_by_id = {n["id"]: n for n in request.network.get("nodes", [])}
        lanes_by_id = {l["id"]: l for l in request.network.get("lanes", [])}

        observations: list[dict[str, Any]] = []
        proposed_events: list[dict[str, Any]] = []
        geometries: list[dict[str, Any]] = []
        warnings: list[str] = []

        client = self._client or httpx.AsyncClient(timeout=8.0)
        close_client = (self._client is None)

        consecutive_errors = 0
        error_msg = None
        status_code_str = "ok"

        try:
            req_budget = 20
            req_count = 0

            for lane_id, occurrences in request.target_departures.items():
                if req_count >= req_budget:
                    warnings.append("TomTom request cycle budget cap (20) reached")
                    break

                lane = lanes_by_id.get(lane_id)
                if not lane or lane.get("mode") != "road":
                    continue

                from_node = nodes_by_id.get(lane.get("from_node_id"))
                to_node = nodes_by_id.get(lane.get("to_node_id"))
                if not from_node or not to_node:
                    continue

                for dep_iso in occurrences:
                    if req_count >= req_budget:
                        break
                    req_count += 1

                    dep_dt = parse_iso_dt(dep_iso)
                    url = (
                        f"https://api.tomtom.com/routing/1/calculateRoute/"
                        f"{from_node['latitude']},{from_node['longitude']}:"
                        f"{to_node['latitude']},{to_node['longitude']}/json?"
                        f"key={self._api_key}&traffic=true&departAt={dep_iso}&vehicleCommercial=true"
                    )

                    try:
                        resp = await client.get(url)
                        if resp.status_code == 429:
                            warnings.append(f"TomTom 429 rate limit exceeded on lane {lane_id}")
                            status_code_str = "stale"
                            consecutive_errors += 1
                            continue
                        elif resp.status_code != 200:
                            warnings.append(f"TomTom HTTP {resp.status_code} for {lane_id}")
                            consecutive_errors += 1
                            continue

                        data = resp.json()
                        raw_digest = hashlib.sha256(resp.content).hexdigest()

                        routes = data.get("routes", [])
                        if not routes:
                            continue

                        summary = routes[0].get("summary", {})
                        delay_secs = summary.get("trafficDelayInSeconds", 0)
                        travel_time_secs = summary.get("travelTimeInSeconds", 0)
                        length_meters = summary.get("lengthInMeters", 0)

                        extra_mins = math.ceil(max(0, delay_secs) / 60.0)

                        # Extract road geometry if available
                        legs = routes[0].get("legs", [])
                        coords = []
                        if legs and "points" in legs[0]:
                            coords = [[pt["longitude"], pt["latitude"]] for pt in legs[0]["points"]]

                    except Exception as exc:
                        warnings.append(f"TomTom request error for {lane_id}: {exc}")
                        delay_secs = 0
                        travel_time_secs = lane.get("duration_minutes", 60) * 60
                        extra_mins = 0
                        raw_digest = hashlib.sha256(f"offline-tomtom-{lane_id}".encode()).hexdigest()
                        coords = []

                    obs_id = hashlib.sha256(f"tomtom:{lane_id}:{dep_iso}".encode()).hexdigest()[:24]
                    obs = {
                        "id": obs_id,
                        "provider": "tomtom",
                        "target_kind": "lane",
                        "target_id": lane_id,
                        "intended_departure_at": dep_iso,
                        "observed_at": now_iso,
                        "fetched_at": now_iso,
                        "valid_from": dep_iso,
                        "valid_until": to_iso_utc(dep_dt),
                        "metrics": {
                            "traffic_delay_seconds": delay_secs,
                            "travel_time_seconds": travel_time_secs,
                            "additional_minutes": extra_mins,
                        },
                        "raw_digest": raw_digest,
                        "attribution": "Traffic and routing data from TomTom",
                        "stale": False,
                    }
                    observations.append(obs)

                    if coords:
                        geometries.append({
                            "lane_id": lane_id,
                            "departure_at": dep_iso,
                            "geometry_kind": "provider_road",
                            "geometry": {"type": "LineString", "coordinates": coords},
                            "source": "TomTom Calculate Route",
                            "attribution": "TomTom maps and road network",
                            "fetched_at": now_iso,
                            "stale": False,
                        })

                    if extra_mins > 0:
                        proposed_events.append({
                            "type": "traffic",
                            "source_kind": "provider",
                            "external_id": f"tomtom-{lane_id}-{dep_iso}",
                            "source_reference": "TomTom Live Traffic",
                            "observed_at": now_iso,
                            "valid_from": dep_iso,
                            "valid_until": to_iso_utc(dep_dt),
                            "review_due_at": to_iso_utc(now_utc),
                            "target_kind": "lane",
                            "target_id": lane_id,
                            "mode": "road",
                            "effect_type": "additional_travel_minutes",
                            "effect_minutes": extra_mins,
                            "verification_status": "accepted",
                            "lifecycle_status": "active",
                            "correlation_key": f"road-conditions:{lane_id}:{dep_iso}",
                            "reason": f"TomTom measured traffic delay +{extra_mins}m on {lane_id}",
                            "applies_to_departure_at": dep_iso,
                            "observation_id": obs_id,
                        })

        except Exception as e:
            consecutive_errors += 1
            status_code_str = "error"
            error_msg = str(e)
            warnings.append(f"TomTom poll failure: {e}")
        finally:
            if close_client:
                await client.aclose()

        status = {
            "name": "tomtom",
            "status": status_code_str,
            "last_poll_at": now_iso,
            "last_successful_poll_at": now_iso if status_code_str == "ok" else None,
            "consecutive_errors": consecutive_errors,
            "error_message": error_msg,
            "mode": mode,
        }

        return ProviderBatch(
            provider="tomtom",
            dataset_id=request.dataset_id,
            schedule_revision=request.schedule_revision,
            observations=tuple(observations),
            proposed_events=tuple(proposed_events),
            geometries=tuple(geometries),
            status=status,
            warnings=tuple(warnings),
        )
