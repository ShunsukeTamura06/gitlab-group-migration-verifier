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

py -3 "%~dp0configure_distribution.py"
set "CONFIGURE_EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%CONFIGURE_EXIT_CODE%"=="0" (
  echo 社内配布ZIPは作成されていません。上に表示された内容を確認してください。
)
pause
exit /b %CONFIGURE_EXIT_CODE%
