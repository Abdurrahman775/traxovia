# =============================================================================
# Traxovia AI — Windows VPS Setup Script
# Run this in PowerShell as Administrator:
#   Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
#   .\scripts\windows_setup.ps1
# =============================================================================

param(
    [string]$ProjectPath = "C:\traxovia",
    [string]$EnvFile     = ".env"
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  WARN $msg" -ForegroundColor Yellow }

# ── 1. Check prerequisites ─────────────────────────────────────────────────────

Write-Step "Checking prerequisites"

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Run PowerShell as Administrator."
    exit 1
}

# Check winget
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Error "winget not found. Install App Installer from the Microsoft Store first."
    exit 1
}
Write-Ok "winget available"

# ── 2. Install Python 3.12 ────────────────────────────────────────────────────

Write-Step "Installing Python 3.12"
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py -and (python --version 2>&1) -match "3\.1[2-9]") {
    Write-Ok "Python 3.12+ already installed"
} else {
    winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    Write-Ok "Python 3.12 installed"
}

# ── 3. Enable WSL2 ────────────────────────────────────────────────────────────

Write-Step "Enabling WSL2 (for Redis + PostgreSQL)"
$wslFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux
if ($wslFeature.State -ne "Enabled") {
    Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -NoRestart
    Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -NoRestart
    Write-Warn "WSL2 features enabled — a REBOOT is required before continuing."
    Write-Warn "After rebooting, run: wsl --install -d Ubuntu  then re-run this script."
    exit 0
} else {
    Write-Ok "WSL2 already enabled"
}

# Check Ubuntu is installed
$wslDistros = wsl --list --quiet 2>$null
if ($wslDistros -notmatch "Ubuntu") {
    Write-Warn "Ubuntu not found in WSL2. Installing..."
    wsl --install -d Ubuntu --no-launch
    Write-Warn "Ubuntu installed. You must open Ubuntu once to complete setup, then re-run this script."
    exit 0
}
Write-Ok "Ubuntu WSL2 available"

# ── 4. Clone / copy project ───────────────────────────────────────────────────

Write-Step "Setting up project at $ProjectPath"
if (-not (Test-Path $ProjectPath)) {
    New-Item -ItemType Directory -Path $ProjectPath | Out-Null
    Write-Warn "Created $ProjectPath — copy your project files here before continuing."
    Write-Warn "Or run: git clone <your-repo-url> $ProjectPath"
} else {
    Write-Ok "Project directory exists"
}

# ── 5. Install Python dependencies ───────────────────────────────────────────

Write-Step "Installing Python dependencies"
Set-Location $ProjectPath

if (-not (Test-Path "requirements.txt")) {
    Write-Error "requirements.txt not found in $ProjectPath"
    exit 1
}

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install MetaTrader5

Write-Ok "Python packages installed (including MetaTrader5)"

# ── 6. Install NSSM (service manager) ────────────────────────────────────────

Write-Step "Installing NSSM (Windows service manager)"
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    winget install --id NSSM.NSSM --silent --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    Write-Ok "NSSM installed"
} else {
    Write-Ok "NSSM already available"
}

# ── 7. Run WSL2 setup (Redis + PostgreSQL/TimescaleDB) ───────────────────────

Write-Step "Setting up Redis + PostgreSQL inside WSL2"
$wslScript = (Get-Item ".\scripts\wsl_setup.sh").FullName -replace "\\", "/" -replace "^([A-Za-z]):", { "/mnt/$($_.Value.ToLower())" }
wsl bash "$wslScript"
Write-Ok "WSL2 services configured"

# ── 8. Register Windows services via NSSM ────────────────────────────────────

Write-Step "Registering Windows services"

$python  = (Get-Command python).Source
$projDir = $ProjectPath

# FastAPI
nssm install TraxoviaAPI $python "-m" "uvicorn" "main:app" "--host" "0.0.0.0" "--port" "8000" "--workers" "2"
nssm set TraxoviaAPI AppDirectory $projDir
nssm set TraxoviaAPI AppEnvironmentExtra "PYTHONPATH=$projDir"
nssm set TraxoviaAPI AppStdout "$projDir\logs\api.log"
nssm set TraxoviaAPI AppStderr "$projDir\logs\api.log"
nssm set TraxoviaAPI Start SERVICE_AUTO_START
Write-Ok "TraxoviaAPI service registered"

# Celery worker (--pool=solo required on Windows)
nssm install TraxoviaWorker $python "-m" "celery" "-A" "scheduler.tasks" "worker" "--pool=solo" "--loglevel=info"
nssm set TraxoviaWorker AppDirectory $projDir
nssm set TraxoviaWorker AppEnvironmentExtra "PYTHONPATH=$projDir"
nssm set TraxoviaWorker AppStdout "$projDir\logs\worker.log"
nssm set TraxoviaWorker AppStderr "$projDir\logs\worker.log"
nssm set TraxoviaWorker Start SERVICE_AUTO_START
Write-Ok "TraxoviaWorker service registered"

# Celery beat (scheduler)
nssm install TraxoviaBeat $python "-m" "celery" "-A" "scheduler.tasks" "beat" "--loglevel=info"
nssm set TraxoviaBeat AppDirectory $projDir
nssm set TraxoviaBeat AppEnvironmentExtra "PYTHONPATH=$projDir"
nssm set TraxoviaBeat AppStdout "$projDir\logs\beat.log"
nssm set TraxoviaBeat AppStderr "$projDir\logs\beat.log"
nssm set TraxoviaBeat Start SERVICE_AUTO_START
Write-Ok "TraxoviaBeat service registered"

# Telegram bot
nssm install TraxoviaBot $python "-m" "tg_bot.bot"
nssm set TraxoviaBot AppDirectory $projDir
nssm set TraxoviaBot AppEnvironmentExtra "PYTHONPATH=$projDir"
nssm set TraxoviaBot AppStdout "$projDir\logs\bot.log"
nssm set TraxoviaBot AppStderr "$projDir\logs\bot.log"
nssm set TraxoviaBot Start SERVICE_AUTO_START
Write-Ok "TraxoviaBot service registered"

# Live trading loop (Windows-only — requires MT5 terminal running and logged in)
# Set MT5_LOGIN / MT5_PASSWORD / MT5_SERVER / LIVE_USER_ID in .env before starting.
nssm install TraxoviaLiveTrading $python "live_trading_loop.py"
nssm set TraxoviaLiveTrading AppDirectory $projDir
nssm set TraxoviaLiveTrading AppEnvironmentExtra "PYTHONPATH=$projDir"
nssm set TraxoviaLiveTrading AppStdout "$projDir\logs\live_trading.log"
nssm set TraxoviaLiveTrading AppStderr "$projDir\logs\live_trading.log"
nssm set TraxoviaLiveTrading Start SERVICE_DEMAND_START
Write-Ok "TraxoviaLiveTrading service registered (demand-start — start manually when ready)"

# ── 9. Create logs directory ──────────────────────────────────────────────────

New-Item -ItemType Directory -Path "$projDir\logs" -Force | Out-Null

# ── 10. Start all services ────────────────────────────────────────────────────

Write-Step "Starting all services"

# Start WSL2 Redis + PostgreSQL first
wsl sudo service redis-server start
wsl sudo service postgresql start

# Then Windows services
nssm start TraxoviaAPI
nssm start TraxoviaWorker
nssm start TraxoviaBeat
nssm start TraxoviaBot
# TraxoviaLiveTrading is demand-start — do NOT auto-start here.
# Start it manually once MT5 credentials are set in .env:
#   nssm start TraxoviaLiveTrading

Write-Ok "All services started (live trading loop NOT auto-started — start manually)"

# ── Done ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Traxovia AI setup complete!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  IMPORTANT: MT5 terminal must be:" -ForegroundColor Yellow
Write-Host "    1. Installed from your broker" -ForegroundColor Yellow
Write-Host "    2. Running and logged in at all times" -ForegroundColor Yellow
Write-Host "    3. Tools > Options > Expert Advisors:" -ForegroundColor Yellow
Write-Host "       [x] Allow automated trading" -ForegroundColor Yellow
Write-Host "       [x] Allow DLL imports" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Services running:" -ForegroundColor Cyan
Write-Host "    TraxoviaAPI          http://localhost:8000" -ForegroundColor Cyan
Write-Host "    TraxoviaWorker       Celery tasks" -ForegroundColor Cyan
Write-Host "    TraxoviaBeat         Celery scheduler" -ForegroundColor Cyan
Write-Host "    TraxoviaBot          Telegram bot" -ForegroundColor Cyan
Write-Host "    TraxoviaLiveTrading  LIVE MT5 loop (start manually)" -ForegroundColor Yellow
Write-Host ""
Write-Host "  To start live trading:" -ForegroundColor Yellow
Write-Host "    1. Set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER in .env" -ForegroundColor Yellow
Write-Host "    2. Ensure MT5 terminal is open and logged in" -ForegroundColor Yellow
Write-Host "    3. nssm start TraxoviaLiveTrading" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Manage services:" -ForegroundColor Cyan
Write-Host "    nssm start|stop|restart TraxoviaAPI" -ForegroundColor Cyan
Write-Host "    Get-Service Traxovia* | Select Name,Status" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Logs: $projDir\logs\" -ForegroundColor Cyan
Write-Host ""
