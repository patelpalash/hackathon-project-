"""Operator bulletin feed adapter adhering to docs/MAP_AND_LIVE_DATA.md."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import httpx

from ..contracts.provider_protocol import PollRequest, ProviderBatch, ProviderAdapter
from ..engine.time_utils import to_iso_utc

class OperatorBulletinAdapter:
    def __init__(
        self,
        feed_url_or_path: Optional[str] = None,
        is_trusted: bool = False,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._feed_target = feed_url_or_path or os.environ.get("OPERATOR_BULLETIN_FEED")
        self._is_trusted = is_trusted or (os.environ.get("OPERATOR_FEED_TRUSTED", "").lower() in ("1", "true"))
        self._client = client

    async def poll(self, request: PollRequest) -> ProviderBatch:
        now_iso = to_iso_utc(datetime.now(timezone.utc))
        mode = "demo" if request.dataset_id.startswith("seed") or "demo" in request.dataset_id else "live"

        if not self._feed_target:
            status = {
                "name": "operator_bulletins",
                "status": "disabled",
                "last_poll_at": now_iso,
                "last_successful_poll_at": None,
                "consecutive_errors": 0,
                "error_message": None,
                "mode": mode,
            }
            return ProviderBatch(
                provider="operator_bulletins",
                dataset_id=request.dataset_id,
                schedule_revision=request.schedule_revision,
                observations=(),
                proposed_events=(),
                geometries=(),
                status=status,
                warnings=("Operator bulletin feed not configured; adapter disabled",),
            )

        observations: list[dict[str, Any]] = []
        proposed_events: list[dict[str, Any]] = []
        warnings: list[str] = []

        try:
            raw_text = ""
            if self._feed_target.startswith("http://") or self._feed_target.startswith("https://"):
                client = self._client or httpx.AsyncClient(timeout=8.0)
                try:
                    resp = await client.get(self._feed_target)
                    resp.raise_for_status()
                    raw_text = resp.text
                finally:
                    if self._client is None:
                        await client.aclose()
            else:
                p = Path(self._feed_target)
                if p.exists():
                    raw_text = p.read_text(encoding="utf-8")
                else:
                    raise FileNotFoundError(f"Feed file not found: {p}")

            raw_digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            feed_data = json.loads(raw_text)

            events_list = feed_data.get("events", [])
            for item in events_list:
                # Disregard self-declared trust in remote payload; server config determines trust
                ver_status = "accepted" if self._is_trusted else "pending"

                obs_id = hashlib.sha256(f"bulletin:{item.get('external_id')}:{raw_digest[:8]}".encode()).hexdigest()[:24]
                obs = {
                    "id": obs_id,
                    "provider": "operator_bulletins",
                    "target_kind": item.get("target_kind", "lane"),
                    "target_id": item.get("target_id"),
                    "intended_departure_at": item.get("applies_to_departure_at"),
                    "observed_at": item.get("observed_at", now_iso),
                    "fetched_at": now_iso,
                    "valid_from": item.get("valid_from", now_iso),
                    "valid_until": item.get("valid_until"),
                    "metrics": {"raw_summary": item.get("reason", "")},
                    "raw_digest": raw_digest,
                    "attribution": "Operator Administrative Bulletin",
                    "stale": False,
                }
                observations.append(obs)

                ev = {
                    "type": item.get("type", "political"),
                    "source_kind": "provider",
                    "external_id": item.get("external_id"),
                    "source_reference": item.get("source_reference", "Operator Bulletin"),
                    "observed_at": item.get("observed_at", now_iso),
                    "valid_from": item.get("valid_from", now_iso),
                    "valid_until": item.get("valid_until"),
                    "review_due_at": item.get("review_due_at"),
                    "target_kind": item.get("target_kind", "lane"),
                    "target_id": item.get("target_id"),
                    "mode": item.get("mode", "road"),
                    "effect_type": item.get("effect_type", "closure"),
                    "effect_minutes": item.get("effect_minutes"),
                    "verification_status": ver_status,
                    "lifecycle_status": item.get("lifecycle_status", "active"),
                    "correlation_key": item.get("correlation_key", f"BULLETIN-{item.get('external_id')}"),
                    "reason": item.get("reason", "Administrative disruption"),
                    "applies_to_departure_at": item.get("applies_to_departure_at"),
                    "observation_id": obs_id,
                }
                proposed_events.append(ev)

            status = {
                "name": "operator_bulletins",
                "status": "ok",
                "last_poll_at": now_iso,
                "last_successful_poll_at": now_iso,
                "consecutive_errors": 0,
                "error_message": None,
                "mode": mode,
            }

        except Exception as e:
            status = {
                "name": "operator_bulletins",
                "status": "error",
                "last_poll_at": now_iso,
                "last_successful_poll_at": None,
                "consecutive_errors": 1,
                "error_message": str(e),
                "mode": mode,
            }
            warnings.append(f"Failed to poll operator bulletins: {e}")

        return ProviderBatch(
            provider="operator_bulletins",
            dataset_id=request.dataset_id,
            schedule_revision=request.schedule_revision,
            observations=tuple(observations),
            proposed_events=tuple(proposed_events),
            geometries=(),
            status=status,
            warnings=tuple(warnings),
        )
