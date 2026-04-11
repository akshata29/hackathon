@echo off
setlocal

echo === Portfolio Advisor - Frontend ===
echo.

cd /d "%~dp0frontend"

where node >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found. Install it from https://nodejs.org/
    exit /b 1
)

if not exist "node_modules" (
    echo Installing npm dependencies ...
    npm install
    if errorlevel 1 (
        echo ERROR: npm install failed.
        exit /b 1
    )
    echo.
)

if not exist ".env" (
    if exist ".env.example" (
        echo INFO: .env not found. Copying from .env.example ...
        copy ".env.example" ".env" >nul
        echo INFO: Please edit frontend\.env and fill in your values before running.
        echo.
    ) else (
        echo WARNING: No .env or .env.example found. Running without environment file.
        echo.
    )
)

echo Starting frontend on http://localhost:5173 ...
echo Press Ctrl+C to stop.
echo.

npm run dev
