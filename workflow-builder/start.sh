#!/usr/bin/env bash
# Starts backend (port 8001) and frontend (port 5174) in parallel.
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "=== Surveillance Workflow Builder ==="
echo ""
echo "Starting backend on http://localhost:8001 ..."
(cd "$ROOT/backend" && python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload) &
BACKEND_PID=$!

echo "Starting frontend on http://localhost:5174 ..."
(cd "$ROOT/frontend" && npm run dev) &
FRONTEND_PID=$!

echo ""
echo "Both servers running."
echo "  Frontend → http://localhost:5174"
echo "  Backend  → http://localhost:8001"
echo ""
echo "Press Ctrl+C to stop both."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
