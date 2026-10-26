"""
FastAPI 后端服务：桥接前端 React 与本地 main.py 执行
提供 WebSocket 实时无缓冲推流，精准输出节点分段信息及控制进程
"""

import os
import sys
import asyncio
import subprocess
import signal
from typing import Optional, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 确保在 Windows 环境下优先启用 ProactorEventLoop，支持异步管道通信与子进程创建
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass


def proactor_loop_factory(*args, **kwargs):
    """供 uvicorn 自定义 loop 参数调用的工厂函数，确保在 Windows 上始终使用 ProactorEventLoop"""
    return asyncio.ProactorEventLoop()


app = FastAPI(title="LangGraph Stock Picker API Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

current_process: Optional[Any] = None
process_lock = asyncio.Lock()



class RunRequest(BaseModel):
    topic: str = ""
    keep_alive: int = 0


@app.on_event("startup")
async def startup_event():
    """服务启动时自动拉起常驻定时任务后台监听引擎与 RAG 知识库"""
    try:
        from agent.scheduler import scheduler_instance
        scheduler_instance.start()
        print("⏰ [FastAPI Startup] 定时任务常驻调度引擎已成功启动就绪！")
    except Exception as e:
        print(f"⚠️ [FastAPI Startup] 启动定时任务调度引擎失败: {e}")

    try:
        from rag import rag_service
        rag_service.init_samples_if_empty()
        print("📚 [FastAPI Startup] RAG 研报财报知识库已成功就绪！")
    except Exception as e:
        print(f"⚠️ [FastAPI Startup] 启动 RAG 知识库失败: {e}")


# 挂载 RAG 研报分析与财报解读知识库模块路由
from rag import rag_router
app.include_router(rag_router)


@app.get("/api/health")
async def health_check():
    is_running = current_process is not None and current_process.returncode is None
    return {
        "status": "ok",
        "running": is_running,
        "python_version": sys.version.split()[0],
        "workdir": os.getcwd()
    }


@app.get("/api/recommendations")
async def get_recommendations(limit: int = 20):
    """查询 MySQL stock_recommendation 表中的最新股票推荐入库记录"""
    try:
        try:
            from agent import db
        except Exception:
            import importlib
            db = importlib.import_module("agent.db")
        records = db.get_latest_recommendations(limit=limit)
        return {"success": True, "data": records, "count": len(records)}
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print(f"⚠️ [/api/recommendations] 查询异常: {e}\n{err_msg}")
        return {"success": False, "error": str(e), "data": [], "count": 0}


class RecommendationMonitorRequest(BaseModel):
    is_monitored: int = 1


@app.post("/api/recommendations/{rec_id}/monitor")
async def set_recommendation_monitor(rec_id: int, req: Optional[RecommendationMonitorRequest] = None):
    """更新某条股票推荐记录的【是否监控】状态"""
    try:
        try:
            from agent import db
        except Exception:
            import importlib
            db = importlib.import_module("agent.db")
        target_status = req.is_monitored if req is not None else 1
        success, msg = db.update_recommendation_monitor_status(rec_id, target_status)
        return {"success": success, "message": msg, "is_monitored": target_status}
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print(f"⚠️ [/api/recommendations/{rec_id}/monitor] 更新异常: {e}\n{err_msg}")
        return {"success": False, "error": str(e)}


# ==============================================================================
# 用户记忆持久化管理 RESTful API (配置：用户操盘人设、交易风格、战法笔记等)
# ==============================================================================
class UserMemoryUpdateRequest(BaseModel):
    user_role: Optional[str] = None
    persona_title: Optional[str] = None
    trading_style: Optional[str] = None
    memory_notes: Optional[list[str]] = None
    custom_preferences: Optional[dict] = None


@app.get("/api/user-memory")
async def get_user_memory():
    """获取持久化的用户记忆数据"""
    try:
        from agent.user_memory import load_user_memory
        mem = load_user_memory()
        return {"success": True, "data": mem}
    except Exception as e:
        return {"success": False, "error": str(e), "data": {}}


@app.post("/api/user-memory")
async def update_user_memory(req: UserMemoryUpdateRequest):
    """更新持久化用户记忆并写入 stock_data/user_memory.json"""
    try:
        from agent.user_memory import load_user_memory, save_user_memory
        current = load_user_memory()
        payload = {k: v for k, v in req.dict().items() if v is not None}
        current.update(payload)
        ok = save_user_memory(current)
        return {"success": ok, "data": current, "message": "用户记忆更新成功并持久化生效！" if ok else "更新失败"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==============================================================================
# 定时任务管理 RESTful API (配置：任务名称、运行的python文件、cron表达式)
# ==============================================================================
class TaskCreateRequest(BaseModel):
    name: str
    python_script: str = "agent/sync_close_price.py"
    cron_expr: str = "10 15 * * 1-5"
    enabled: bool = True


class TaskUpdateRequest(BaseModel):
    name: Optional[str] = None
    python_script: Optional[str] = None
    cron_expr: Optional[str] = None
    enabled: Optional[bool] = None


@app.get("/api/tasks")
async def get_tasks():
    """获取所有定时任务列表"""
    try:
        from agent.scheduler import scheduler_instance
        tasks = scheduler_instance.get_all_tasks()
        return {"success": True, "data": tasks, "count": len(tasks)}
    except Exception as e:
        return {"success": False, "error": str(e), "data": [], "count": 0}


@app.post("/api/tasks")
async def create_task(req: TaskCreateRequest):
    """新增定时任务 -> 写入存储并立刻动态注册生效"""
    try:
        from agent.scheduler import scheduler_instance
        task = scheduler_instance.add_task(req.dict())
        return {"success": True, "data": task, "message": f"定时任务【{task['name']}】已创建并立刻生效！"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.put("/api/tasks/{task_id}")
async def update_task(task_id: int, req: TaskUpdateRequest):
    """修改定时任务 -> 更新配置并立刻热重载生效"""
    try:
        from agent.scheduler import scheduler_instance
        data = {k: v for k, v in req.dict().items() if v is not None}
        task = scheduler_instance.update_task(task_id, data)
        if not task:
            return {"success": False, "message": f"任务 ID {task_id} 不存在"}
        return {"success": True, "data": task, "message": f"定时任务【{task['name']}】已更新并立刻生效！"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int):
    """删除定时任务 -> 从调度池卸载并立刻生效"""
    try:
        from agent.scheduler import scheduler_instance
        ok = scheduler_instance.delete_task(task_id)
        if not ok:
            return {"success": False, "message": f"任务 ID {task_id} 不存在"}
        return {"success": True, "message": "定时任务已成功删除并卸载生效！"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/tasks/{task_id}/toggle")
async def toggle_task(task_id: int):
    """启用/停用定时任务 -> 立刻生效"""
    try:
        from agent.scheduler import scheduler_instance
        task = scheduler_instance.toggle_task(task_id)
        if not task:
            return {"success": False, "message": f"任务 ID {task_id} 不存在"}
        status_text = "已启用" if task.get("enabled") else "已停用"
        return {"success": True, "data": task, "message": f"任务【{task['name']}】{status_text}并立刻生效！"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/tasks/{task_id}/run")
async def run_task_now(task_id: int):
    """立即手动触发执行指定定时任务脚本"""
    try:
        from agent.scheduler import scheduler_instance
        res = scheduler_instance.execute_task_now(task_id)
        return res
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/tasks/sync-close-prices")
async def trigger_sync_close_prices(target_date: Optional[str] = None):
    """一键手动触发当日/指定日期的 A 股收盘价同步脚本"""
    try:
        from agent.sync_close_price import run_sync
        ok = run_sync(target_date or "")
        return {"success": ok, "message": "A股收盘价同步执行完成" if ok else "收盘价同步执行异常"}
    except Exception as e:
        return {"success": False, "error": str(e)}


class MonitorBreakPriceRequest(BaseModel):
    force: bool = False
    ignore_date: bool = False


@app.post("/api/tasks/monitor-break-prices")
async def trigger_monitor_break_prices(req: Optional[MonitorBreakPriceRequest] = None):
    """一键手动触发 A 股次日量化跌破分时均线卖出监控研判"""
    try:
        from agent.monitor_break_price import run_monitor_scan
        force = req.force if req else False
        ignore_date = req.ignore_date if req else False
        res = run_monitor_scan(force_run=force, ignore_date_check=ignore_date)
        return res
    except Exception as e:
        return {"success": False, "error": str(e), "message": f"次日量化监控执行异常: {str(e)}"}


@app.get("/api/monitor/candidates")
async def get_monitor_candidates():
    """查询当前处于【需要次日量化监控】(is_monitored=1 且 当天 > 买入日期) 的持仓标的列表"""
    try:
        from agent.db import get_candidates_for_break_monitor
        candidates = get_candidates_for_break_monitor()
        return {"success": True, "data": candidates, "count": len(candidates)}
    except Exception as e:
        return {"success": False, "error": str(e), "data": [], "count": 0}



@app.post("/api/stop")
async def stop_execution():
    """强制中止当前正在运行的 main.py 进程树"""
    global current_process
    async with process_lock:
        if current_process:
            ret = getattr(current_process, "returncode", None)
            if ret is None:
                try:
                    pid = current_process.pid
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(pid)],
                            capture_output=True,
                            text=True,
                        )
                    else:
                        current_process.terminate()
                    return {"success": True, "message": f"进程 PID {pid} 已中止"}
                except Exception as e:
                    return {"success": False, "message": f"中止失败: {str(e)}"}
                finally:
                    current_process = None
        return {"success": False, "message": "当前没有正在运行的任务"}


@app.websocket("/ws/run")
async def websocket_run(websocket: WebSocket):
    """
    WebSocket 实时双工通信：
    1. 接收客户端参数
    2. 无缓冲读取 stdout 并立即推送到前端
    3. 支持客户端随时发送 {"action": "stop"} 中止
    """
    global current_process
    await websocket.accept()

    try:
        init_data = await websocket.receive_json()
        topic = str(init_data.get("topic", "")).strip()
        keep_alive = int(init_data.get("keep_alive", 0))
        fast_mode = bool(init_data.get("fast_mode", True))

        async with process_lock:
            if current_process and getattr(current_process, "returncode", None) is None:
                await websocket.send_json({
                    "type": "error",
                    "content": "⚠️ 系统当前已有选股任务在运行中，请等待其完成或点击终止后再启动！\n"
                })
                await websocket.close()
                return

            agent_script = os.path.join("agent", "main.py")
            cmd = [
                sys.executable,
                "-u",  # 开启无缓冲流式输出
                agent_script,
                "--topic",
                topic,
                "--keep-alive",
                str(keep_alive),
                "--no-browser",
            ]
            if fast_mode:
                cmd.append("--fast")
            else:
                cmd.append("--full")

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["FAST_MODE"] = "1" if fast_mode else "0"
            env["NO_BROWSER"] = "1"

            await websocket.send_json({
                "type": "start",
                "command": " ".join(cmd),
                "topic": topic,
                "keep_alive": keep_alive,
                "fast_mode": fast_mode,
                "content": f"⚡ 正在拉起六节点 LangGraph 协同工作流 {'[🚀 极速模式]' if fast_mode else '[🔄 深度全网模式]'}: {' '.join(cmd)}\n\n"
            })

            use_async_proc = True
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=env,
                    cwd=os.getcwd(),
                )
                current_process = proc
            except NotImplementedError:
                # 兼容 Windows SelectorEventLoop 无法创建异步子进程的场景
                use_async_proc = False
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=os.getcwd(),
                    bufsize=0,
                )
                current_process = proc

        # 后台任务监听客户端中止指令
        async def client_listener():
            try:
                while True:
                    msg = await websocket.receive_json()
                    if msg.get("action") == "stop":
                        await stop_execution()
                        break
            except Exception:
                pass

        listener_task = asyncio.create_task(client_listener())

        try:
            loop = asyncio.get_running_loop()
            # 实时无缓冲读取输出流 (每次读取可用字节，即刻推送)
            while True:
                if use_async_proc:
                    chunk_bytes = await proc.stdout.read(1024)
                else:
                    chunk_bytes = await loop.run_in_executor(None, proc.stdout.read, 1024)

                if not chunk_bytes:
                    break
                chunk_text = chunk_bytes.decode("utf-8", errors="replace")
                await websocket.send_json({
                    "type": "stdout",
                    "content": chunk_text
                })

            if use_async_proc:
                return_code = await proc.wait()
            else:
                return_code = await loop.run_in_executor(None, proc.wait)

            await websocket.send_json({
                "type": "finish",
                "exit_code": return_code,
                "content": f"\n\n✨ 选股工作流执行完毕 (进程退出码: {return_code})\n"
            })
        finally:
            listener_task.cancel()
            async with process_lock:
                if current_process == proc:
                    current_process = None

    except WebSocketDisconnect:
        pass
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print(f"❌ WebSocket 运行异常:\n{err_msg}")
        try:
            err_detail = f"{type(e).__name__}: {str(e)}" if str(e) else type(e).__name__
            await websocket.send_json({
                "type": "error",
                "content": f"\n❌ 服务端异常: {err_detail}\n"
            })
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    # 在 Windows 下若开启 reload，uvicorn 默认会切换为 SelectorEventLoop 并监控目录，导致频繁重启与子进程受限；
    # 此处默认以稳态运行 (reload=False)，并优先注入 ProactorEventLoop 工厂保证流式管道高稳定输出
    uvicorn_kwargs = {
        "app": "server:app",
        "host": "0.0.0.0",
        "port": 8000,
        "reload": False,
    }
    if sys.platform == "win32":
        uvicorn_kwargs["loop"] = "server:proactor_loop_factory"
    uvicorn.run(**uvicorn_kwargs)

