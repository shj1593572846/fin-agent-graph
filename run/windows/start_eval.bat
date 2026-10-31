@echo off
chcp 65001 >nul
set ROOT_DIR=%~dp0..\..
cd /d "%ROOT_DIR%"

echo ================================================================
echo    [Windows] LangGraph 选股多 Agent 全生命周期评测控制台 (Eval)
echo ================================================================
echo.
echo 请选择评测执行模式：
echo   [1] 🧪 标杆场景回归评测 (高动能牛市复现，含LLM专家裁判)
echo   [2] 🛡️ 弱势防守场景评测 (单边下挫行情，考核空仓风控纪律)
echo   [3] 💾 本地真实产物评测 (基于 stock_data/ 现场数据出具诊断)
echo   [4] ⚡ 端到端全链路执行 (实时调度 Node 1-6 选股并插桩审计)
echo   [5] 🌐 启动 Web 前后端工作台 (在网页中可视化评测与查看仪表盘)
echo   [0] 退出
echo.

set /p user_choice=请输入编号 (0-5) [默认 1]: 
if "%user_choice%"=="" set user_choice=1

if "%user_choice%"=="0" exit /b 0

REM 寻找 Python 解释器
set PYTHON_CMD=python
if exist "%ROOT_DIR%\.venv\Scripts\python.exe" set PYTHON_CMD="%ROOT_DIR%\.venv\Scripts\python.exe"
if exist "%ROOT_DIR%\venv\Scripts\python.exe" set PYTHON_CMD="%ROOT_DIR%\venv\Scripts\python.exe"

if "%user_choice%"=="1" (
    echo.
    echo 正在运行标杆场景评测 (local_cache)...
    %PYTHON_CMD% eval/run_eval.py --mode benchmark --case local_cache
    pause
    exit /b 0
)

if "%user_choice%"=="2" (
    echo.
    echo 正在运行弱势防守评测 (bear_defensive)...
    %PYTHON_CMD% eval/run_eval.py --mode benchmark --case bear_defensive
    pause
    exit /b 0
)

if "%user_choice%"=="3" (
    echo.
    echo 正在基于本地最新产物执行诊断评测 (offline)...
    %PYTHON_CMD% eval/run_eval.py --mode offline
    pause
    exit /b 0
)

if "%user_choice%"=="4" (
    echo.
    set /p topic_name=请输入选股主题 (留空为全市场): 
    echo 正在执行端到端选股工作流并全链路追踪诊断...
    %PYTHON_CMD% eval/run_eval.py --mode live --topic "%topic_name%"
    pause
    exit /b 0
)

if "%user_choice%"=="5" (
    echo.
    echo 正在启动 Web 工作台 (server.py + vite frontend)...
    call "%~dp0start.bat"
    exit /b 0
)

pause
