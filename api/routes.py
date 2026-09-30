import asyncio
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from api.exceptions import CalculationError, ValidationError
from core.assembly import assemble_lunar_payload
from core.cache import SimpleCache
from core.config import ELEVATION_MAX_M, ELEVATION_MIN_M
from core.utils import (
    parse_datetime_string,
    validate_coordinates,
    validate_datetime_range,
)
from models.models import ErrorResponse, HealthCheckResponse, LunarDataResponse

router = APIRouter()
cache = SimpleCache()


@router.get("/health", response_model=HealthCheckResponse)
async def health_check_fastapi(request: Request):
    """Health and readiness check endpoint."""
    uptime = time.time() - request.app.state.start_time
    response = HealthCheckResponse(
        status="healthy",
        timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        uptime_seconds=round(uptime, 2),
    )
    return response


def _error_response(error: str, message: str, status_code: int) -> JSONResponse:
    """Build a JSON error response with a UTC timestamp."""
    payload = ErrorResponse(
        error=error,
        message=message,
        timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    return JSONResponse(payload.model_dump(), status_code=status_code)


@router.get("/api/v1/lunalabe", response_model=LunarDataResponse)
async def lunalabe_fastapi(
    request: Request,
    latitude: float = Query(51.48, description="Latitude in decimal degrees"),
    longitude: float = Query(0.0, description="Longitude in decimal degrees"),
    datetime: str | None = Query(None, description="Datetime (ISO 8601 or similar)"),
    elevation: float = Query(
        0.0,
        ge=ELEVATION_MIN_M,
        le=ELEVATION_MAX_M,
        description="Observer elevation in meters",
    ),
):
    """Main lunar data endpoint.

    Datetimes must fall within DE440s coverage (1849–2150); accuracy past
    ~2027 degrades with Earth-rotation predictions.
    """
    start_time = time.time()
    app = request.app

    validated = validate_coordinates(latitude, longitude)
    if isinstance(validated, ValidationError):
        return _error_response("Validation Error", validated.detail, 400)
    latitude, longitude = validated

    tf = app.state.tf
    timezone_str = tf.timezone_at(lng=longitude, lat=latitude) or "UTC"
    local_tz = ZoneInfo(timezone_str)

    local_dt = parse_datetime_string(datetime, local_tz)
    if isinstance(local_dt, ValidationError):
        return _error_response("Validation Error", local_dt.detail, 400)
    ranged = validate_datetime_range(local_dt)
    if isinstance(ranged, ValidationError):
        return _error_response("Validation Error", ranged.detail, 400)

    cache_key_dt = local_dt.replace(second=0, microsecond=0)
    cached_result = cache.get(latitude, longitude, cache_key_dt)
    if cached_result:
        calculation_time = (time.time() - start_time) * 1000
        cached_result["meta"]["calculation_time_ms"] = round(calculation_time, 2)
        cached_result["meta"]["cache_hit"] = True
        return cached_result

    result = await asyncio.to_thread(
        assemble_lunar_payload,
        latitude=latitude,
        longitude=longitude,
        elevation_m=elevation,
        local_dt=local_dt,
        local_tz=local_tz,
        timezone_str=timezone_str,
        eph=app.state.eph,
        ts=app.state.ts,
    )
    if isinstance(result, CalculationError):
        return _error_response("Calculation Error", result.detail, 500)

    calculation_time = (time.time() - start_time) * 1000
    response_data = {
        "meta": {
            "api_version": "1.0.0",
            "calculation_time_ms": round(calculation_time, 2),
            "data_source": "JPL DE440",
            "cache_hit": False,
        },
        **result,
    }
    cache.set(latitude, longitude, cache_key_dt, response_data)
    return response_data
