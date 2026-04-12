@echo off
setlocal

echo === Portfolio Advisor - ESG Advisor A2A Agent ===
echo.

cd /d "%~dp0a2a-agents\esg-advisor"

if not exist ".venv\Scripts\activate.bat" (
    echo Creating virtual environment ...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create .venv. Make sure Python is installed.
        exit /b 1
    )
    echo Installing dependencies ...
    .venv\Scripts\pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo ERROR: pip install failed.
        exit /b 1
    )
    echo.
)

if not exist ".env" (
    if exist ".env.example" (
        echo INFO: .env not found. Copying from .env.example ...
        copy ".env.example" ".env" >nul
        echo INFO: Please edit a2a-agents\esg-advisor\.env and set your LLM credentials.
        echo       Then re-run this script.
        echo.
        pause
        exit /b 0
    )
)

echo Activating virtual environment ...
call ".venv\Scripts\activate.bat"

echo.
echo Starting ESG Advisor A2A server on http://localhost:8010
echo Agent card: http://localhost:8010/.well-known/agent.json
echo Press Ctrl+C to stop.
echo.
echo NOTE: Set ESG_ADVISOR_URL=http://localhost:8010 in backend\.env to enable
echo       the ESG agent in the portfolio workflow.
echo.

python server.py
