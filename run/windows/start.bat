@echo off
chcp 65001 >nul
title LangGraph AI Quantitative Stock Picker

set "CURRENT_DIR=%~dp0"
pushd "%CURRENT_DIR%..\.."
set "ROOT_DIR=%CD%"

echo ================================================================
echo    [Windows] LangGraph AI Quantitative Stock System
echo ================================================================
echo.

set "PYTHON_CMD=python"
if exist "%ROOT_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%ROOT_DIR%\.venv\Scripts\python.exe"
) else if exist "%ROOT_DIR%\venv\Scripts\python.exe" (
    set "PYTHON_CMD=%ROOT_DIR%\venv\Scripts\python.exe"
)

echo [1/2] Starting FastAPI Backend Server (server.py, Port: 8000)...
start "LangGraph Backend Server" cmd /k "cd /d "%ROOT_DIR%" && "%PYTHON_CMD%" server.py"

echo Waiting for backend initialization...
timeout /t 3 /nobreak >nul 2>&1

echo.
echo [2/2] Starting Vite React Frontend Console (Port: 5173)...
if not exist "%ROOT_DIR%\frontend\package.json" (
    echo [ERROR] Frontend directory not found: %ROOT_DIR%\frontend
    popd
    pause
    exit /b 1
)

cd /d "%ROOT_DIR%\frontend"
call npm.cmd run dev

popd
pause
