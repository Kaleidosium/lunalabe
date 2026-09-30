"""Reference-checked lunar accuracy harness (spec section G).

Offline-capable: loads the repo's DE440s ephemeris directly. Eclipse dates are
checked against the NASA/GSFC catalog (Total: 2025-03-14, 2025-09-07);
phase/position goldens are closed-loop or probe-verified vectors.
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from skyfield.api import Topos, load
from timezonefinder import TimezoneFinder

from api.exceptions import CalculationError, ValidationError
from api.routes import lunalabe_fastapi
from app import app as fastapi_app
from core.assembly import assemble_lunar_payload
from core.cache import SimpleCache
from core.config import ELEVATION_MAX_M, ELEVATION_MIN_M
from core.lunar_calculations import (
    calculate_lunar_eclipses,
    calculate_phase_info,
    calculate_position_info,
    calculate_rise_set_info,
    calculate_upcoming_phases,
)
from core.utils import get_zodiac_sign, validate_datetime_range
from models.models import LunarDataResponse, MoonPhaseInfo, RiseSetInfo

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def eph():
    path = REPO_ROOT / "de440s.bsp"
    if not path.exists():
        pytest.skip("de440s.bsp not present")
    return load(str(path))


@pytest.fixture(scope="module")
def ts():
    try:
        return load.timescale()
    except Exception:  # noqa: BLE001 - any download/cache failure falls back
        return load.timescale(builtin=True)


def _observer(eph, lat, lon):
    return eph["earth"] + Topos(
        latitude_degrees=lat, longitude_degrees=lon, elevation_m=0
    )


def _day_window(ts, tzname, day):
    local_tz = ZoneInfo(tzname)
    day_start = datetime.fromisoformat(day).replace(tzinfo=local_tz)
    return (
        local_tz,
        day_start,
        ts.from_datetime(day_start),
        ts.from_datetime(day_start + timedelta(days=1)),
    )


def test_greenwich_rise_set_golden(eph, ts):
    """Probe-verified vector: 2025-06-15 rise 00:11, set 08:26, one each."""
    loc = Topos(latitude_degrees=51.48, longitude_degrees=0.0, elevation_m=0)
    tz, _, start, end = _day_window(ts, "Europe/London", "2025-06-15")
    info = calculate_rise_set_info(ts, eph, loc, start, end, tz)
    assert not isinstance(info, CalculationError)
    assert info.moonrise is not None and info.moonset is not None
    assert info.moonrise.startswith("2025-06-15T00:11")
    assert info.moonset.startswith("2025-06-15T08:26")
    assert info.rise_count == 1
    assert info.set_count == 1


def test_polar_no_rise_has_zero_counts(eph, ts):
    loc = Topos(latitude_degrees=78.22, longitude_degrees=15.63, elevation_m=0)
    tz, _, start, end = _day_window(ts, "Arctic/Longyearbyen", "2025-06-15")
    info = calculate_rise_set_info(ts, eph, loc, start, end, tz)
    assert not isinstance(info, CalculationError)
    assert info.moonrise is None and info.moonset is None
    assert info.rise_count == 0 and info.set_count == 0


def test_rise_set_failure_is_error_not_nulls(ts, eph):
    """A computation failure must be an error value, never silent nulls."""
    tz = ZoneInfo("UTC")
    t0 = ts.from_datetime(datetime(2025, 6, 15, tzinfo=UTC))
    t1 = ts.from_datetime(datetime(2025, 6, 16, tzinfo=UTC))
    result = calculate_rise_set_info(ts, eph, None, t0, t1, tz)
    assert isinstance(result, CalculationError)


@pytest.mark.parametrize("catalog_date", ["2025-03-14", "2025-09-07"])
def test_total_eclipses_match_catalog(eph, ts, catalog_date):
    """Total lunar eclipses must land within a day of the NASA/GSFC catalog."""
    t = ts.from_datetime(datetime(2025, 1, 1, tzinfo=UTC))
    eclipses = calculate_lunar_eclipses(ts, eph, t)
    assert not isinstance(eclipses, CalculationError)
    target = datetime.fromisoformat(catalog_date).date()
    totals = [
        datetime.fromisoformat(e.event_time_utc).date()
        for e in eclipses
        if "Total" in e.event_type
    ]
    assert any(abs((d - target).days) <= 1 for d in totals)


def test_upcoming_quarters_self_consistent(eph, ts):
    """At each upcoming quarter instant the phase angle must agree."""
    t = ts.from_datetime(datetime(2025, 6, 15, 12, tzinfo=UTC))
    tz = ZoneInfo("UTC")
    upcoming = calculate_upcoming_phases(ts, eph, t, tz)
    assert not isinstance(upcoming, CalculationError)
    from skyfield import almanac

    checks = {
        "next_new_moon": 0.0,
        "next_full_moon": 180.0,
    }
    for key, expected in checks.items():
        assert getattr(upcoming, key) is not None
        ti = ts.from_datetime(datetime.fromisoformat(getattr(upcoming, key)))
        angle = cast(float, almanac.moon_phase(eph, ti).degrees)
        delta = abs(angle - expected)
        assert min(delta, 360 - delta) < 3.0


def test_phase_and_age_sane(eph, ts):
    t = ts.from_datetime(datetime(2025, 6, 15, 12, tzinfo=UTC))
    info = calculate_phase_info(eph, ts, t)
    assert not isinstance(info, CalculationError)
    assert 0.0 <= info.phase_angle_degrees <= 360.0
    assert 0.0 <= info.percent_illuminated <= 100.0
    assert 0.0 <= info.age_days <= 30.0
    assert info.age_is_estimate is False


def test_position_sane(eph, ts):
    t = ts.from_datetime(datetime(2025, 6, 15, 12, tzinfo=UTC))
    info = calculate_position_info(eph, ts, t, _observer(eph, 51.48, 0.0))
    assert not isinstance(info, CalculationError)
    assert -90.0 <= info.altitude_degrees <= 90.0
    assert 0.0 <= info.azimuth_degrees <= 360.0
    assert 350000 < info.distance_km < 410000


@pytest.mark.parametrize(
    "lon,expected",
    [
        (0.0, "Aries"),
        (29.9, "Aries"),
        (30.0, "Taurus"),
        (359.9, "Pisces"),
        (360.0, "Aries"),
        (720.0, "Aries"),
    ],
)
def test_zodiac_boundaries(lon, expected):
    assert get_zodiac_sign(lon) == expected


@pytest.mark.parametrize(
    "lat,lon,expected",
    [(27.72, 85.32, "Asia/Kathmandu"), (-43.95, -176.55, "Pacific/Chatham")],
)
def test_timezone_full_dataset(lat, lon, expected):
    """Distinctive zones catch a repeat of the 8.0 dataset shrink."""
    assert TimezoneFinder().timezone_at(lng=lon, lat=lat) == expected


def test_cache_bucket_shares_but_copies():
    cache = SimpleCache(ttl_seconds=600)
    base = datetime(2025, 6, 15, 12, 5, tzinfo=UTC)
    same_bucket = datetime(2025, 6, 15, 12, 10, tzinfo=UTC)
    next_bucket = datetime(2025, 6, 15, 12, 20, tzinfo=UTC)
    cache.set(51.48, 0.0, base, {"meta": {"cache_hit": False}})
    first = cache.get(51.48, 0.0, same_bucket)
    assert first is not None
    assert first == {"meta": {"cache_hit": False}}
    first["meta"]["cache_hit"] = True
    second = cache.get(51.48, 0.0, base)
    assert second == {"meta": {"cache_hit": False}}
    assert cache.get(51.48, 0.0, next_bucket) is None


def test_response_models_accept_new_fields():
    rise = RiseSetInfo(moonrise=None, moonset=None, rise_count=0, set_count=0)
    assert rise.rise_count == 0
    phase = MoonPhaseInfo(
        phase_name="Full Moon",
        phase_angle_degrees=180.0,
        percent_illuminated=100.0,
        age_days=14.7,
        age_is_estimate=False,
    )
    assert phase.age_is_estimate is False


@pytest.mark.parametrize(
    "year,ok",
    [(1848, False), (1849, True), (2150, True), (2151, False)],
)
def test_datetime_range_edges(year, ok):
    dt = datetime(year, 6, 15, 12, tzinfo=UTC)
    result = validate_datetime_range(dt)
    if ok:
        assert result == dt
    else:
        assert isinstance(result, ValidationError)


def test_route_elevation_and_range(eph, ts):
    """Route wiring: elevation plumbed through, bad inputs rejected."""
    state = SimpleNamespace(eph=eph, ts=ts, tf=TimezoneFinder(), start_time=time.time())
    req = cast(Request, SimpleNamespace(app=SimpleNamespace(state=state)))
    base = {"latitude": 51.48, "longitude": 0.0}

    ok = asyncio.run(
        lunalabe_fastapi(
            req, datetime="2025-06-15T12:00:00", elevation=8849.0, **base
        )
    )
    assert isinstance(ok, dict)
    validated = LunarDataResponse.model_validate(ok)
    assert -90.0 <= validated.position.altitude_degrees <= 90.0

    # Native Query bounds are framework-enforced (422); verify the declared
    # OpenAPI contract carries them.
    params = fastapi_app.openapi()["paths"]["/api/v1/lunalabe"]["get"]["parameters"]
    elev_schema = next(p for p in params if p["name"] == "elevation")["schema"]
    assert elev_schema["minimum"] == ELEVATION_MIN_M
    assert elev_schema["maximum"] == ELEVATION_MAX_M

    bad_date = asyncio.run(
        lunalabe_fastapi(
            req, datetime="1800-01-01T12:00:00", elevation=0.0, **base
        )
    )
    assert isinstance(bad_date, JSONResponse)
    assert bad_date.status_code == 400


def test_assembly_payload_keys(eph, ts):
    """The assembly seam takes plain values — no doubles needed."""
    local_tz = ZoneInfo("Europe/London")
    local_dt = datetime.fromisoformat("2025-06-15T12:00:00").replace(tzinfo=local_tz)
    payload = assemble_lunar_payload(
        latitude=51.48,
        longitude=0.0,
        elevation_m=0.0,
        local_dt=local_dt,
        local_tz=local_tz,
        timezone_str="Europe/London",
        eph=eph,
        ts=ts,
    )
    assert not isinstance(payload, CalculationError)
    assert payload["phase_info"]["phase_name"] == "Waning Gibbous"
    assert payload["rise_and_set"]["rise_count"] == 1
    assert payload["location"] == "Lat: 51.48, Lon: 0.0"


def test_assembly_setup_failure_is_error_value(ts):
    payload = assemble_lunar_payload(
        latitude=0.0,
        longitude=0.0,
        elevation_m=0.0,
        local_dt=datetime(2025, 6, 15, 12, tzinfo=UTC),
        local_tz=ZoneInfo("UTC"),
        timezone_str="UTC",
        eph=None,
        ts=ts,
    )
    assert isinstance(payload, CalculationError)
