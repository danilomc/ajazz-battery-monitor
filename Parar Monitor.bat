@echo off
chcp 65001 >nul
echo Encerrando Monitor de Bateria Ajazz...
taskkill /F /FI "WINDOWTITLE eq Ajazz*" >nul 2>&1
wmic process where "commandline like '%%ajazz_battery.pyw%%'" delete >nul 2>&1
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'ajazz_battery\.pyw' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
echo Monitor encerrado com sucesso.
pause
