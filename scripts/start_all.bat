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
:: TraxoviaLiveTrading is demand-start.
:: Start manually after setting MT5_LOGIN/MT5_PASSWORD/MT5_SERVER in .env:
::   nssm start TraxoviaLiveTrading

echo.
echo ==> Service status:
timeout /t 2 /nobreak >nul
sc query TraxoviaAPI          | findstr "STATE"
sc query TraxoviaWorker       | findstr "STATE"
sc query TraxoviaBeat         | findstr "STATE"
sc query TraxoviaBot          | findstr "STATE"
sc query TraxoviaLiveTrading  | findstr "STATE"

echo.
echo Done. API at http://localhost:8000
echo NOTE: Start live trading manually with:  nssm start TraxoviaLiveTrading
pause
