"""Pure data model and derived-value math for Solkart forecasts.

This module intentionally has **no Home Assistant imports** so the parsing and
the derived-value helpers can be exercised standalone (see ``scripts`` /
smoke test in the repository). The Home Assistant coordinator feeds it the raw
API JSON and a timezone-aware ``now``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

ONE_HOUR = timedelta(hours=1)


def _parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (``...Z`` or offset) to aware UTC."""
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class ForecastPoint:
    """A single hourly forecast sample (the hour starting at ``timestamp``)."""

    timestamp: datetime  # aware, UTC; start of the hour
    ghi_wm2: float | None
    total_w: float | None
    total_kwh: float | None  # energy produced during this hour
    array_w: dict[str, float | None] = field(default_factory=dict)


@dataclass(slots=True)
class SolkartData:
    """Parsed forecast plus system summary, with derived-value helpers."""

    cycle_time: datetime | None
    data_mode: str | None
    model: str | None
    engine: str | None
    peak_power_w: float | None
    total_production_kwh: float | None
    peak_ghi_wm2: float | None
    daily_ghi_kwh_m2: float | None
    array_names: list[str]
    points: list[ForecastPoint]

    # -- interpolation -----------------------------------------------------

    def _interpolate(
        self, now: datetime, getter: Callable[[ForecastPoint], float | None]
    ) -> float | None:
        """Linearly interpolate a per-point value at ``now`` (aware datetime)."""
        pts = self.points
        if not pts:
            return None
        now = now.astimezone(timezone.utc)
        if now <= pts[0].timestamp:
            return getter(pts[0])
        if now >= pts[-1].timestamp:
            return None
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            if a.timestamp <= now <= b.timestamp:
                va, vb = getter(a), getter(b)
                if va is None and vb is None:
                    return None
                if va is None:
                    return vb
                if vb is None:
                    return va
                span = (b.timestamp - a.timestamp).total_seconds()
                if span <= 0:
                    return va
                frac = (now - a.timestamp).total_seconds() / span
                return va + (vb - va) * frac
        return None

    def power_now(self, now: datetime) -> float | None:
        """Total PV power (W) interpolated at ``now``."""
        return self._interpolate(now, lambda p: p.total_w)

    def ghi_now(self, now: datetime) -> float | None:
        """Global horizontal irradiance (W/m²) interpolated at ``now``."""
        return self._interpolate(now, lambda p: p.ghi_wm2)

    def power_array_now(self, now: datetime, name: str) -> float | None:
        """Power (W) for a single named array interpolated at ``now``."""
        return self._interpolate(now, lambda p: p.array_w.get(name))

    def power_at(self, now: datetime, offset: timedelta) -> float | None:
        """Total PV power (W) interpolated at ``now + offset``."""
        return self._interpolate(now + offset, lambda p: p.total_w)

    # -- hourly energy lookups --------------------------------------------

    def _point_for_hour(self, target: datetime) -> ForecastPoint | None:
        """Return the point whose hour bucket contains ``target``."""
        target = target.astimezone(timezone.utc)
        for p in self.points:
            if p.timestamp <= target < p.timestamp + ONE_HOUR:
                return p
        return None

    def energy_current_hour(self, now: datetime) -> float | None:
        """Energy (kWh) for the hour bucket containing ``now``."""
        point = self._point_for_hour(now)
        return None if point is None else point.total_kwh

    def energy_next_hour(self, now: datetime) -> float | None:
        """Energy (kWh) for the hour bucket starting one hour from ``now``."""
        point = self._point_for_hour(now + ONE_HOUR)
        return None if point is None else point.total_kwh

    # -- per-local-day aggregates -----------------------------------------

    def _local_date(self, ts: datetime, reference: datetime):
        """Return the calendar date of ``ts`` in ``reference``'s timezone."""
        return ts.astimezone(reference.tzinfo).date()

    def energy_for_date(self, now: datetime, day) -> float:
        """Sum of hourly energy (kWh) for points falling on local date ``day``."""
        total = 0.0
        for p in self.points:
            if p.total_kwh is None:
                continue
            if self._local_date(p.timestamp, now) == day:
                total += p.total_kwh
        return round(total, 3)

    def energy_today(self, now: datetime) -> float:
        """Today's total energy (kWh). Best-effort on the free tier (the series
        starts at the latest model cycle, so early-morning hours may be absent).
        """
        return self.energy_for_date(now, now.date())

    def energy_tomorrow(self, now: datetime) -> float:
        """Tomorrow's total energy (kWh)."""
        return self.energy_for_date(now, (now + timedelta(days=1)).date())

    def energy_today_remaining(self, now: datetime) -> float:
        """Energy (kWh) still expected for the remainder of today.

        The hour bucket containing ``now`` is prorated by the fraction of the
        hour that is still in the future.
        """
        now = now.astimezone(timezone.utc) if now.tzinfo else now
        reference = now
        today = reference.astimezone(reference.tzinfo).date()
        total = 0.0
        now_utc = reference.astimezone(timezone.utc)
        for p in self.points:
            if p.total_kwh is None:
                continue
            if self._local_date(p.timestamp, reference) != today:
                continue
            hour_end = p.timestamp + ONE_HOUR
            if hour_end <= now_utc:
                continue  # fully in the past
            if p.timestamp >= now_utc:
                total += p.total_kwh  # fully in the future
            else:
                frac = (hour_end - now_utc).total_seconds() / 3600.0
                total += p.total_kwh * frac
        return round(total, 3)

    def peak_time_for_date(self, now: datetime, day) -> datetime | None:
        """Timestamp (aware UTC) of the highest-power hour on local date ``day``."""
        best: ForecastPoint | None = None
        for p in self.points:
            if p.total_w is None:
                continue
            if self._local_date(p.timestamp, now) != day:
                continue
            if best is None or (p.total_w > (best.total_w or 0)):
                best = p
        return None if best is None else best.timestamp

    def peak_time_today(self, now: datetime) -> datetime | None:
        return self.peak_time_for_date(now, now.date())

    def peak_time_tomorrow(self, now: datetime) -> datetime | None:
        return self.peak_time_for_date(now, (now + timedelta(days=1)).date())

    # -- export helpers ----------------------------------------------------

    def wh_hours(self) -> dict[str, float]:
        """Energy per hour in Wh keyed by ISO timestamp (Energy Dashboard)."""
        return {
            p.timestamp.isoformat(): round((p.total_kwh or 0.0) * 1000.0, 2)
            for p in self.points
        }

    def forecast_attribute(self) -> list[dict[str, Any]]:
        """Compact per-hour series suitable for a sensor attribute / charts."""
        return [
            {
                "datetime": p.timestamp.isoformat(),
                "power_w": p.total_w,
                "energy_kwh": p.total_kwh,
                "ghi_wm2": p.ghi_wm2,
            }
            for p in self.points
        ]


def parse_forecast(raw: dict[str, Any]) -> SolkartData:
    """Parse a raw ``/api/forecast`` JSON body into :class:`SolkartData`."""
    pv_system = raw.get("pv_system") or {}
    array_names = [
        a.get("name")
        for a in (pv_system.get("arrays") or [])
        if a.get("name")
    ]

    points: list[ForecastPoint] = []
    for item in raw.get("pv_timeseries") or []:
        ts_raw = item.get("timestamp")
        if not ts_raw:
            continue
        array_w = {name: _as_float(item.get(f"{name}_W")) for name in array_names}
        points.append(
            ForecastPoint(
                timestamp=_parse_ts(ts_raw),
                ghi_wm2=_as_float(item.get("ghi_wm2")),
                total_w=_as_float(item.get("total_W")),
                total_kwh=_as_float(item.get("total_kWh")),
                array_w=array_w,
            )
        )
    points.sort(key=lambda p: p.timestamp)

    cycle_raw = raw.get("cycle_time")
    return SolkartData(
        cycle_time=_parse_ts(cycle_raw) if cycle_raw else None,
        data_mode=raw.get("data_mode"),
        model=raw.get("model"),
        engine=pv_system.get("engine"),
        peak_power_w=_as_float(pv_system.get("peak_power_w")),
        total_production_kwh=_as_float(pv_system.get("total_production_kwh")),
        peak_ghi_wm2=_as_float(raw.get("peak_ghi_wm2")),
        daily_ghi_kwh_m2=_as_float(raw.get("daily_ghi_kwh_m2")),
        array_names=array_names,
        points=points,
    )
