@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
  echo Python 3.11 or later was not found.
  echo Install Python from https://www.python.org/downloads/windows/
  echo and enable the Python launcher.
  echo.
  if not defined GITLAB_MIGRATOR_NO_PAUSE pause
  exit /b 1
)

py -3 "%~dp0windows_bootstrap.py" %*
set "MIGRATION_EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%MIGRATION_EXIT_CODE%"=="0" (
  echo The migration process did not complete.
  echo Review the error shown above.
)
if not defined GITLAB_MIGRATOR_NO_PAUSE pause
exit /b %MIGRATION_EXIT_CODE%
