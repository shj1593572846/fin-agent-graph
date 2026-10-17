# 🚀 LangGraph 六节点多 Agent 股票量化与协同决策系统

本项目基于 **LangGraph** 框架构建了一套工业级 **A 股多智能体量化选股与协同决策系统**。系统通过日K线趋势初筛、实时分时 16 宫格监控、早盘量化形态确权（回踩不破分时均线、缩量承接）、多源消息面舆情排查，以及智能体横向协同通信与决策者终审研判，实现从全市场大数据筛选到最终操盘交易建议的全自动化闭环。

---

## 🏗️ 六节点工作流架构

```mermaid
flowchart TD
    START([开始]) --> Node1["Node 1: 下载日线数据<br/>(全市场/指定板块历史日K线初筛)"]
    Node1 --> Node2["Node 2: 过滤强势个股<br/>(筛选近10日涨停且多头排列标的)"]
    Node2 --> Node3["Node 3: 实时分时16宫格终端<br/>(多窗口加载实时分时K线与VWAP)"]
    Node3 --> Node4["Node 4: 16宫格分时量化 Agent<br/>(09:30-09:35 回踩不破均线与放量承接)"]
    Node3 --> Node5["Node 5: 消息面与舆情 Agent<br/>(行业催化剂、公司新闻与宏观情绪排查)"]
    Node4 <-->|"协同通信 / 交叉印证"| Node5
    Node4 --> Node6["Node 6: 决策者 Agent<br/>(综合技术面与消息面终审裁决)"]
    Node5 --> Node6
    Node6 --> END([输出终审投资研报 / 结束])
```

---

## ✨ 核心特性

1. **六节点智能体协同编排**：基于 LangGraph 状态图构建完整的股票量化筛选与决策流水线。
2. **实时 16 宫格监控看板**：集成高可用实时行情数据中心，支持多窗口（每页 16 只）秒级分时走势与均价线（VWAP）展示。
3. **早盘量化特征毫秒级运算**：核验 09:30 - 09:35 期间的回踩不破均线、缩量衰竭、快速收回与主动承接四大战法维度。
4. **Agent 协同对齐通信**：技术面 Agent 与消息面 Agent 在汇入决策者前进行跨节点横向通信与交叉印证。
5. **全栈 Web 交互工作台**：
   - **后端**：FastAPI 提供 WebSocket 流式无缓冲终端输出与进程生命周期管理。
   - **前端**：React + Vite 打造的赛博科技风大屏，支持节点拓扑点亮、日志过滤、看盘看板快速跳转。

---

## 📁 目录结构

```text
fin-agent-graph/
├── agent/                         # 智能体核心工作流包
│   ├── __init__.py                # 导出核心状态与调用接口
│   ├── main.py                    # 命令行研判流水线执行入口
│   ├── graph.py                   # LangGraph 六节点状态图编排
│   ├── agents.py                  # 各节点智能体实现与协同逻辑
│   ├── state.py                   # ResearchState 共享状态定义
│   ├── tools.py                   # 日K线抓取、指标过滤与搜索工具
│   ├── stock_chart.py             # 16 宫格实时分时看板服务与行情中心
│   └── stock_quant.py             # 早盘量化回踩承接分析引擎
├── server.py                      # FastAPI 后端服务 (提供 WebSocket 实时流)
├── frontend/                      # React + Vite 前端看板
│   ├── src/                       # 前端源码
│   └── package.json               # 前端依赖配置
├── start.bat                      # Windows 一键全栈启动脚本
├── requirements.txt               # Python 后端依赖库
├── .env.example                   # 环境变量模板
└── .gitignore                     # Git 忽略配置
```

---

## 🚀 快速开始

### 1. 安装依赖

#### Python 依赖
```bash
pip install -r requirements.txt
```

#### 前端依赖（若需运行 Web 前端）
```bash
cd frontend
npm install
cd ..
```

### 2. 配置环境变量（可选）

复制 `.env.example` 为 `.env`，填入你的大模型 API Key（兼容 OpenAI、DeepSeek、通义千问等标准接口）：

```bash
cp .env.example .env
```

> **提示**：未配置 API Key 时，程序会自动进入**本地极速演示模式**，可直接体验完整图拓扑流转与量化特征计算。

---

### 3. 运行方式

#### 方式一：一键启动全栈系统（推荐）
在项目根目录下双击运行 `start.bat`，系统将自动拉起：
1. **FastAPI 后端服务**：`http://127.0.0.1:8000`
2. **React 前端工作台**：`http://localhost:5173`

#### 方式二：纯命令行直接运行
```bash
# 极速分析全市场重点龙头标的
python agent/main.py --topic "全市场重点龙头"

# 分析指定题材或概念板块
python agent/main.py --topic "低空经济"

# 深度全量模式 (重新抓取全网最新行情并分析)
python agent/main.py --full --topic "半导体"

# 静默运行 (不弹出外部浏览器看盘窗口)
python agent/main.py --no-browser --keep-alive 0
```

#### 命令行参数说明

| 参数 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--topic` | `str` | `""` | 分析主题或板块（留空则收集全市场非科创板、非ST标的） |
| `--fast` | `flag` | `True` | 开启极速分析模式（优先复用本地缓存直驱计算，大幅提升速度） |
| `--full` | `flag` | `False` | 开启深度全量模式（重新全量抓取全网数据） |
| `--keep-alive` | `int` | `10` | 研报生成后保持 16 宫格看板运行的分钟数（`0` 表示生成后立即退出） |
| `--no-browser` | `flag` | `False` | 静默模式，不自动打开外部浏览器看盘窗口 |
