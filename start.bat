@echo off
chcp 65001 >nul
echo ================================================================
echo    🚀 启动 LangGraph AI 量化选股系统 (后端服务 + React前端)
echo ================================================================
echo.

echo 1. 正在后台启动 FastAPI 后端服务 (端口: 8000)...
start "LangGraph Backend Server" cmd /k "python server.py"

echo.
echo 2. 正在启动 Vite React 前端开发服务器 (端口: 5173)...
cd /d "%~dp0frontend"
npm.cmd run dev

pause
