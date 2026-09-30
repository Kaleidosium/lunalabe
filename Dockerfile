# Bakes de440s.bsp + the IERS timescale into the image so startup needs no
# network (spec section F). The ephemeris stays out of git; it ships here.
FROM python:3.14-slim

WORKDIR /srv/lunalabe

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev

COPY . .
RUN .venv/bin/python -c \
    "from skyfield.api import load; load('de440s.bsp'); load.timescale()"

EXPOSE 8080
CMD ["sh", "-c", ".venv/bin/uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
