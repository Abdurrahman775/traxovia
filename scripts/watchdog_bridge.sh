#!/usr/bin/env bash
# Watchdog: keeps the SSH tunnel to the Windows VM MT5 bridge alive.
# Reconnects automatically if the tunnel drops or the VM restarts.
#
# Usage:
#   bash scripts/watchdog_bridge.sh <vm_user> <vm_ip> [ssh_key]
#
# Example:
#   bash scripts/watchdog_bridge.sh Administrator 203.0.113.10 ~/.ssh/vm_key
#
# Forwards VM port 8001 → localhost:8001

set -euo pipefail

VM_USER="${1:?Usage: $0 <vm_user> <vm_ip> [ssh_key]}"
VM_IP="${2:?Usage: $0 <vm_user> <vm_ip> [ssh_key]}"
SSH_KEY="${3:-}"

LOG="bridge_watchdog.log"
HEALTH_URL="http://127.0.0.1:8001/health"
SSH_OPTS="-o StrictHostKeyChecking=no -o ServerAliveInterval=10 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -N -L 8001:127.0.0.1:8001"
[[ -n "$SSH_KEY" ]] && SSH_OPTS="-i $SSH_KEY $SSH_OPTS"

echo "[$(date '+%F %T')] Tunnel watchdog started → $VM_USER@$VM_IP:8001" | tee -a "$LOG"

while true; do
    echo "[$(date '+%F %T')] Opening SSH tunnel..." | tee -a "$LOG"
    # shellcheck disable=SC2086
    ssh $SSH_OPTS "$VM_USER@$VM_IP" >> "$LOG" 2>&1 || true
    echo "[$(date '+%F %T')] Tunnel dropped — reconnecting in 5s" | tee -a "$LOG"
    sleep 5
done
