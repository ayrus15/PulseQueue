# Single image for both the API and the worker - docker-compose.yml's
# "api" and "worker" services run it with different commands. There's
# no runtime difference between them beyond that (see
# docs/architecture.md): same package, same dependencies, same config.
FROM python:3.11-slim AS runtime

WORKDIR /app

# libpq isn't needed at runtime (asyncpg is a pure C extension wheel,
# no libpq.so dependency), so no extra OS packages beyond the base image.
COPY pyproject.toml ./
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./

RUN pip install --no-cache-dir .

# Runs as a non-root user - no part of this app needs root.
RUN useradd --create-home --shell /bin/bash pulsequeue
USER pulsequeue

EXPOSE 8000

CMD ["uvicorn", "pulsequeue.main:app", "--host", "0.0.0.0", "--port", "8000"]
