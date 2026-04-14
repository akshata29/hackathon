@echo off
setlocal

echo === Portfolio Advisor - Mock OIDC Server (Simulates Okta) ===
echo.
echo Provides a local OIDC identity provider for demonstrating:
echo   Option B: Multi-IDP trust on MCP servers (TRUSTED_ISSUERS)
echo   Option C: Okta-to-Entra token exchange proxy
echo.
echo Token issuance:
echo   GET  http://localhost:8889/token/for/alice@demo.com
echo   POST http://localhost:8889/token  (form: sub, email, audience, scope)
echo   GET  http://localhost:8889/.well-known/openid-configuration
echo   GET  http://localhost:8889/keys
echo.

cd /d "%~dp0mcp-servers\mock-oidc"

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
        echo.
    )
)

echo Activating virtual environment ...
call ".venv\Scripts\activate.bat"

echo Starting Mock OIDC server on http://localhost:8889 ...
echo Press Ctrl+C to stop.
echo.

python server.py
