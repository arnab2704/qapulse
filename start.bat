@echo off
echo.
echo   =============================================
echo   QA Pulse -- Starting server...
echo   =============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found. Install from https://python.org
    pause
    exit /b 1
)

echo   Starting on http://localhost:7337
echo   Press Ctrl+C to stop
echo.

start "" http://localhost:7337
python server.py
pause
