@echo off
setlocal

echo === Portfolio Advisor - Portfolio DB MCP Server ===
echo.

cd /d "%~dp0mcp-servers\portfolio-db"

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
        echo INFO: Please edit mcp-servers\portfolio-db\.env before running.
        echo.
    )
)

echo Activating virtual environment ...
call ".venv\Scripts\activate.bat"

echo Starting Portfolio DB MCP server on http://localhost:8002 ...
echo Press Ctrl+C to stop.
echo.

set DB_PATH=%~dp0data\portfolio.db
if exist "%DB_PATH%" (
    echo Using local SQLite database: %DB_PATH%
) else (
    echo INFO: Local SQLite DB not found at %DB_PATH%
    echo       Run: python scripts\seed-portfolio-db.py  to create it.
    echo       Falling back to in-memory synthetic data.
)
echo.

python server.py
