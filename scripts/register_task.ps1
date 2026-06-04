$action = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "C:\traxovia\live_trading_loop.py" `
    -WorkingDirectory "C:\traxovia"

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit 0 `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName "TraxoviaLiveTrading" `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force

Start-ScheduledTask -TaskName "TraxoviaLiveTrading"
Write-Host "Done. Checking task state..."
Get-ScheduledTask -TaskName "TraxoviaLiveTrading" | Select-Object TaskName, State
