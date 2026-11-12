#!/bin/bash
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate
trap 'trap - EXIT; kill 0' INT TERM EXIT   # Ctrl+C stops everything below
python server.py --host 127.0.0.1 &
(cd frontend && npm run dev) &
sleep 4
open -a "Google Chrome" http://localhost:5173
wait
