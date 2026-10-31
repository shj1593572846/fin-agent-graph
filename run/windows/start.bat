@echo off
chcp 65001 >nul
set ROOT_DIR=%~dp0..\..
cd /d "%ROOT_DIR%"

echo ================================================================
echo    [Windows] LangGraph AI 量化选股系统 (后端服务 + React前端)
echo ================================================================
echo.

REM 1. 检查 Python 解释器
set PYTHON_CMD=python
if exist "%ROOT_DIR%\.venv\Scripts\python.exe" set PYTHON_CMD="%ROOT_DIR%\.venv\Scripts\python.exe"
if exist "%ROOT_DIR%\venv\Scripts\python.exe" set PYTHON_CMD="%ROOT_DIR%\venv\Scripts\python.exe"

REM 2. 启动 FastAPI 后端服务
echo [1/2] 正在独立窗口启动 FastAPI 后端服务 (server.py, 端口: 8000)...
start "LangGraph Backend Server" /d "%ROOT_DIR%" cmd /k "%PYTHON_CMD% server.py"

REM 等待 2 秒让后端初始化
timeout /t 2 /nobreak >nul 2>&1

REM 3. 启动 Vite React 前端开发服务器
echo.
echo [2/2] 正在启动 Vite React 前端开发服务器 (端口: 5173)...
cd /d "%ROOT_DIR%\frontend"

call npm.cmd run dev

pause
