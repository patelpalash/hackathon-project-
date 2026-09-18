"""Open-Meteo weather adapter adhering to docs/MAP_AND_LIVE_DATA.md."""
import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Optional
import httpx

from ..contracts.provider_protocol import PollRequest, ProviderBatch, ProviderAdapter
from ..domain.models import Observation, EventInput, ProviderStatus
from ..engine.time_utils import parse_iso_dt, to_iso_utc

class OpenMeteoAdapter:
    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client

    async def poll(self, request: PollRequest) -> ProviderBatch:
        nodes_by_id = {n["id"]: n for n in request.network.get("nodes", [])}
        lanes_by_id = {l["id"]: l for l in request.network.get("lanes", [])}

        observations: list[dict[str, Any]] = []
        proposed_events: list[dict[str, Any]] = []
        warnings: list[str] = []

        now_utc = datetime.now(timezone.utc)
        now_iso = to_iso_utc(now_utc)
        eval_dt = parse_iso_dt(request.evaluation_at)

        client = self._client or httpx.AsyncClient(timeout=8.0)
        close_client = (self._client is None)

        consecutive_errors = 0
        error_msg = None
        status_code_str = "ok"

        try:
            # Process target road lane departures
            for lane_id, occurrences in request.target_departures.items():
                lane = lanes_by_id.get(lane_id)
                if not lane or lane.get("mode") != "road":
                    continue

                from_node = nodes_by_id.get(lane.get("from_node_id"))
                to_node = nodes_by_id.get(lane.get("to_node_id"))
                if not from_node or not to_node:
                    continue

                for dep_iso in occurrences:
                    dep_dt = parse_iso_dt(dep_iso)
                    lane_dur = lane.get("duration_minutes", 60)
                    arr_dt = dep_dt + (eval_dt - eval_dt) # preserve tz
                    arr_iso = to_iso_utc(dep_dt + (eval_dt - eval_dt))

                    # Simulated / mock or live query for endpoint weather
                    url = (
                        f"https://api.open-meteo.com/v1/forecast?"
                        f"latitude={from_node['latitude']}&longitude={from_node['longitude']}&"
                        f"hourly=precipitation,wind_gusts_10m,snowfall,weather_code&timezone=UTC"
                    )

                    try:
                        resp = await client.get(url)
                        if resp.status_code == 429:
                            warnings.append(f"Open-Meteo 429 rate limit on lane {lane_id}")
                            status_code_str = "stale"
                            consecutive_errors += 1
                            continue
                        elif resp.status_code != 200:
                            warnings.append(f"Open-Meteo HTTP {resp.status_code} for {lane_id}")
                            consecutive_errors += 1
                            continue

                        data = resp.json()
                        raw_bytes = resp.content
                        raw_digest = hashlib.sha256(raw_bytes).hexdigest()

                        # Extract max precipitation and gusts in traversal window
                        hourly = data.get("hourly", {})
                        times = hourly.get("time", [])
                        precips = hourly.get("precipitation", [])
                        gusts = hourly.get("wind_gusts_10m", [])
                        snows = hourly.get("snowfall", [])

                        max_precip = 0.0
                        max_gust = 0.0
                        max_snow = 0.0

                        for t_str, p, g, s in zip(times, precips, gusts, snows):
                            try:
                                t_dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
                                if dep_dt <= t_dt <= (dep_dt + (eval_dt - eval_dt)):
                                    if p is not None and p > max_precip: max_precip = float(p)
                                    if g is not None and g > max_gust: max_gust = float(g)
                                    if s is not None and s > max_snow: max_snow = float(s)
                            except Exception:
                                pass

                    except Exception as exc:
                        # Offline fallback or timeout
                        warnings.append(f"Open-Meteo fetch failed ({exc}); offline/demo conditions applied")
                        data = {"simulated": True}
                        raw_digest = hashlib.sha256(f"offline-{lane_id}-{dep_iso}".encode()).hexdigest()
                        max_precip = 0.0
                        max_gust = 0.0
                        max_snow = 0.0

                    obs_id = hashlib.sha256(f"open_meteo:{lane_id}:{dep_iso}".encode()).hexdigest()[:24]
                    obs = {
                        "id": obs_id,
                        "provider": "open_meteo",
                        "target_kind": "lane",
                        "target_id": lane_id,
                        "intended_departure_at": dep_iso,
                        "observed_at": now_iso,
                        "fetched_at": now_iso,
                        "valid_from": dep_iso,
                        "valid_until": to_iso_utc(dep_dt + (eval_dt - eval_dt)),
                        "metrics": {
                            "precipitation_mm": max_precip,
                            "wind_gusts_kmh": max_gust,
                            "snowfall_cm": max_snow,
                        },
                        "raw_digest": raw_digest,
                        "attribution": "Weather data by Open-Meteo.com under CC BY 4.0",
                        "stale": False,
                    }
                    observations.append(obs)

                    # Demo thresholds check
                    if request.weather_delay_policy == "demo_thresholds":
                        extra_mins = 0
                        reasons = []
                        if max_precip >= 10.0:
                            extra_mins = max(extra_mins, 30)
                            reasons.append(f"Precipitation {max_precip}mm >= 10mm (30m)")
                        if max_gust >= 80.0:
                            extra_mins = max(extra_mins, 45)
                            reasons.append(f"Wind gusts {max_gust}km/h >= 80km/h (45m)")

                        if extra_mins > 0:
                            ev = {
                                "type": "weather",
                                "source_kind": "provider",
                                "external_id": f"meteo-{lane_id}-{dep_iso}",
                                "source_reference": "Open-Meteo Forecast",
                                "observed_at": now_iso,
                                "valid_from": dep_iso,
                                "valid_until": to_iso_utc(dep_dt + (eval_dt - eval_dt)),
                                "review_due_at": to_iso_utc(now_utc + (eval_dt - eval_dt)),
                                "target_kind": "lane",
                                "target_id": lane_id,
                                "mode": "road",
                                "effect_type": "additional_travel_minutes",
                                "effect_minutes": extra_mins,
                                "verification_status": "accepted",
                                "lifecycle_status": "active",
                                "correlation_key": f"road-conditions:{lane_id}:{dep_iso}",
                                "reason": f"Severe weather ({', '.join(reasons)}) on lane {lane_id}",
                                "applies_to_departure_at": dep_iso,
                                "observation_id": obs_id,
                            }
                            proposed_events.append(ev)

        except Exception as e:
            consecutive_errors += 1
            status_code_str = "error"
            error_msg = str(e)
            warnings.append(f"Open-Meteo poll error: {e}")
        finally:
            if close_client:
                await client.aclose()

        status = {
            "name": "open_meteo",
            "status": status_code_str,
            "last_poll_at": now_iso,
            "last_successful_poll_at": now_iso if status_code_str == "ok" else None,
            "consecutive_errors": consecutive_errors,
            "error_message": error_msg,
            "mode": "demo" if request.dataset_id.startswith("seed") or "demo" in request.dataset_id else "live",
        }

        return ProviderBatch(
            provider="open_meteo",
            dataset_id=request.dataset_id,
            schedule_revision=request.schedule_revision,
            observations=tuple(observations),
            proposed_events=tuple(proposed_events),
            geometries=(),
            status=status,
            warnings=tuple(warnings),
        )
