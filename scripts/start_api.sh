#!/bin/bash
# Start the Trading AI API server persistently
cd /home/kira/trading-bot
source .env 2>/dev/null || true
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8080
