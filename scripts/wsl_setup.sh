#!/usr/bin/env bash
# =============================================================================
# Traxovia AI — WSL2 Ubuntu Setup Script
# Called automatically by windows_setup.ps1:
#   wsl bash "./scripts/wsl_setup.sh"
#
# Installs and configures:
#   - PostgreSQL 16 + TimescaleDB 2.x
#   - Redis 7
#   - Creates the trading_ai database and runs schema migrations
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  OK  $1${NC}"; }
warn() { echo -e "${YELLOW}  WARN $1${NC}"; }
fail() { echo -e "${RED}  ERROR $1${NC}"; exit 1; }
step() { echo -e "\n==> $1"; }

# ── 1. System update ──────────────────────────────────────────────────────────

step "Updating apt package lists"
sudo apt-get update -qq
ok "apt updated"

# ── 2. Install prerequisites ──────────────────────────────────────────────────

step "Installing prerequisites"
sudo apt-get install -y -qq \
    curl wget gnupg lsb-release ca-certificates \
    apt-transport-https software-properties-common
ok "Prerequisites installed"

# ── 3. Install PostgreSQL 16 ──────────────────────────────────────────────────

step "Installing PostgreSQL 16"

PG_VERSION=16
PG_CONF="/etc/postgresql/${PG_VERSION}/main/postgresql.conf"
PG_HBA="/etc/postgresql/${PG_VERSION}/main/pg_hba.conf"

if ! command -v psql &>/dev/null; then
    # Add PostgreSQL official APT repository
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | sudo gpg --dearmor -o /usr/share/keyrings/postgresql.gpg
    echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] \
https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
        | sudo tee /etc/apt/sources.list.d/pgdg.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq postgresql-${PG_VERSION} postgresql-client-${PG_VERSION}
    ok "PostgreSQL ${PG_VERSION} installed"
else
    ok "PostgreSQL already installed"
fi

# ── 4. Install TimescaleDB ────────────────────────────────────────────────────

step "Installing TimescaleDB"

if ! dpkg -l | grep -q timescaledb-2; then
    curl -fsSL https://packagecloud.io/timescale/timescaledb/gpgkey \
        | sudo gpg --dearmor -o /usr/share/keyrings/timescaledb.gpg
    echo "deb [signed-by=/usr/share/keyrings/timescaledb.gpg] \
https://packagecloud.io/timescale/timescaledb/ubuntu/ $(lsb_release -cs) main" \
        | sudo tee /etc/apt/sources.list.d/timescaledb.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq timescaledb-2-postgresql-${PG_VERSION}
    ok "TimescaleDB installed"
else
    ok "TimescaleDB already installed"
fi

# ── 5. Configure PostgreSQL ───────────────────────────────────────────────────

step "Configuring PostgreSQL"

# Enable TimescaleDB in shared_preload_libraries
if ! grep -q "timescaledb" "$PG_CONF" 2>/dev/null; then
    sudo sed -i "s/#shared_preload_libraries = ''/shared_preload_libraries = 'timescaledb'/" "$PG_CONF"
    # If the line wasn't commented out, try without the #
    if ! grep -q "timescaledb" "$PG_CONF"; then
        echo "shared_preload_libraries = 'timescaledb'" | sudo tee -a "$PG_CONF"
    fi
    ok "TimescaleDB added to shared_preload_libraries"
else
    ok "TimescaleDB already in shared_preload_libraries"
fi

# Allow connections from Windows host (WSL2 gateway)
if ! grep -q "host.*trading_ai" "$PG_HBA" 2>/dev/null; then
    echo "host trading_ai trading_app 0.0.0.0/0 scram-sha-256" \
        | sudo tee -a "$PG_HBA" > /dev/null
    ok "pg_hba.conf updated"
fi

# Listen on all interfaces so Windows host can connect
sudo sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" "$PG_CONF"

ok "PostgreSQL configured"

# ── 6. Start PostgreSQL ───────────────────────────────────────────────────────

step "Starting PostgreSQL"
sudo service postgresql start
sleep 2
if sudo service postgresql status | grep -q "online\|running"; then
    ok "PostgreSQL running"
else
    fail "PostgreSQL failed to start — check /var/log/postgresql/"
fi

# ── 7. Create DB user and database ───────────────────────────────────────────

step "Creating database user and database"

# Read credentials from .env if available (Windows path mounted as /mnt/c/...)
DB_USER="${DB_USER:-trading_app}"
DB_PASSWORD="${DB_PASSWORD:-changeme_in_env}"
DB_NAME="${DB_NAME:-trading_ai}"

# Try to source .env from project directory (WSL path)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
    # Extract DB vars safely (no eval — grep + cut only)
    _val() { grep -m1 "^$1=" "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'" | awk '{print $1}'; }
    [[ -n "$(_val DB_USER)"     ]] && DB_USER="$(_val DB_USER)"
    [[ -n "$(_val DB_PASSWORD)" ]] && DB_PASSWORD="$(_val DB_PASSWORD)"
    [[ -n "$(_val DB_NAME)"     ]] && DB_NAME="$(_val DB_NAME)"
    ok ".env loaded — user=$DB_USER db=$DB_NAME"
else
    warn ".env not found at $ENV_FILE — using defaults (change DB_PASSWORD!)"
fi

# Create role if not exists
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" \
    | grep -q 1 || \
    sudo -u postgres psql -c \
        "CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';"

# Create database if not exists
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" \
    | grep -q 1 || \
    sudo -u postgres psql -c \
        "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

# Grant privileges
sudo -u postgres psql -d "${DB_NAME}" -c \
    "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};" > /dev/null

# Enable TimescaleDB extension
sudo -u postgres psql -d "${DB_NAME}" -c \
    "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;" > /dev/null

ok "Database '${DB_NAME}' ready with TimescaleDB"

# ── 8. Run schema migrations ──────────────────────────────────────────────────

step "Running schema migrations"

MIGRATIONS_DIR="$PROJECT_ROOT/database/migrations"

if [[ -d "$MIGRATIONS_DIR" ]]; then
    # Run migration files in order
    for sql_file in $(ls "$MIGRATIONS_DIR"/*.sql 2>/dev/null | sort); do
        filename=$(basename "$sql_file")
        echo "    Applying $filename ..."
        PGPASSWORD="$DB_PASSWORD" psql \
            -h localhost -U "$DB_USER" -d "$DB_NAME" \
            -f "$sql_file" -q \
            && echo "    OK  $filename" \
            || warn "Migration $filename had errors (may already be applied)"
    done
    ok "Migrations complete"
else
    warn "No migrations directory at $MIGRATIONS_DIR — skipping"
fi

# ── 9. Install Redis 7 ────────────────────────────────────────────────────────

step "Installing Redis 7"

if ! command -v redis-server &>/dev/null; then
    curl -fsSL https://packages.redis.io/gpg \
        | sudo gpg --dearmor -o /usr/share/keyrings/redis.gpg
    echo "deb [signed-by=/usr/share/keyrings/redis.gpg] \
https://packages.redis.io/deb $(lsb_release -cs) main" \
        | sudo tee /etc/apt/sources.list.d/redis.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq redis
    ok "Redis installed"
else
    ok "Redis already installed"
fi

# ── 10. Configure Redis ───────────────────────────────────────────────────────

step "Configuring Redis"

REDIS_CONF="/etc/redis/redis.conf"

# Bind to all interfaces so Windows can reach it
sudo sed -i 's/^bind 127.0.0.1.*/bind 0.0.0.0/' "$REDIS_CONF"

# Set a password if REDIS_PASSWORD is in .env
REDIS_PASSWORD=""
if [[ -f "$ENV_FILE" ]]; then
    _rp() { grep -m1 "^REDIS_PASSWORD=" "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'" | awk '{print $1}'; }
    REDIS_PASSWORD="$(_rp)"
fi

if [[ -n "$REDIS_PASSWORD" ]] && [[ "$REDIS_PASSWORD" != "your-redis-password" ]]; then
    sudo sed -i "s/^# requirepass foobared/requirepass ${REDIS_PASSWORD}/" "$REDIS_CONF"
    sudo sed -i "s/^requirepass .*/requirepass ${REDIS_PASSWORD}/" "$REDIS_CONF"
    ok "Redis password set"
else
    warn "No REDIS_PASSWORD in .env — Redis running without auth (OK for local WSL2)"
fi

# ── 11. Start Redis ───────────────────────────────────────────────────────────

step "Starting Redis"
sudo service redis-server start
sleep 1

if redis-cli ping 2>/dev/null | grep -q PONG; then
    ok "Redis responding to PING"
else
    warn "Redis may not be running — check: sudo service redis-server status"
fi

# ── 12. Configure WSL2 services to auto-start ─────────────────────────────────

step "Configuring WSL2 auto-start on Windows boot"

WSLCONF="/etc/wsl.conf"
if ! grep -q "\[boot\]" "$WSLCONF" 2>/dev/null; then
    sudo tee "$WSLCONF" > /dev/null <<'EOF'
[boot]
command = "service postgresql start; service redis-server start"

[network]
generateResolvConf = true
EOF
    ok "/etc/wsl.conf created — services will start on WSL2 boot"
else
    ok "/etc/wsl.conf already configured"
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "================================================================"
echo -e "${GREEN}  WSL2 setup complete!${NC}"
echo "================================================================"
echo ""
echo "  Services:"
echo "    PostgreSQL  localhost:5432   db=${DB_NAME}  user=${DB_USER}"
echo "    Redis       localhost:6379"
echo ""
echo "  From Windows, connect via:"
echo "    DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}"
echo "    REDIS_URL=redis://localhost:6379"
echo ""
echo "  Manual control:"
echo "    wsl sudo service postgresql start|stop|restart"
echo "    wsl sudo service redis-server start|stop|restart"
echo ""
