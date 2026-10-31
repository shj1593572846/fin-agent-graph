# 🚀 fin-agent-graph 运行与启动中心 (Run & Launch Center)

本目录按**操作系统与部署环境**（Windows 开发环境 / Linux 生产与容器环境）对所有服务拉起、评测与定时调度脚本进行了模块化分类隔离。

---

## 📁 目录架构总览

```text
run/
├── windows/                     # 🪟 Windows 本地开发与评测环境
│   ├── start.bat                # 一键拉起 FastAPI 后端 (8000) 与 Vite 前端 (5173)
│   ├── start_eval.bat           # 选股多 Agent 全生命周期评测交互控制台
│   └── schedule_task.bat        # 注册每日 01:30 定时选股计划任务至 Windows Task Scheduler
│
├── linux/                       # 🐧 Linux 开发、生产与 Docker 容器环境
│   ├── start.sh                 # 本地开发全栈启动脚本 (后台拉起后端 + 启动前端)
│   ├── start_eval.sh            # Linux 终端交互式评测控制台
│   ├── docker_start.sh          # 生产环境一键构建并拉起 Docker 集群 (MySQL + App + Caddy)
│   ├── docker_logs.sh           # 实时跟随查看应用容器流式日志
│   └── docker_restart.sh        # 热重载/重启应用容器
│
└── README.md                    # 本说明文档
```

---

## 🪟 1. Windows 环境使用指南 (`run/windows/`)

适用于 Windows 本地工作站快速开发、调试与评测：

| 脚本文件 | 说明 | 推荐运行方式 |
| :--- | :--- | :--- |
| [`start.bat`](windows/start.bat) | 在独立终端窗口启动 FastAPI 后端，并在当前窗口拉起 React 前端开发服务器 | 直接双击运行，或在终端输入 `run\windows\start.bat` |
| [`start_eval.bat`](windows/start_eval.bat) | 交互式选股评测控制台（支持高动能牛市、弱势防守、现场数据及端到端评测） | 直接双击运行，或在终端输入 `run\windows\start_eval.bat` |
| [`schedule_task.bat`](windows/schedule_task.bat) | 将 Node 1（数据采集）与 Node 2（选股初筛）注册为每日凌晨 01:30 自动执行的系统计划任务 | 右键以管理员身份运行 |

---

## 🐧 2. Linux / 容器生产环境使用指南 (`run/linux/`)

适用于 Linux 生产服务器（如阿里云 ECS `<生产服务器IP>`）或本地 Linux/macOS 开发：

### 2.1 本地/裸机启动
```bash
# 启动本地服务 (后端 8000 + 前端 5173)
bash run/linux/start.sh

# 交互式选股评测
bash run/linux/start_eval.sh
```

### 2.2 生产容器运维 (Docker Compose)
```bash
# 一键构建并启动集群 (MySQL 8.0 + App + Caddy TLS)
bash run/linux/docker_start.sh

# 查看实时智能体流式日志
bash run/linux/docker_logs.sh

# 热重启应用容器
bash run/linux/docker_restart.sh
```
