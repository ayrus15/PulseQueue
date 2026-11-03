#!/bin/sh
# Render's dockerCommand field doesn't reliably interpret shell syntax
# (&&, quotes) passed inline in render.yaml - a real script file sidesteps
# that entirely. Applies pending migrations, then starts the API;
# alembic upgrade head is a no-op when already current, so this is safe
# to run on every boot, not just the first one.
set -e
alembic upgrade head
exec uvicorn pulsequeue.main:app --host 0.0.0.0 --port "$PORT"
