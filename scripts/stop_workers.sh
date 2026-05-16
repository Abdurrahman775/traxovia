#!/usr/bin/env bash
# Stop Celery worker + beat
cd "$(dirname "$0")/.."
source venv/bin/activate

PID_DIR="/tmp/traxovia"

for name in celery_worker celery_beat; do
  pid_file="$PID_DIR/$name.pid"
  if [ -f "$pid_file" ]; then
    pid=$(cat "$pid_file")
    kill "$pid" 2>/dev/null && echo "Stopped $name (PID $pid)" || echo "$name not running"
    rm -f "$pid_file"
  else
    echo "$name pidfile not found"
  fi
done
