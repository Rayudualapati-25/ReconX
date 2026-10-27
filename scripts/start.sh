#!/bin/sh
# Container entrypoint: serve the API.
set -eu

# exec replaces the shell, so uvicorn receives SIGTERM directly and shuts down cleanly.
exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
