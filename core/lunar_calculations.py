import logging
from datetime import timedelta
from typing import cast

from skyfield import almanac, eclipselib

from api.exceptions import CalculationError
from core.utils import get_zodiac_sign
from models.models import (
    EclipseInfo,
    MoonPhaseInfo,
    MoonPosition,
    RiseSetInfo,
    UpcomingPhases,
)

logger = logging.getLogger(__name__)

# Scan windows must exceed one synodic month (29.53 days) so the window always
# contains the event being searched for.
MOON_AGE_SCAN_DAYS = 31
UPCOMING_PHASES_WINDOW_DAYS = 35

# Eclipse forecast policy: how far ahead to look and how many entries to keep.
ECLIPSE_WINDOW_DAYS = 365 * 2
ECLIPSE_LIMIT = 5

# Phase-name buckets: equal 45° sectors centered on the cardinal phases.
PHASE_SECTOR_DEGREES = 45
PHASE_SECTOR_OFFSET_DEGREES = 22.5

# Index of the new moon in almanac.moon_phases() output.
NEW_MOON_INDEX = 0


def calculate_phase_info(eph, ts, t) -> MoonPhaseInfo | CalculationError:
    try:
        # Skyfield's Angle.degrees is float-like at runtime.
        moon_phase_angle = cast(float, almanac.moon_phase(eph, t).degrees)
        percent_illuminated = almanac.fraction_illuminated(eph, "moon", t) * 100
        phase_names = [
            "New Moon",
            "Waxing Crescent",
            "First Quarter",
            "Waxing Gibbous",
            "Full Moon",
            "Waning Gibbous",
            "Last Quarter",
            "Waning Crescent",
        ]
        phase_name = phase_names[
            int(
                ((moon_phase_angle + PHASE_SECTOR_OFFSET_DEGREES) % 360)
                // PHASE_SECTOR_DEGREES
            )
        ]
        past_times, past_kinds = almanac.find_discrete(
            t - timedelta(days=MOON_AGE_SCAN_DAYS), t, almanac.moon_phases(eph)
        )
        new_moon_found = past_kinds == NEW_MOON_INDEX
        if new_moon_found.any():
            last_new_moon = past_times[new_moon_found][-1]
            moon_age_days = t.tt - last_new_moon.tt
            age_is_estimate = False
        else:
            # Sentinel: 0.0 here means "no new moon found in window", which is
            # otherwise indistinguishable from a true new moon.
            moon_age_days = 0
            age_is_estimate = True
        return MoonPhaseInfo(
            phase_name=phase_name,
            phase_angle_degrees=round(float(moon_phase_angle), 2),
            percent_illuminated=round(float(percent_illuminated), 2),
            age_days=round(float(moon_age_days), 2),
            age_is_estimate=age_is_estimate,
        )
    # Deliberate catch-all: convert any skyfield failure into an error value.
    except Exception as e:  # noqa: BLE001
        logger.error(f"Phase calculation error: {e}")
        return CalculationError("Failed to calculate moon phase information")


def calculate_position_info(eph, ts, t, observer) -> MoonPosition | CalculationError:
    try:
        moon = eph["moon"]
        apparent_pos = observer.at(t).observe(moon).apparent()
        altitude, azimuth, distance = apparent_pos.altaz()
        moon_pos = moon.at(t)
        ecliptic_lon = moon_pos.ecliptic_latlon()[1].degrees
        zodiac_sign = get_zodiac_sign(ecliptic_lon)
        return MoonPosition(
            altitude_degrees=round(float(altitude.degrees), 2),
            azimuth_degrees=round(float(azimuth.degrees), 2),
            distance_km=round(float(distance.km), 2),
            zodiac_sign=zodiac_sign,
        )
    # Deliberate catch-all: convert any skyfield failure into an error value.
    except Exception as e:  # noqa: BLE001
        logger.error(f"Position calculation error: {e}")
        return CalculationError("Failed to calculate moon position")


def calculate_rise_set_info(
    ts, eph, location, start_time, end_time, local_tz
) -> RiseSetInfo | CalculationError:
    """Rise/set attributed to one local day.

    Only events inside ``[start_time, end_time)`` count, so the pair can never
    straddle days. ``rise_count``/``set_count`` make 0- and 2-event days
    explicit. Failures return a ``CalculationError`` value — never nulls, which
    are reserved for genuine no-rise/no-set days.
    """
    try:
        rise_set_fn = almanac.risings_and_settings(eph, eph["moon"], location)
        times, is_rise = almanac.find_discrete(start_time, end_time, rise_set_fn)
        in_day = [
            (moment, rose) for moment, rose in zip(times, is_rise) if moment.tt < end_time.tt
        ]
        rises = [moment.astimezone(local_tz).isoformat() for moment, rose in in_day if rose]
        sets = [
            moment.astimezone(local_tz).isoformat() for moment, rose in in_day if not rose
        ]
        return RiseSetInfo(
            moonrise=rises[0] if rises else None,
            moonset=sets[0] if sets else None,
            rise_count=len(rises),
            set_count=len(sets),
        )
    # Deliberate catch-all: convert any skyfield failure into an error value.
    except Exception as e:  # noqa: BLE001
        logger.error(f"Rise/set calculation error: {e}")
        return CalculationError("Failed to calculate moonrise and moonset")


def calculate_upcoming_phases(
    ts, eph, t, local_tz
) -> UpcomingPhases | CalculationError:
    try:
        future_times, future_kinds = almanac.find_discrete(
            t, t + timedelta(days=UPCOMING_PHASES_WINDOW_DAYS), almanac.moon_phases(eph)
        )
        phases = {
            "next_new_moon": None,
            "next_first_quarter": None,
            "next_full_moon": None,
            "next_last_quarter": None,
        }
        keys = [
            "next_new_moon",
            "next_first_quarter",
            "next_full_moon",
            "next_last_quarter",
        ]
        for phase_idx, key in enumerate(keys):
            phase_times = future_times[future_kinds == phase_idx]
            if len(phase_times) > 0:
                phases[key] = phase_times[0].astimezone(local_tz).isoformat()
        return UpcomingPhases(**phases)
    # Deliberate catch-all: convert any skyfield failure into an error value.
    except Exception as e:  # noqa: BLE001
        logger.error(f"Upcoming phases calculation error: {e}")
        return CalculationError("Failed to calculate upcoming moon phases")


def calculate_lunar_eclipses(ts, eph, t) -> list[EclipseInfo] | CalculationError:
    """Next eclipses over a 2-year window, capped at 5 entries.

    These are global events, not observer-visible ones. The cap can truncate
    penumbral-heavy windows; kept deliberately with this documented meaning.
    """
    try:
        window_end = t + timedelta(days=ECLIPSE_WINDOW_DAYS)
        times, kinds, _ = eclipselib.lunar_eclipses(t, window_end, eph)
        kind_names = {0: "Penumbral", 1: "Partial", 2: "Total"}
        eclipses = []
        for moment, kind in zip(times, kinds):
            eclipses.append(
                EclipseInfo(
                    event_time_utc=moment.utc_iso(),
                    event_type=f"Lunar Eclipse ({kind_names.get(kind, 'Unknown')})",
                )
            )
        return eclipses[:ECLIPSE_LIMIT]
    # Deliberate catch-all: convert any skyfield failure into an error value.
    except Exception as e:  # noqa: BLE001
        logger.error(f"Eclipse calculation error: {e}")
        return CalculationError("Failed to calculate lunar eclipses")
