"""
core/execution_engine/mt5_bridge_standby.py — Standby MT5 bridge server.

Runs on a second Windows VPS from a DIFFERENT provider than the primary
(per Master Review: use Vultr for primary, Hetzner/OVH/Linode for standby).
Using a different provider ensures a datacentre outage on VPS A cannot take
down both bridges simultaneously.

This module is intentionally a thin wrapper around mt5_bridge.py. All endpoint
logic, authentication, and MT5 connection management lives there. This file
only forces IS_STANDBY=true before the import so that:
  - /health returns  "is_standby": true
  - app.description shows "STANDBY instance"
  - logs include "(STANDBY)" in the connection line

Launch (on Windows VPS B):
    uvicorn core.execution_engine.mt5_bridge_standby:app --host 0.0.0.0 --port 8002 --workers 1

Environment variables (.env on standby VPS — same keys as primary):
    MT5_ACCOUNT        — standby MT5 account number (can be same account as primary)
    MT5_PASSWORD       — MT5 account password
    MT5_SERVER         — broker server name
    MT5_BRIDGE_API_KEY — must match the value on the Linux VPS and primary bridge
    MT5_BRIDGE_PORT    — port to listen on (default: 8002 on standby)

Watchdog promotion flow (bridge_watchdog.py):
    1. Primary /health returns degraded or times out for ≥ 5 minutes
    2. Watchdog POSTs /mt5/initialize to this server (re-initialises MT5 connection)
    3. Watchdog updates bridge_state["active_url"] to point at this server
    4. All subsequent data and execution calls go to this server
    5. When primary recovers, watchdog demotes this server back to standby
"""

import os

# Force IS_STANDBY before importing mt5_bridge so the flag is set at module
# load time (it is read as a module-level constant in mt5_bridge.py).
os.environ.setdefault("IS_STANDBY", "true")

# Re-export the fully configured FastAPI app — no logic duplication.
from core.execution_engine.mt5_bridge import app  # noqa: F401, E402


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("MT5_BRIDGE_PORT", "8002"))   # default 8002, not 8001
    uvicorn.run(
        "core.execution_engine.mt5_bridge_standby:app",
        host="0.0.0.0",
        port=port,
        workers=1,          # must be 1 — single MT5 terminal per process
        log_level="info",
    )
