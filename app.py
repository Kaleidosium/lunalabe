# FastAPI application entry point for lunalabe API
import logging
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from skyfield.api import load
from timezonefinder import TimezoneFinder

from api.middleware import RateLimitMiddleware
from api.routes import router as api_router
from core.config import RATE_LIMIT

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load astronomical data and initialize app state on startup."""
    try:
        logger.info("Loading astronomical data...")
        app.state.eph = load("de440s.bsp")
        app.state.ts = load.timescale()
        app.state.tf = TimezoneFinder()
        app.state.start_time = time.time()
        logger.info("Astronomical data loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load astronomical data: {e}")
        raise
    yield
    # Shutdown expectation: no persistent resources to release (ephemeris,
    # timescale, and timezone finder are plain in-memory state).
    logger.info("Shutting down lunalabe API")


app = FastAPI(title="lunalabe API", version="1.0.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions and return a JSON error response."""
    # Starlette awaits exception handlers inside an active except block,
    # so exc_info=True captures the real traceback here.
    logger.error(f"Unhandled exception: {exc}", exc_info=True)  # noqa: LOG014
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": str(exc),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        },
    )


app.include_router(api_router)

app.add_middleware(GZipMiddleware)
app.add_middleware(RateLimitMiddleware, calls_per_minute=RATE_LIMIT)
# CORS added last so it runs outermost (Starlette executes last-added first):
# rate-limited 429s carry CORS headers instead of failing opaquely cross-origin.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"]
)

if __name__ == "__main__":
    logger.info("Starting lunalabe API server at http://localhost:8000")
    logger.info("Endpoints:")
    logger.info("  Health check: http://localhost:8000/health")
    logger.info("  Moon data: http://localhost:8000/api/v1/lunalabe")
    logger.info(
        "Example: http://localhost:8000/api/v1/lunalabe?latitude=40.7128&longitude=-74.0060"
    )
    uvicorn.run(app, host="localhost", port=8000)
