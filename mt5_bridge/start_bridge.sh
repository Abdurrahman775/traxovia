#!/usr/bin/env bash
# mt5_bridge/start_bridge.sh — Launch the MT5 bridge server inside Wine.
# Uses Python 3.8 (embeddable) — avoids ucrtbase.dll.crealf issue in Wine 9.x.

export DISPLAY=:0
export WINEPREFIX=~/.mt5wine
export WINEARCH=win64
export MT5_BRIDGE_PORT="${MT5_BRIDGE_PORT:-8001}"

LOG=/home/kira/trading-bot/logs/mt5_bridge.log
mkdir -p /home/kira/trading-bot/logs

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting MT5 bridge on port ${MT5_BRIDGE_PORT}" >> "$LOG"

exec wine explorer /desktop=bridge,1x1 \
  cmd.exe /c \
  "C:\\Python38\\python.exe Z:\\home\\kira\\trading-bot\\mt5_bridge\\server.py >> Z:\\home\\kira\\trading-bot\\logs\\mt5_bridge.log 2>&1"
