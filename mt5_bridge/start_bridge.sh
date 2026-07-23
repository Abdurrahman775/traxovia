#!/usr/bin/env bash
# mt5_bridge/start_bridge.sh — Launch the MT5 bridge server inside Wine.
# Uses Python 3.8 (embeddable) — avoids ucrtbase.dll.crealf issue in Wine 9.x.
# Uses bridge_launcher.py which calls AllocConsole() so Python 3.8 can
# initialize stdio handles when running without a TTY (systemd service).

export DISPLAY=:0
export WINEPREFIX=~/.mt5wine
export WINEARCH=win64
export MT5_BRIDGE_PORT="${MT5_BRIDGE_PORT:-8001}"

# Resolve current Xwayland auth file dynamically (changes each session)
XAUTH_FILE=$(ls /run/user/1000/.mutter-Xwaylandauth.* 2>/dev/null | head -1)
if [ -n "$XAUTH_FILE" ]; then
    export XAUTHORITY="$XAUTH_FILE"
fi

LOG=/home/kira/trading-bot/logs/mt5_bridge.log
mkdir -p /home/kira/trading-bot/logs
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting MT5 bridge on port ${MT5_BRIDGE_PORT}" >> "$LOG"

export MT5_BRIDGE_LOG="$LOG"

exec wine start /wait /unix /home/kira/.mt5wine/drive_c/run_bridge.bat
