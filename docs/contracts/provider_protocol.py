"""Frozen internal integration protocol; specification only, no provider implementation.

Codex supplies scheduling/DB ingestion. Antigravity implements pure fetch adapters.
Returned dictionaries MUST validate against named schemas in openapi.json.
"""
from dataclasses import dataclass
from typing import Any, Literal, Protocol

ProviderName = Literal['open_meteo', 'tomtom', 'operator_bulletins']

@dataclass(frozen=True)
class PollRequest:
    provider: ProviderName
    dataset_id: str
    schedule_revision: int
    evaluation_at: str  # UTC RFC3339
    network: dict[str, Any]  # Network schema, immutable copy
    target_departures: dict[str, tuple[str, ...]]  # lane ID -> UTC occurrences
    weather_delay_policy: Literal['advisory_only', 'demo_thresholds']

@dataclass(frozen=True)
class ProviderBatch:
    provider: ProviderName
    dataset_id: str
    schedule_revision: int
    observations: tuple[dict[str, Any], ...]  # Observation schema
    proposed_events: tuple[dict[str, Any], ...]  # EventInput schema
    geometries: tuple[dict[str, Any], ...]  # LaneGeometry schema
    status: dict[str, Any]  # ProviderStatus schema
    warnings: tuple[str, ...]

class ProviderAdapter(Protocol):
    async def poll(self, request: PollRequest) -> ProviderBatch:
        """No DB writes; network secrets injected server-side and never returned."""
        ...
