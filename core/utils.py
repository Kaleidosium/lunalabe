from datetime import datetime, tzinfo

from api.exceptions import ValidationError
from core.config import EPHEMERIS_END_YEAR, EPHEMERIS_START_YEAR


def validate_coordinates(
    latitude: float, longitude: float
) -> tuple[float, float] | ValidationError:
    if not (-90 <= latitude <= 90):
        return ValidationError(f"Latitude must be between -90 and 90, got {latitude}")
    if not (-180 <= longitude <= 180):
        return ValidationError(
            f"Longitude must be between -180 and 180, got {longitude}"
        )
    return latitude, longitude


def parse_datetime_string(
    datetime_str: str | None, local_tz: tzinfo
) -> datetime | ValidationError:
    if not datetime_str:
        return datetime.now(local_tz)
    try:
        # fromisoformat() handles the "Z" suffix natively on Python 3.11+.
        parsed_dt = datetime.fromisoformat(datetime_str)
        if parsed_dt.tzinfo is None:
            return parsed_dt.replace(tzinfo=local_tz)
        return parsed_dt.astimezone(local_tz)
    except ValueError:
        return ValidationError(
            f"Invalid datetime format: {datetime_str}. Use ISO format (YYYY-MM-DDTHH:MM:SS)"
        )


def validate_datetime_range(dt: datetime) -> datetime | ValidationError:
    if not (EPHEMERIS_START_YEAR <= dt.year <= EPHEMERIS_END_YEAR):
        return ValidationError(
            "Datetime must fall within DE440s coverage "
            f"({EPHEMERIS_START_YEAR}–{EPHEMERIS_END_YEAR}), got {dt.year}"
        )
    return dt


# A full circle holds twelve 30° zodiac signs.
DEGREES_PER_SIGN = 30
FULL_CIRCLE_DEGREES = 360


def get_zodiac_sign(ecliptic_lon: float) -> str:
    zodiac_signs = [
        "Aries",
        "Taurus",
        "Gemini",
        "Cancer",
        "Leo",
        "Virgo",
        "Libra",
        "Scorpio",
        "Sagittarius",
        "Capricorn",
        "Aquarius",
        "Pisces",
    ]
    # Normalize first: exact 360° multiples wrap to Aries, and cusps at exact
    # 30° multiples belong to the following sign.
    return zodiac_signs[int((ecliptic_lon % FULL_CIRCLE_DEGREES) // DEGREES_PER_SIGN)]
