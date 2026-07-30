@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
  echo Python が見つかりません。
  echo https://www.python.org/downloads/windows/ から Python 3.11 以上を
  echo インストールし、"py launcher" を有効にしてください。
  echo.
  pause
  exit /b 1
)

py -3 "%~dp0windows_bootstrap.py"
set "MIGRATION_EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%MIGRATION_EXIT_CODE%"=="0" (
  echo 処理は完了していません。上に表示された内容を確認してください。
)
pause
exit /b %MIGRATION_EXIT_CODE%
