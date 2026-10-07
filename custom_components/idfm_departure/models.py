"""Data models for the IDFM Prochain Départ integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Place:
    """Navitia /places result."""

    id: str
    name: str
    kind: str
    lat: float | None
    lon: float | None


@dataclass(frozen=True, slots=True)
class LineInfo:
    """Navitia line."""

    id: str
    code: str
    name: str
    mode: str
    network: str | None
    color: str | None
    text_color: str | None = None


@dataclass(frozen=True, slots=True)
class StopVisit:
    """One SIRI MonitoredStopVisit."""

    line_ref: str
    line_name: str | None
    destination: str | None
    direction: str | None
    stop_ref: str | None
    departure_at: datetime
    realtime: bool
    aimed_departure_at: datetime | None = None
    platform: str | None = None


@dataclass(frozen=True, slots=True)
class JourneyOption:
    """One Navitia journey, reduced to what we need."""

    walk_s: int
    pt_departure_at: datetime
    stop_point_id: str
    stop_name: str
    line_id: str | None
    line_code: str
    mode: str
    direction: str | None
    arrival_at: datetime | None
    color: str | None = None
    text_color: str | None = None
    base_pt_departure_at: datetime | None = None
    nb_transfers: int = 0


@dataclass(frozen=True, slots=True)
class PlannedDeparture:
    """What entities display."""

    line: str
    mode: str
    direction: str | None
    stop_departure: datetime
    leave_at: datetime
    realtime: bool
    walk_min: int
    source: str
    line_id: str | None = None
    line_color: str | None = None
    line_text_color: str | None = None
    arrival_at: datetime | None = None
    platform: str | None = None

    def as_attr(self) -> dict[str, Any]:
        """Return a JSON-friendly attribute dict."""
        return {
            "line": self.line,
            "mode": self.mode,
            "direction": self.direction,
            "stop_departure": self.stop_departure.isoformat(),
            "leave_at": self.leave_at.isoformat(),
            "realtime": self.realtime,
            "walk_min": self.walk_min,
            "line_id": self.line_id,
            "line_color": self.line_color,
            "line_text_color": self.line_text_color,
            "arrival_at": (
                self.arrival_at.astimezone(UTC).isoformat()
                if self.arrival_at
                else None
            ),
            "platform": self.platform,
        }


@dataclass(slots=True)
class IdfmData:
    """Coordinator data."""

    mode: str
    departures: list[PlannedDeparture]
    walk_s: int | None
    walk_source: str
    stop_name: str | None
    last_api_update: datetime | None
    active: bool
    api_usage: dict[str, int]

    def upcoming(self, now: datetime) -> list[PlannedDeparture]:
        """Departures whose leave_at is not in the past."""
        return [d for d in self.departures if d.leave_at >= now]
