@echo off
chcp 65001 >nul
set ROOT_DIR=%~dp0..\..
cd /d "%ROOT_DIR%"

echo ==============================================================================
echo  [Windows] 正在将 Node 1 + Node 2 每日定时任务注册至 Windows 系统任务计划程序...
echo ==============================================================================

set TASK_NAME=FinAgent_Daily_Node1_Node2
set PYTHON_EXE=pythonw.exe
where %PYTHON_EXE% >nul 2>nul
if %errorlevel% neq 0 (
    set PYTHON_EXE=python.exe
)
set SCRIPT_PATH=%ROOT_DIR%\agent\run_nodes_1_2.py

echo 任务名称: %TASK_NAME%
echo 执行时间: 每天 01:30
echo 执行脚本: %SCRIPT_PATH%
echo Python解释器: %PYTHON_EXE% (静默无黑窗模式)

schtasks /create /tn "%TASK_NAME%" /tr "\"%PYTHON_EXE%\" \"%SCRIPT_PATH%\"" /sc daily /st 01:30 /f

if %errorlevel% equ 0 (
    echo.
    echo [成功] Windows 系统定时任务已成功创建！
    echo 将在每天 01:30 自动调用 Python 执行 Node 1 和 Node 2。
) else (
    echo.
    echo [提示] 如需直接在 Windows 系统级注册计划任务，请以管理员身份运行本脚本。
)

echo.
pause
