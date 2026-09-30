"""Pure orchestration for the lunar payload: no HTTP, no cache, no app state.

The route owns transport (validation, timezone shaping, caching, meta); this
module owns computation. Tests cross this seam directly with plain values.
"""

from datetime import datetime, timedelta, tzinfo

from skyfield.api import Topos

from api.exceptions import CalculationError
from core.lunar_calculations import (
    calculate_lunar_eclipses,
    calculate_phase_info,
    calculate_position_info,
    calculate_rise_set_info,
    calculate_upcoming_phases,
)
from models.models import UpcomingPhases


def assemble_lunar_payload(
    *,
    latitude: float,
    longitude: float,
    elevation_m: float,
    local_dt: datetime,
    local_tz: tzinfo,
    timezone_str: str,
    eph,
    ts,
) -> dict | CalculationError:
    """Compute the response body (everything except ``meta``)."""
    try:
        earth = eph["earth"]
        t = ts.from_datetime(local_dt)
        location = Topos(
            latitude_degrees=latitude,
            longitude_degrees=longitude,
            elevation_m=elevation_m,
        )
        observer = earth + location
        day_start = local_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = ts.from_datetime(day_start)
        window_end = ts.from_datetime(day_start + timedelta(days=1))
    # Deliberate catch-all: convert skyfield setup failures into an error value.
    except Exception as e:  # noqa: BLE001
        return CalculationError(f"Failed to calculate lunar data: {e!s}")

    phase_info = calculate_phase_info(eph, ts, t)
    if isinstance(phase_info, CalculationError):
        return phase_info
    position = calculate_position_info(eph, ts, t, observer)
    if isinstance(position, CalculationError):
        return position
    rise_and_set = calculate_rise_set_info(
        ts, eph, location, window_start, window_end, local_tz
    )
    if isinstance(rise_and_set, CalculationError):
        # Never mask as nulls: nulls mean a genuine no-rise/no-set day.
        return rise_and_set

    upcoming = calculate_upcoming_phases(ts, eph, t, local_tz)
    if isinstance(upcoming, CalculationError):
        upcoming = UpcomingPhases()
    eclipses = calculate_lunar_eclipses(ts, eph, t)
    if isinstance(eclipses, CalculationError):
        eclipses = []

    return {
        "request_time_utc": t.utc_iso(),
        "request_time_local": local_dt.isoformat(),
        "location": f"Lat: {latitude}, Lon: {longitude}",
        "timezone": timezone_str,
        "phase_info": phase_info.model_dump(),
        "position": position.model_dump(),
        "rise_and_set": rise_and_set.model_dump(),
        "upcoming_major_phases": upcoming.model_dump(),
        "upcoming_lunar_eclipses": [e.model_dump() for e in eclipses],
    }
