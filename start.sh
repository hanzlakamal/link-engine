#!/bin/sh
set -e
if [ "${ROLE:-web}" = "worker" ]; then
  exec python -m app.worker
else
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
fi
