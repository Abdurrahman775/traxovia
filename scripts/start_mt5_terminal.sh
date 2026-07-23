#!/usr/bin/env bash
# Resolve the current Xwayland auth file dynamically (changes each session)
XAUTH_FILE=$(ls /run/user/1000/.mutter-Xwaylandauth.* 2>/dev/null | head -1)
if [ -n "$XAUTH_FILE" ]; then
    export XAUTHORITY="$XAUTH_FILE"
fi

export DISPLAY=:0
export WINEPREFIX=/home/kira/.mt5wine
export WINEARCH=win64

exec /usr/bin/wine "C:\\Program Files\\MetaTrader 5\\terminal64.exe" /portable
