#!/usr/bin/env bash
# Start Celery worker + beat for Traxovia AI
# Usage: ./scripts/start_workers.sh

set -e
cd "$(dirname "$0")/.."

source venv/bin/activate

LOG_DIR="/tmp/traxovia"
mkdir -p "$LOG_DIR"

echo "Starting Celery worker..."
celery -A scheduler.tasks worker \
  --pool=solo \
  --loglevel=info \
  --logfile="$LOG_DIR/celery_worker.log" \
  --pidfile="$LOG_DIR/celery_worker.pid" \
  --detach

echo "Starting Celery beat..."
celery -A scheduler.tasks beat \
  --loglevel=info \
  --logfile="$LOG_DIR/celery_beat.log" \
  --pidfile="$LOG_DIR/celery_beat.pid" \
  --detach

sleep 3

echo ""
echo "Worker log: $LOG_DIR/celery_worker.log"
echo "Beat log:   $LOG_DIR/celery_beat.log"
echo ""
echo "Status:"
celery -A scheduler.tasks inspect ping 2>/dev/null || echo "(ping timeout — worker may still be starting)"
