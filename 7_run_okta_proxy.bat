@echo off
setlocal

echo === Portfolio Advisor - Okta-to-Entra Token Exchange Proxy (Option C) ===
echo.
echo This proxy sits between Copilot Studio (Okta) and the MCP server.
echo It validates the Okta JWT, maps the user identity, and forwards the
echo request with a valid MCP service token - no second login prompt.
echo.
echo Prerequisites:
echo   1. Start the Mock OIDC server first: 6_run_mock_oidc.bat
echo   2. Start the target MCP server:      3_run_mcp_yahoo.bat
echo.
echo Proxy URL:  http://localhost:8003
echo Target MCP: http://localhost:8001  (set TARGET_MCP_URL in .env to change)
echo.

cd /d "%~dp0mcp-servers\okta-proxy"

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
        echo INFO: Review mcp-servers\okta-proxy\.env - defaults work for local demo.
        echo.
    )
)

echo Activating virtual environment ...
call ".venv\Scripts\activate.bat"

echo Starting Okta proxy on http://localhost:8003 ...
echo Press Ctrl+C to stop.
echo.

python server.py
