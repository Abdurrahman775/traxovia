# =============================================================================
# Traxovia AI - Windows Live Trading Setup
# Run in PowerShell as Administrator from C:\traxovia:
#   Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
#   .\scripts\windows_setup.ps1
# =============================================================================

param(
    [string]$ProjectPath = "C:\traxovia"
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    WARN $msg" -ForegroundColor Yellow }

# --- 1. Check admin ----------------------------------------------------------

Write-Step "Checking admin privileges"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "Run PowerShell as Administrator."
    exit 1
}
Write-Ok "Running as Administrator"

# --- 2. Check project directory ----------------------------------------------

Write-Step "Checking project directory"
if (-not (Test-Path $ProjectPath)) {
    Write-Error "Project not found at $ProjectPath. Run git clone first."
    exit 1
}
Write-Ok "Project found at $ProjectPath"
Set-Location $ProjectPath

# --- 3. Check Python ---------------------------------------------------------

Write-Step "Checking Python"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Error "Python not found. Install Python 3.12 from python.org and re-run."
    exit 1
}
$pyVer = python --version 2>&1
Write-Ok "Found: $pyVer"

# --- 4. Install Python dependencies ------------------------------------------

Write-Step "Installing Python dependencies"
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
python -m pip install MetaTrader5 --quiet
Write-Ok "All packages installed (including MetaTrader5)"

# --- 5. Install NSSM ---------------------------------------------------------

Write-Step "Installing NSSM"
$nssmPath = Get-Command nssm -ErrorAction SilentlyContinue
if (-not $nssmPath) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id NSSM.NSSM --silent --accept-package-agreements --accept-source-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        Write-Ok "NSSM installed via winget"
    } else {
        Write-Error "NSSM not found and winget unavailable. Install NSSM manually from nssm.cc then re-run."
        exit 1
    }
} else {
    Write-Ok "NSSM already available"
}

# --- 6. Create logs directory ------------------------------------------------

Write-Step "Creating logs directory"
New-Item -ItemType Directory -Path "$ProjectPath\logs" -Force | Out-Null
Write-Ok "Logs directory ready: $ProjectPath\logs"

# --- 7. Register TraxoviaLiveTrading service ----------------------------------

Write-Step "Registering TraxoviaLiveTrading service"
$python = (Get-Command python).Source

$existing = Get-Service -Name TraxoviaLiveTrading -ErrorAction SilentlyContinue
if ($existing) {
    Write-Warn "Service already exists - removing old registration"
    nssm remove TraxoviaLiveTrading confirm
}

nssm install TraxoviaLiveTrading $python "live_trading_loop.py"
nssm set TraxoviaLiveTrading AppDirectory $ProjectPath
nssm set TraxoviaLiveTrading AppEnvironmentExtra "PYTHONPATH=$ProjectPath"
nssm set TraxoviaLiveTrading AppStdout "$ProjectPath\logs\live_trading.log"
nssm set TraxoviaLiveTrading AppStderr "$ProjectPath\logs\live_trading.log"
nssm set TraxoviaLiveTrading Start SERVICE_DEMAND_START
Write-Ok "TraxoviaLiveTrading service registered (demand-start)"

# --- Done --------------------------------------------------------------------

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Yellow
Write-Host "    1. Open MT5 terminal and log in to your account" -ForegroundColor Yellow
Write-Host "    2. Tools > Options > Expert Advisors:" -ForegroundColor Yellow
Write-Host "       [x] Allow automated trading" -ForegroundColor Yellow
Write-Host "       [x] Allow DLL imports" -ForegroundColor Yellow
Write-Host "    3. Start the live trading service:" -ForegroundColor Yellow
Write-Host "       nssm start TraxoviaLiveTrading" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Check logs:" -ForegroundColor Cyan
Write-Host "    Get-Content $ProjectPath\logs\live_trading.log -Wait" -ForegroundColor Cyan
Write-Host ""
