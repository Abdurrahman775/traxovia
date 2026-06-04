@echo off
:: Traxovia AI — Stop All Services
:: Run as Administrator

echo.
echo ==> Stopping Windows services...
nssm stop TraxoviaLiveTrading
nssm stop TraxoviaBot
nssm stop TraxoviaBeat
nssm stop TraxoviaWorker
nssm stop TraxoviaAPI

echo.
echo ==> Stopping WSL2 services...
wsl sudo service redis-server stop
wsl sudo service postgresql stop

echo.
echo All services stopped.
pause
