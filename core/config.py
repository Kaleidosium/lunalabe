# Configuration for lunalabe API: environment variables with defaults.
import os

CACHE_TTL = int(os.environ.get("CACHE_TTL", "600"))  # Cache time-to-live in seconds
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "60"))  # Requests per minute per IP

# DE440s ephemeris coverage (years). Datetimes outside this range are rejected;
# accuracy past ~2027 degrades with Earth-rotation predictions (documented).
EPHEMERIS_START_YEAR = 1849
EPHEMERIS_END_YEAR = 2150

# Observer elevation bounds (meters) enforced natively by FastAPI Query.
ELEVATION_MIN_M = -500
ELEVATION_MAX_M = 9000
