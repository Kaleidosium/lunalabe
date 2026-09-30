from pydantic import BaseModel, Field


class MoonPhaseInfo(BaseModel):
    phase_name: str
    phase_angle_degrees: float = Field(..., ge=0, le=360)
    percent_illuminated: float = Field(..., ge=0, le=100)
    age_days: float = Field(..., ge=0)
    # True when no new moon was found in the scan window: age_days is then a
    # 0.0 fallback, not a true new moon.
    age_is_estimate: bool = False


class MoonPosition(BaseModel):
    altitude_degrees: float = Field(..., ge=-90, le=90)
    azimuth_degrees: float = Field(..., ge=0, le=360)
    distance_km: float = Field(..., gt=0)
    zodiac_sign: str


class RiseSetInfo(BaseModel):
    moonrise: str | None = None
    moonset: str | None = None
    # Event counts for the local day; 0/2-event days are explicit, and nulls
    # always mean a genuine no-rise/no-set day, never a masked failure.
    rise_count: int = Field(default=0, ge=0)
    set_count: int = Field(default=0, ge=0)


class UpcomingPhases(BaseModel):
    next_new_moon: str | None = None
    next_first_quarter: str | None = None
    next_full_moon: str | None = None
    next_last_quarter: str | None = None


class EclipseInfo(BaseModel):
    event_time_utc: str
    event_type: str


class APIMetadata(BaseModel):
    api_version: str = "1.0.0"
    calculation_time_ms: float
    data_source: str = "JPL DE440"
    cache_hit: bool = False


class LunarDataResponse(BaseModel):
    meta: APIMetadata
    request_time_utc: str
    request_time_local: str
    location: str
    timezone: str
    phase_info: MoonPhaseInfo
    position: MoonPosition
    rise_and_set: RiseSetInfo
    upcoming_major_phases: UpcomingPhases
    upcoming_lunar_eclipses: list[EclipseInfo]


class HealthCheckResponse(BaseModel):
    status: str
    timestamp: str
    uptime_seconds: float
    version: str = "1.0.0"


class ErrorResponse(BaseModel):
    error: str
    message: str
    timestamp: str
