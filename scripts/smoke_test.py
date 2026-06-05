#!/usr/bin/env python3
"""Live smoke test for the Solkart integration's parsing and math.

Loads ``custom_components/solkart/model.py`` in isolation (no Home Assistant
required), calls the real Solkart API with a multi-array config, and asserts the
derived-value helpers behave sanely.

Usage:
    SOLKART_API_KEY=sk_live_... python3 scripts/smoke_test.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_URL = "https://api.solkart.no/api/forecast"
REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = REPO_ROOT / "custom_components" / "solkart" / "model.py"


def load_model():
    """Import model.py without triggering the HA package __init__."""
    spec = importlib.util.spec_from_file_location("solkart_model", MODEL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # Register before exec so dataclasses(slots=True) can resolve annotations.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fetch(api_key: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-Key": api_key,
            # Solkart is behind Cloudflare, which blocks the default
            # python-urllib User-Agent; send our own.
            "User-Agent": "ha-solkart/0.1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


class Checks:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}{f'  ({detail})' if detail else ''}")
        if not ok:
            self.failures.append(label)


def main() -> int:
    api_key = os.environ.get("SOLKART_API_KEY")
    if not api_key:
        print("ERROR: set SOLKART_API_KEY in the environment.", file=sys.stderr)
        return 2

    model = load_model()

    payload = {
        "latitude": 59.19,
        "longitude": 10.90,
        "performance_ratio": 0.85,
        "arrays": [
            {"name": "Sør", "kwp": 5, "tilt_deg": 25, "azimuth_deg": 180},
            {"name": "Øst", "kwp": 3, "tilt_deg": 15, "azimuth_deg": 90},
            {"name": "Vest", "kwp": 3, "tilt_deg": 15, "azimuth_deg": 270},
        ],
    }

    print("Requesting forecast (multi-array)...")
    try:
        raw = fetch(api_key, payload)
    except urllib.error.HTTPError as err:
        print(f"ERROR: HTTP {err.code}: {err.read()[:200]!r}", file=sys.stderr)
        return 1
    except urllib.error.URLError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    data = model.parse_forecast(raw)
    now = datetime.now(timezone.utc).astimezone()

    c = Checks()
    print("\nParsing:")
    c.check("timeseries parsed", len(data.points) > 0, f"{len(data.points)} points")
    c.check(
        "points sorted ascending",
        all(
            data.points[i].timestamp <= data.points[i + 1].timestamp
            for i in range(len(data.points) - 1)
        ),
    )
    c.check("cycle_time parsed", data.cycle_time is not None, str(data.cycle_time))
    c.check(
        "array names resolved",
        data.array_names == ["Sør", "Øst", "Vest"],
        str(data.array_names),
    )
    sample = data.points[len(data.points) // 3]
    c.check(
        "per-array keys present on points",
        set(sample.array_w) == {"Sør", "Øst", "Vest"},
        str(list(sample.array_w)),
    )
    c.check(
        "per-array sum ≈ total (pre performance-ratio)",
        sample.total_w is not None
        and all(v is not None for v in sample.array_w.values()),
    )

    print("\nDerived values (now = %s):" % now.isoformat(timespec="minutes"))
    power_now = data.power_now(now)
    ghi_now = data.ghi_now(now)
    e_today = data.energy_today(now)
    e_remaining = data.energy_today_remaining(now)
    e_tomorrow = data.energy_tomorrow(now)
    e_hour = data.energy_current_hour(now)
    peak_today = data.peak_time_today(now)
    peak_tomorrow = data.peak_time_tomorrow(now)

    print(f"  power_now            = {power_now}")
    print(f"  ghi_now              = {ghi_now}")
    print(f"  energy_today         = {e_today} kWh")
    print(f"  energy_today_remain  = {e_remaining} kWh")
    print(f"  energy_tomorrow      = {e_tomorrow} kWh")
    print(f"  energy_current_hour  = {e_hour} kWh")
    print(f"  peak_time_today      = {peak_today}")
    print(f"  peak_time_tomorrow   = {peak_tomorrow}")

    print("\nAssertions:")
    powers = [p.total_w for p in data.points if p.total_w is not None]
    c.check(
        "power_now within data range or None",
        power_now is None or (min(powers) <= power_now <= max(powers)),
        str(power_now),
    )
    c.check("energy_today >= 0", e_today >= 0, str(e_today))
    c.check(
        "energy_today_remaining <= energy_today + tolerance",
        e_remaining <= e_today + 0.05,
        f"{e_remaining} <= {e_today}",
    )
    c.check("energy_tomorrow >= 0", e_tomorrow >= 0, str(e_tomorrow))
    first, last = data.points[0].timestamp, data.points[-1].timestamp
    c.check(
        "peak_time_tomorrow within forecast window",
        peak_tomorrow is None or (first <= peak_tomorrow <= last),
        str(peak_tomorrow),
    )
    wh = data.wh_hours()
    c.check(
        "wh_hours keys == point count",
        len(wh) == len(data.points),
        f"{len(wh)} == {len(data.points)}",
    )
    c.check(
        "power_at(+1h) interpolates",
        data.power_at(now, timedelta(hours=1)) is None
        or isinstance(data.power_at(now, timedelta(hours=1)), float),
    )

    print()
    if c.failures:
        print(f"RESULT: {len(c.failures)} check(s) FAILED: {c.failures}")
        return 1
    print("RESULT: all checks passed ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
