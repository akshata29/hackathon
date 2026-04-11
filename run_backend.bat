@echo off
setlocal

echo === Portfolio Advisor - Backend ===
echo.

cd /d "%~dp0backend"

if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: .venv not found. Please create it first:
    echo   cd backend
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    exit /b 1
)

if not exist ".env" (
    if exist ".env.example" (
        echo INFO: .env not found. Copying from .env.example ...
        copy ".env.example" ".env" >nul
        echo INFO: Please edit backend\.env and fill in your values before running.
        echo.
    ) else (
        echo WARNING: No .env or .env.example found. Running without environment file.
        echo.
    )
)

echo Activating virtual environment ...
call ".venv\Scripts\activate.bat"

echo Starting backend on http://localhost:8000 ...
echo Press Ctrl+C to stop.
echo.

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
