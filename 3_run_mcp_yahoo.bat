@echo off
setlocal

echo === Portfolio Advisor - Yahoo Finance MCP Server ===
echo.

cd /d "%~dp0mcp-servers\yahoo-finance"

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
        echo INFO: Please edit mcp-servers\yahoo-finance\.env before running.
        echo.
    )
)

echo Activating virtual environment ...
call ".venv\Scripts\activate.bat"

if not defined MCP_AUTH_TOKEN (
    set MCP_AUTH_TOKEN=dev-portfolio-mcp-token
)

echo Starting Yahoo Finance MCP server on http://localhost:8001 ...
echo Press Ctrl+C to stop.
echo.

python server.py
