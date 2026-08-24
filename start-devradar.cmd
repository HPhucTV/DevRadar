@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-devradar.ps1"
if errorlevel 1 (
  echo.
  echo DevRadar could not start. Review the message above.
  pause
  exit /b 1
)
endlocal
