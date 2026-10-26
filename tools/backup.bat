@echo off
rem ---------------------------------------------------------------------
rem  Thin wrapper for backup.ps1 so it can be launched from cmd or by
rem  double-clicking. Keeps ExecutionPolicy out of the way.
rem  Usage:  backup.bat "fix: message" [-Tag v0.1.1] [-Both]
rem ---------------------------------------------------------------------
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup.ps1" %*
if errorlevel 1 (
  echo.
  echo Backup script exited with an error. Press any key to close.
  pause >nul
)
endlocal
