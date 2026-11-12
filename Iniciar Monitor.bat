@echo off
cd /d "%~dp0"
if exist "C:\Python315\pythonw.exe" (
    start "" "C:\Python315\pythonw.exe" "ajazz_battery.pyw"
) else (
    start "" pythonw "ajazz_battery.pyw"
)
exit

