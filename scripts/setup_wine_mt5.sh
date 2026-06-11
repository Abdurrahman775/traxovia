#!/usr/bin/env bash
# scripts/setup_wine_mt5.sh — Install Wine + MT5 on Linux (one-time setup)
#
# Run as the 'kira' user (not root). Sudo password needed for apt commands.
# After this script completes you still need to:
#   1. Launch MT5 under Wine and log in with your broker credentials
#   2. Start mt5-bridge.service
#
# Usage:
#   bash scripts/setup_wine_mt5.sh

set -euo pipefail

WINE_PREFIX="$HOME/.mt5wine"
# Python 3.8 embeddable ZIP — uses msvcrt (old CRT), fully supported by Wine 9.
# Do NOT use Python 3.10+: ucrtbase.dll.crealf is unimplemented in Wine 9.0.
PY_VERSION="3.8.10"
PY_ZIP="python-${PY_VERSION}-embed-amd64.zip"
PY_URL="https://www.python.org/ftp/python/${PY_VERSION}/${PY_ZIP}"
PY_DIR="$WINE_PREFIX/drive_c/Python38"

GET_PIP_URL="https://bootstrap.pypa.io/get-pip.py"

MT5_INSTALLER="mt5setup.exe"
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
    wget unzip cabextract \
    2>/dev/null
echo "      Done."

# ── 2. Create Wine64 prefix ────────────────────────────────────────────────────
echo "[2/7] Creating Wine64 prefix at ${WINE_PREFIX}..."
export WINEPREFIX="$WINE_PREFIX"
export WINEARCH=win64
export DISPLAY=:0

WINEDLLOVERRIDES="mscoree,mshtml=" wineboot --init 2>/dev/null || true
echo "      Done."

# ── 3. Install Wine dependencies ──────────────────────────────────────────────
echo "[3/7] Installing Wine vcrun2019..."
WINEPREFIX="$WINE_PREFIX" WINEARCH=win64 \
    winetricks -q vcrun2019 2>/dev/null || \
    echo "      WARNING: winetricks step had errors — may still work."
echo "      Done."

# ── 4. Install Python 3.8 embeddable ZIP ──────────────────────────────────────
echo "[4/7] Installing Python 3.8 embeddable inside Wine..."
mkdir -p "$PY_DIR"

cd /tmp
if [ ! -f "$PY_ZIP" ]; then
    wget -q --show-progress "$PY_URL" -O "$PY_ZIP"
fi
unzip -qo "$PY_ZIP" -d "$PY_DIR"
echo "      Extracted to ${PY_DIR}"

# Enable site-packages (required for pip-installed packages to be importable)
PTH_FILE="$PY_DIR/python38._pth"
if grep -q "^#import site" "$PTH_FILE" 2>/dev/null; then
    sed -i 's/^#import site/import site/' "$PTH_FILE"
    echo "      Enabled import site in python38._pth"
fi

# Install pip using the virtual desktop trick (provides Windows console)
wget -q "$GET_PIP_URL" -O /tmp/get-pip.py
cp /tmp/get-pip.py "$PY_DIR/../get-pip.py"
wine explorer /desktop=setup,1x1 \
    cmd.exe /c \
    "C:\\Python38\\python.exe C:\\get-pip.py > C:\\pip_install.txt 2>&1" &
echo "      Installing pip (waiting 60s)..."
sleep 60
echo "      Done."

WINE_PYTHON="$PY_DIR/python.exe"
if [ ! -f "$WINE_PYTHON" ]; then
    echo "ERROR: Wine Python not found at ${WINE_PYTHON}"
    exit 1
fi
echo "      Wine Python 3.8 ready."

# ── 5. Install Python packages inside Wine ────────────────────────────────────
echo "[5/7] Installing MetaTrader5 and bridge packages..."
# Write install command to a batch file (avoids shell quoting issues)
cat > /tmp/pip_pkgs.bat << 'BATCH'
C:\Python38\python.exe -m pip install ^
  MetaTrader5 ^
  "fastapi==0.103.2" ^
  "starlette==0.27.0" ^
  "uvicorn==0.33.0" ^
  requests ^
  > C:\pip_pkgs.txt 2>&1
BATCH

cp /tmp/pip_pkgs.bat "$WINE_PREFIX/drive_c/pip_pkgs.bat"
wine explorer /desktop=setup,1x1 \
    cmd.exe /c "C:\\pip_pkgs.bat" &
echo "      Installing packages (waiting 120s)..."
sleep 120
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
echo "2020" | sudo -S cp "$BRIDGE_DIR/mt5-bridge.service" /etc/systemd/system/
echo "2020" | sudo -S cp "$(dirname "$BRIDGE_DIR")/infra/mt5-terminal.service" /etc/systemd/system/ 2>/dev/null || true
echo "2020" | sudo -S systemctl daemon-reload
echo "2020" | sudo -S systemctl enable mt5-terminal.service mt5-bridge.service 2>/dev/null || true
echo "      Services installed and enabled."

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "========================================================"
echo "  Setup complete!"
echo "========================================================"
echo ""
echo "NEXT STEPS:"
echo ""
echo "  1. Launch MT5 terminal and log in with your broker credentials:"
echo "     WINEPREFIX=$WINE_PREFIX DISPLAY=:0 \\"
echo "     wine '$WINE_PREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe'"
echo ""
echo "     Log in, enable 'Allow automated trading', then minimize."
echo ""
echo "  2. Start the services:"
echo "     sudo systemctl start mt5-terminal"
echo "     sudo systemctl start mt5-bridge"
echo ""
echo "  3. Verify it works:"
echo "     curl http://127.0.0.1:8001/health"
echo ""
echo "  4. Add to .env:"
echo "     MT5_BRIDGE_URL=http://127.0.0.1:8001"
echo "     MT5_LOGIN=<your account number>"
echo "     MT5_PASSWORD=<your password>"
echo "     MT5_SERVER=<your broker server>"
echo ""
