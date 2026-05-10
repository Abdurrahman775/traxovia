@echo off
:: Traxovia AI — Start All Services
:: Run as Administrator

echo.
echo ==> Starting WSL2 services (Redis + PostgreSQL)...
wsl sudo service redis-server start
wsl sudo service postgresql start

echo.
echo ==> Starting Windows services...
nssm start TraxoviaAPI
nssm start TraxoviaWorker
nssm start TraxoviaBeat
nssm start TraxoviaBot

echo.
echo ==> Service status:
timeout /t 2 /nobreak >nul
sc query TraxoviaAPI    | findstr "STATE"
sc query TraxoviaWorker | findstr "STATE"
sc query TraxoviaBeat   | findstr "STATE"
sc query TraxoviaBot    | findstr "STATE"

echo.
echo Done. API at http://localhost:8000
pause
