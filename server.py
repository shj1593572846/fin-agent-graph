"""
FastAPI 后端服务：桥接前端 React 与本地 main.py 执行
提供 WebSocket 实时无缓冲推流，精准输出节点分段信息及控制进程
"""

import os
import sys
import asyncio
import subprocess
import signal
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="LangGraph Stock Picker API Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

current_process: Optional[asyncio.subprocess.Process] = None
process_lock = asyncio.Lock()


class RunRequest(BaseModel):
    topic: str = ""
    keep_alive: int = 0


@app.get("/api/health")
async def health_check():
    is_running = current_process is not None and current_process.returncode is None
    return {
        "status": "ok",
        "running": is_running,
        "python_version": sys.version.split()[0],
        "workdir": os.getcwd()
    }


@app.post("/api/stop")
async def stop_execution():
    """强制中止当前正在运行的 main.py 进程树"""
    global current_process
    async with process_lock:
        if current_process and current_process.returncode is None:
            try:
                pid = current_process.pid
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True,
                        text=True,
                    )
                else:
                    current_process.send_signal(signal.SIGTERM)
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
            if current_process and current_process.returncode is None:
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

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=os.getcwd(),
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
            # 实时无缓冲读取输出流 (每次读取可用字节，即刻推送)
            while True:
                chunk_bytes = await proc.stdout.read(1024)
                if not chunk_bytes:
                    break
                chunk_text = chunk_bytes.decode("utf-8", errors="replace")
                await websocket.send_json({
                    "type": "stdout",
                    "content": chunk_text
                })

            return_code = await proc.wait()
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
        try:
            await websocket.send_json({
                "type": "error",
                "content": f"\n❌ 服务端异常: {str(e)}\n"
            })
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
