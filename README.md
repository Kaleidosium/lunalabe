# lunalabe API

lunalabe is a FastAPI-based web service for lunar phase, position, and event calculations. It uses Skyfield for astronomy, derives the timezone from the query coordinates, and applies rate limiting and caching.

## Repository and deployment

The canonical repository is on [Tangled](https://tangled.org/kaleidosium.my.id/lunalabe/). It is mirrored to GitHub.

The official deploy is at <https://lunalabe.kaleidosium.my.id/docs>. Please self-host it if you want higher rate limits or a guarantee it stays up. I cannot pay much for hosting the official API.

## Features

- Lunar phase, position, rise/set, and eclipse calculations
- Timezone-aware queries (automatic lookup by coordinates)
- Configurable rate limiting and cache TTL via environment variables
- OpenAPI/Swagger documentation at `/docs` and ReDoc at `/redoc`
- Async serving via uvicorn

## Configuration

Set environment variables to adjust rate limiting and cache TTL:

- `RATE_LIMIT` (default: 60 requests/minute)
- `CACHE_TTL` (default: 600 seconds)

## Docker

`docker build -t lunalabe .` bakes `de440s.bsp` and the IERS timescale into the image, so containers start with no network dependency for astronomy data.

## License

This project is licensed under the [MIT License](LICENSE).
