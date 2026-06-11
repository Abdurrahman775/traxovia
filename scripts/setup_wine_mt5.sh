#!/usr/bin/env bash
# scripts/setup_wine_mt5.sh — Install Wine + MT5 on Linux (one-time setup)
#
# Run as the 'kira' user (not root). Sudo password is needed for apt commands.
# After this script completes you still need to:
#   1. Start the xvfb service (virtual display)
#   2. Launch MT5 under Wine and log in with your broker credentials
#   3. Start mt5-bridge.service
#
# Usage:
#   bash scripts/setup_wine_mt5.sh

set -euo pipefail

WINE_PREFIX="$HOME/.mt5wine"
PYTHON_INSTALLER="python-3.10.11-amd64.exe"
PYTHON_URL="https://www.python.org/ftp/python/3.10.11/${PYTHON_INSTALLER}"
MT5_INSTALLER="mt5setup.exe"
# MT5 installer URL — Exness (replace with your broker's MT5 download link if different)
MT5_URL="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
BRIDGE_DIR="$(cd "$(dirname "$0")/.." && pwd)/mt5_bridge"

echo "========================================================"
echo "  Traxovia AI — Wine + MT5 Linux Setup"
echo "========================================================"
echo ""

# ── 1. System packages ─────────────────────────────────────────────────────────
echo "[1/7] Installing system packages..."
echo "2020" | sudo -S apt-get update -qq
echo "2020" | sudo -S apt-get install -y -qq \
    wine wine64 winetricks \
    xvfb x11-utils \
    wget cabextract \
    2>/dev/null
echo "      Done."

# ── 2. Create Wine64 prefix ────────────────────────────────────────────────────
echo "[2/7] Creating Wine64 prefix at ${WINE_PREFIX}..."
export WINEPREFIX="$WINE_PREFIX"
export WINEARCH=win64
export DISPLAY=:0

# Initialize prefix silently
WINEDLLOVERRIDES="mscoree,mshtml=" wineboot --init 2>/dev/null || true
echo "      Done."

# ── 3. Install Wine dependencies for MT5 ──────────────────────────────────────
echo "[3/7] Installing Wine components (vcrun2019, dotnet48)..."
echo "      This may take several minutes..."
WINEPREFIX="$WINE_PREFIX" WINEARCH=win64 \
    winetricks -q vcrun2019 dotnet48 2>/dev/null || \
    echo "      WARNING: winetricks step had errors — may still work."
echo "      Done."

# ── 4. Download and install Python 3.10 inside Wine ───────────────────────────
echo "[4/7] Downloading Windows Python 3.10..."
cd /tmp
if [ ! -f "$PYTHON_INSTALLER" ]; then
    wget -q --show-progress "$PYTHON_URL" -O "$PYTHON_INSTALLER"
fi

echo "      Installing Python 3.10 inside Wine..."
WINEPREFIX="$WINE_PREFIX" WINEARCH=win64 DISPLAY=:0 \
    wine "$PYTHON_INSTALLER" /quiet InstallAllUsers=0 PrependPath=1 \
    TargetDir="C:\\Python310" 2>/dev/null || true
echo "      Done."

# Verify
WINE_PYTHON="$WINE_PREFIX/drive_c/Python310/python.exe"
if [ ! -f "$WINE_PYTHON" ]; then
    echo "ERROR: Wine Python not found at ${WINE_PYTHON}"
    echo "       The installer may have failed. Try running it manually:"
    echo "       WINEPREFIX=$WINE_PREFIX DISPLAY=:0 wine /tmp/$PYTHON_INSTALLER"
    exit 1
fi
echo "      Wine Python found: ${WINE_PYTHON}"

# ── 5. Install Python packages inside Wine ────────────────────────────────────
echo "[5/7] Installing MetaTrader5 and bridge packages inside Wine Python..."
WINEPREFIX="$WINE_PREFIX" WINEARCH=win64 DISPLAY=:0 \
    wine "$WINE_PYTHON" -m pip install --quiet \
    MetaTrader5 \
    "fastapi==0.111.0" \
    "uvicorn[standard]==0.29.0" \
    requests \
    python-dotenv
echo "      Done."

# ── 6. Download and install MT5 terminal ──────────────────────────────────────
echo "[6/7] Downloading MT5 terminal..."
cd /tmp
if [ ! -f "$MT5_INSTALLER" ]; then
    wget -q --show-progress "$MT5_URL" -O "$MT5_INSTALLER"
fi

echo "      Installing MT5 terminal inside Wine..."
echo "      (A window will open — accept the license and let it install)"
WINEPREFIX="$WINE_PREFIX" WINEARCH=win64 DISPLAY=:0 \
    wine "$MT5_INSTALLER" /auto 2>/dev/null || true

echo "      Done (MT5 installed — you must log in manually on first run)."

# ── 7. Install systemd services ───────────────────────────────────────────────
echo "[7/7] Installing systemd services..."
echo "2020" | sudo -S cp "$BRIDGE_DIR/xvfb.service"      /etc/systemd/system/
echo "2020" | sudo -S cp "$BRIDGE_DIR/mt5-bridge.service" /etc/systemd/system/
echo "2020" | sudo -S systemctl daemon-reload
echo "2020" | sudo -S systemctl enable xvfb.service
echo "2020" | sudo -S systemctl enable mt5-bridge.service
echo "      Services installed and enabled."

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "========================================================"
echo "  Setup complete!"
echo "========================================================"
echo ""
echo "NEXT STEPS:"
echo ""
echo "  1. Start the virtual display:"
echo "     sudo systemctl start xvfb"
echo ""
echo "  2. Launch MT5 terminal and log in with your broker credentials:"
echo "     WINEPREFIX=$WINE_PREFIX DISPLAY=:0 \\"
echo "     wine '$WINE_PREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe'"
echo ""
echo "     Log in, enable 'Allow automated trading', then close the window."
echo "     MT5 will auto-start in future when the bridge server initializes it."
echo ""
echo "  3. Start the bridge:"
echo "     sudo systemctl start mt5-bridge"
echo ""
echo "  4. Verify it works:"
echo "     curl http://127.0.0.1:8001/health"
echo ""
echo "  5. Add to .env:"
echo "     MT5_BRIDGE_URL=http://127.0.0.1:8001"
echo "     MT5_LOGIN=<your account number>"
echo "     MT5_PASSWORD=<your password>"
echo "     MT5_SERVER=<your broker server, e.g. Exness-MT5Real8>"
echo ""
