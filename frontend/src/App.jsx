import React, { useState, useEffect, useRef, useMemo } from 'react'
import './App.css'

const PRESET_TOPICS = [
  { label: '🌟 全市场重点龙头', value: '' },
  { label: '📱 消费电子', value: '消费电子' },
  { label: '⚡ 新能源 储能', value: '新能源 储能' },
  { label: '🚁 低空经济', value: '低空经济' },
  { label: '🤖 人工智能', value: '人工智能' },
  { label: '💾 半导体芯片', value: '半导体' },
  { label: '🏦 银行高股息', value: '银行' },
]

const PIPELINE_NODES = [
  { id: 1, name: 'Node 1: 日线初筛', shortName: 'Node 1 数据初筛', icon: '📥', desc: '问财/AkShare全量K线抓取' },
  { id: 2, name: 'Node 2: 过滤龙头', shortName: 'Node 2 龙头过滤', icon: '🎯', desc: '量比/涨幅/成交额严筛' },
  { id: 3, name: 'Node 3: 16宫格构建', shortName: 'Node 3 16宫格大屏', icon: '🖥️', desc: '分钟分时动态看板生成' },
  { id: 4, name: 'Node 4: 技术量化', shortName: 'Node 4 技术量化', icon: '📈', desc: '分时均线承接战法 Agent' },
  { id: 5, name: 'Node 5: 消息面排查', shortName: 'Node 5 消息面分析', icon: '📰', desc: '题材催化/A股快讯 Agent' },
  { id: 6, name: 'Node 6: 终审决策', shortName: 'Node 6 终审决策研报', icon: '👑', desc: '首席操盘投资决策 Agent' },
]

export default function App() {
  const [topic, setTopic] = useState('')
  const [keepAlive, setKeepAlive] = useState('0')
  const [fastMode, setFastMode] = useState(true)
  const [status, setStatus] = useState('idle') // 'idle' | 'running' | 'completed' | 'stopped' | 'error'
  
  // 日志列表：每项包含独立行号、所属节点ID、节点名称、换行文本等
  const [logs, setLogs] = useState([])
  
  // 当前控制台过滤标签：0 表示“全部实时流”，1~6 表示只看特定节点
  const [selectedNodeTab, setSelectedNodeTab] = useState(0)
  
  const [filterText, setFilterText] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [serverOnline, setServerOnline] = useState(false)
  const [dashboardUrl, setDashboardUrl] = useState('')
  const [activeNode, setActiveNode] = useState(0)
  const [elapsedTime, setElapsedTime] = useState(0)
  const [toast, setToast] = useState('')

  const socketRef = useRef(null)
  const terminalRef = useRef(null)
  const timerRef = useRef(null)
  
  // 流式缓冲器与序号计数器
  const streamBufferRef = useRef('')
  const lineCounterRef = useRef(0)
  const currentNodeRef = useRef(0)
  // 用于记录当前运行中已展示过划分横幅的节点，保证每个节点只出现一次横幅
  const seenNodeStartsRef = useRef(new Set())

  // 显示吐司提示
  const showToast = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }

  // 定期检测后端健康状态
  useEffect(() => {
    const checkServer = async () => {
      try {
        const res = await fetch('/api/health')
        if (res.ok) {
          const data = await res.json()
          setServerOnline(true)
          if (data.running && status === 'idle') {
            setStatus('running')
          }
        } else {
          setServerOnline(false)
        }
      } catch (e) {
        setServerOnline(false)
      }
    }

    checkServer()
    const interval = setInterval(checkServer, 3000)
    return () => clearInterval(interval)
  }, [status])

  // 运行计时器
  useEffect(() => {
    if (status === 'running') {
      const start = Date.now() - elapsedTime * 1000
      timerRef.current = setInterval(() => {
        setElapsedTime(Math.floor((Date.now() - start) / 1000))
      }, 1000)
    } else {
      clearInterval(timerRef.current)
    }
    return () => clearInterval(timerRef.current)
  }, [status])

  // 自动滚屏
  useEffect(() => {
    if (autoScroll && terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight
    }
  }, [logs, autoScroll, selectedNodeTab])

  // 根据单行文本判断其归属的 LangGraph 节点
  const detectNodeFromLine = (line, currentNode) => {
    // 阶段汇总与节点显式路由 (优先匹配对应阶段)
    if (
      line.includes('【阶段汇总 6') ||
      line.includes('阶段汇总 6') ||
      line.includes('[node6:') ||
      line.includes('👑 [node6') ||
      line.includes('终审投资操盘研报') ||
      line.includes('终审交易决策研报') ||
      line.includes('终审决策报告') ||
      line.includes('最终决策矩阵')
    ) {
      return 6
    }

    if (
      line.includes('【阶段汇总 5') ||
      line.includes('阶段汇总 5') ||
      line.includes('[node5:') ||
      line.includes('📰 [node5') ||
      line.includes('A股 7×24 快讯') ||
      line.includes('财经核心头条')
    ) {
      return 5
    }

    if (
      line.includes('【阶段汇总 4') ||
      line.includes('阶段汇总 4') ||
      line.includes('[node4:') ||
      line.includes('📈 [node4') ||
      line.includes('09:30 - 09:35 早盘分时战法') ||
      line.includes('fetch_grid_timeline_data')
    ) {
      return 4
    }

    if (
      line.includes('【阶段汇总 3') ||
      line.includes('阶段汇总 3') ||
      line.includes('[node3:') ||
      line.includes('🖥️ [node3') ||
      line.includes('分时图16宫格')
    ) {
      return 3
    }

    if (
      line.includes('[node2:') ||
      line.includes('🎯 [node2')
    ) {
      return 2
    }

    if (
      line.includes('【阶段汇总 1') ||
      line.includes('阶段汇总 1') ||
      line.includes('[node1:') ||
      line.includes('📥 [node1') ||
      line.includes('启动 LangGraph 六节点')
    ) {
      return 1
    }

    return currentNode
  }

  // 流式块处理函数：正确处理换行符、保留空行、划分节点
  const processStreamChunk = (chunkText) => {
    if (!chunkText) return

    // 1. 标准化换行：将所有 \r\n 统一替换为标准 \n
    const normalized = chunkText.replace(/\r\n/g, '\n')
    streamBufferRef.current += normalized

    // 2. 按照 \n 拆分成行
    const rawSegments = streamBufferRef.current.split('\n')
    // 弹出最后一个未遇到换行符的末尾片段保留到下一次拼接
    streamBufferRef.current = rawSegments.pop() ?? ''

    if (rawSegments.length === 0) return

    const newEntries = []

    for (let rawLine of rawSegments) {
      // 3. 处理独立 \r (倒计时原地覆盖刷新，如 \r⏳ 倒计时: 09分59秒)
      let line = rawLine
      if (line.includes('\r')) {
        const rParts = line.split('\r').filter(Boolean)
        line = rParts.length > 0 ? rParts[rParts.length - 1] : ''
      }

      // 4. 判定节点变迁
      const detectedNode = detectNodeFromLine(line, currentNodeRef.current)

      // 关键防重复逻辑：每个节点的专属划分横幅在全流程中严格只出现一次！
      let isNewNode = false
      if (detectedNode > 0 && !seenNodeStartsRef.current.has(detectedNode)) {
        seenNodeStartsRef.current.add(detectedNode)
        isNewNode = true
      }

      if (detectedNode !== currentNodeRef.current && detectedNode > 0) {
        currentNodeRef.current = detectedNode
        setActiveNode(detectedNode)
      }

      // 5. 提取 16 宫格看板地址
      const urlMatch = line.match(/https?:\/\/(?:127\.0\.0\.1|localhost):\d{2,5}(?:\/[^\s'"\])]*)?/)
      if (urlMatch && !dashboardUrl) {
        setDashboardUrl(urlMatch[0])
      }

      lineCounterRef.current += 1
      newEntries.push({
        id: lineCounterRef.current,
        nodeId: currentNodeRef.current,
        nodeName: PIPELINE_NODES.find((n) => n.id === currentNodeRef.current)?.name || '系统启动',
        text: line,
        isNewNodeStart: isNewNode,
        timestamp: new Date().toLocaleTimeString('zh-CN'),
      })
    }

    setLogs((prev) => [...prev, ...newEntries])
  }

  // 启动选股分析
  const handleStart = () => {
    if (status === 'running') return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/run`

    // 初始化状态
    setLogs([])
    streamBufferRef.current = ''
    lineCounterRef.current = 0
    currentNodeRef.current = 0
    seenNodeStartsRef.current.clear() // 重置节点划分横幅记录，保证每次新运行各出现一次
    setStatus('running')
    setElapsedTime(0)
    setActiveNode(1)
    setSelectedNodeTab(0) // 默认切回全景流
    setDashboardUrl('')

    const ws = new WebSocket(wsUrl)
    socketRef.current = ws

    ws.onopen = () => {
      ws.send(JSON.stringify({
        topic: topic.trim(),
        keep_alive: parseInt(keepAlive, 10) || 0,
        fast_mode: fastMode,
      }))
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'stdout' || msg.type === 'start' || msg.type === 'finish' || msg.type === 'error') {
          if (msg.content) {
            processStreamChunk(msg.content)
          }
        }

        if (msg.type === 'finish') {
          // 刷新剩余未闭合的内容
          if (streamBufferRef.current) {
            let line = streamBufferRef.current.replace(/\r\n/g, '\n')
            if (line.includes('\r')) {
              const rParts = line.split('\r').filter(Boolean)
              line = rParts.length > 0 ? rParts[rParts.length - 1] : ''
            }
            if (line) {
              lineCounterRef.current += 1
              setLogs((prev) => [
                ...prev,
                {
                  id: lineCounterRef.current,
                  nodeId: currentNodeRef.current,
                  nodeName: PIPELINE_NODES.find((n) => n.id === currentNodeRef.current)?.name || '结束',
                  text: line,
                  isNewNodeStart: false,
                  timestamp: new Date().toLocaleTimeString('zh-CN'),
                }
              ])
            }
            streamBufferRef.current = ''
          }
          setStatus(msg.exit_code === 0 ? 'completed' : 'stopped')
          showToast(msg.exit_code === 0 ? '🎉 选股研判全流程执行完毕！' : `⚠️ 进程退出 (代码: ${msg.exit_code})`)
        } else if (msg.type === 'error') {
          setStatus('error')
          showToast(`❌ 服务端异常: ${msg.content}`)
        }
      } catch (err) {
        console.error('WebSocket parse error:', err)
      }
    }

    ws.onerror = () => {
      setLogs((prev) => [
        ...prev,
        {
          id: ++lineCounterRef.current,
          nodeId: 0,
          nodeName: '系统错误',
          text: `❌ [${new Date().toLocaleTimeString()}] 无法连接到后端 WebSocket。请确保已在终端启动后端: python server.py`,
          isNewNodeStart: false,
          timestamp: new Date().toLocaleTimeString('zh-CN'),
        }
      ])
      setStatus('error')
    }

    ws.onclose = () => {
      setStatus((current) => (current === 'running' ? 'stopped' : current))
    }
  }

  // 终止执行
  const handleStop = async () => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ action: 'stop' }))
    }
    try {
      await fetch('/api/stop', { method: 'POST' })
    } catch (e) {
      console.warn('Stop call error:', e)
    }
    setStatus('stopped')
    showToast('🛑 正在强制终止进程树...')
  }

  // 清空日志
  const handleClearLogs = () => {
    setLogs([])
    streamBufferRef.current = ''
    lineCounterRef.current = 0
    seenNodeStartsRef.current.clear()
    showToast('🧹 控制台已清屏')
  }

  // 复制当前视图日志
  const handleCopyLogs = () => {
    const textToCopy = displayLogs.map((l) => l.text).join('\n')
    navigator.clipboard.writeText(textToCopy)
    showToast('📋 已复制当前视图内容到剪贴板')
  }

  // 导出全部日志
  const handleDownloadLogs = () => {
    const fullText = logs.map((l) => `[${l.timestamp}] [${l.nodeName}] ${l.text}`).join('\n')
    const blob = new Blob([fullText], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `stock_screener_${new Date().toISOString().slice(0, 10)}.log`
    a.click()
    URL.revokeObjectURL(url)
    showToast('💾 完整运行日志已下载')
  }

  // 计时格式化
  const formatTimer = (seconds) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }

  // 各节点的日志行数统计
  const nodeCounts = useMemo(() => {
    const counts = { 0: logs.length, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0 }
    logs.forEach((log) => {
      if (log.nodeId >= 1 && log.nodeId <= 6) {
        counts[log.nodeId] = (counts[log.nodeId] || 0) + 1
      }
    })
    return counts
  }, [logs])

  // 过滤后的显示日志列表
  const displayLogs = useMemo(() => {
    let result = logs

    // 1. 按选中节点过滤
    if (selectedNodeTab > 0) {
      result = result.filter((item) => item.nodeId === selectedNodeTab)
    }

    // 2. 按搜索词过滤
    if (filterText.trim()) {
      const q = filterText.toLowerCase()
      result = result.filter((item) => item.text.toLowerCase().includes(q))
    }

    return result
  }, [logs, selectedNodeTab, filterText])

  // 日志样式判断
  const getLineClassName = (text) => {
    if (!text) return 'log-line-item'
    if (text.includes('阶段汇总 6') || text.includes('👑 【阶段汇总 6') || text.includes('最终决策矩阵')) return 'log-line-item decision-header'
    if (text.includes('阶段汇总') || text.includes('🚀 启动 LangGraph') || text.includes('Node4: 筛选符合条件')) return 'log-line-item stage-header'
    if (text.includes('|') && text.includes('---')) return 'log-line-item table-row'
    if (text.includes('❌') || text.includes('Error') || text.includes('error') || text.includes('失败')) return 'log-line-item error-line'
    if (text.includes('✅') || text.includes('🎉') || text.includes('成果') || text.includes('强力符合')) return 'log-line-item success-line'
    return 'log-line-item'
  }

  // 渲染行内容中的超链接与格式
  const renderLogLineContent = (text) => {
    const urlRegex = /(https?:\/\/[^\s'"]+)/g
    const parts = text.split(urlRegex)

    return parts.map((part, index) => {
      if (part.match(urlRegex)) {
        return (
          <a
            key={index}
            href={part}
            target="_blank"
            rel="noopener noreferrer"
            className="terminal-link"
          >
            {part} ↗
          </a>
        )
      }
      return part
    })
  }

  // 当前选中的节点信息对象
  const currentSelectedNodeInfo = PIPELINE_NODES.find((n) => n.id === selectedNodeTab)

  return (
    <div className="app-container">
      {/* 顶部系统导航 */}
      <header className="app-header">
        <div className="brand-section">
          <div className="brand-logo-badge">📈</div>
          <div className="brand-title-wrap">
            <h1>
              AI 量化选股工作台
              <span className="brand-version">LangGraph v1.2</span>
            </h1>
            <p className="brand-subtitle">六节点多 Agent 协同研判决策系统 (Node 1-6 独立分段流式输出)</p>
          </div>
        </div>

        <div className="header-status-group">
          <div className={`status-chip ${serverOnline ? 'online' : 'offline'}`}>
            <span className="status-dot"></span>
            <span>{serverOnline ? 'FastAPI 后端已连接 (8000)' : '后端未就绪 (请运行 python server.py)'}</span>
          </div>
          <div className="status-chip time-chip">
            <span>📅 {new Date().toLocaleDateString('zh-CN')}</span>
          </div>
        </div>
      </header>

      {/* 六节点拓扑流水线卡片 (点击可快速切换至该节点日志) */}
      <section className="pipeline-card">
        <div className="pipeline-header">
          <div className="pipeline-title">
            <span>⚡ 多 Agent 协同研判流水线阶段 (点击可单独查看该节点输出)</span>
          </div>
          <div className="pipeline-status-text">
            {activeNode === 0 && <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>等待启动指令</span>}
            {activeNode > 0 && (
              <span style={{ color: 'var(--accent-cyan)', fontSize: '0.8rem', fontWeight: 600 }}>
                ● 正在执行: {PIPELINE_NODES[activeNode - 1]?.name}
              </span>
            )}
          </div>
        </div>

        <div className="pipeline-steps">
          {PIPELINE_NODES.map((node) => {
            const isDone = activeNode > node.id || status === 'completed'
            const isActive = activeNode === node.id && status === 'running'
            const isTabActive = selectedNodeTab === node.id
            return (
              <div
                key={node.id}
                className={`pipeline-step ${isActive ? 'active' : ''} ${isDone ? 'done' : ''} ${isTabActive ? 'tab-selected' : ''}`}
                onClick={() => setSelectedNodeTab(node.id)}
                title={`点击查看 ${node.name} 的独立输出`}
              >
                <span className="step-num">{isDone ? '✓ COMPLETED' : `PHASE 0${node.id}`}</span>
                <span className="step-name">{node.name.replace(`Node ${node.id}: `, '')}</span>
                <span className="step-desc">{node.desc}</span>
              </div>
            )
          })}
        </div>
      </section>

      {/* 选股启动控制面板 */}
      <section className="control-panel">
        <div className="control-main-row">
          <div className="topic-input-wrapper">
            <label htmlFor="topic-input">🎯 目标选股板块 / 题材主题 (留空则全市场初筛):</label>
            <div className="topic-input-container">
              <span className="topic-icon">🔍</span>
              <input
                id="topic-input"
                type="text"
                className="topic-input"
                placeholder="例如: 消费电子 / 新能源 储能 / 银行 / 低空经济 (回车启动)"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleStart()}
                disabled={status === 'running'}
              />
            </div>
          </div>

          <div className="keepalive-wrapper">
            <label htmlFor="keepalive-select">⏱️ 16宫格看盘保持:</label>
            <select
              id="keepalive-select"
              className="keepalive-select"
              value={keepAlive}
              onChange={(e) => setKeepAlive(e.target.value)}
              disabled={status === 'running'}
            >
              <option value="0">0 分钟 (生成后立即退出)</option>
              <option value="5">5 分钟 (轻度保持看盘)</option>
              <option value="10">10 分钟 (标准看盘监控)</option>
              <option value="30">30 分钟 (长时盘中监控)</option>
            </select>
          </div>

          <div className="mode-toggle-container">
            <label>⚡ 运行速度模式:</label>
            <div className="mode-pill-group">
              <button
                type="button"
                className={`mode-pill-btn ${fastMode ? 'active' : ''}`}
                onClick={() => setFastMode(true)}
                disabled={status === 'running'}
                title="复用本地日线缓存、直接精简调用LLM，全流程~15-25秒"
              >
                🚀 极速模式 (~20s)
              </button>
              <button
                type="button"
                className={`mode-pill-btn ${!fastMode ? 'active' : ''}`}
                onClick={() => setFastMode(false)}
                disabled={status === 'running'}
                title="重新全网抓取全A日线K线数据、全量多轮ReAct推理"
              >
                🔄 深度全量模式
              </button>
            </div>
          </div>

          <div className="action-buttons-group">
            <button
              id="launch-main-btn"
              className={`btn-primary-launch ${status === 'running' ? 'running' : ''}`}
              onClick={handleStart}
              disabled={status === 'running'}
            >
              {status === 'running' ? (
                <>
                  <span className="btn-icon-spin">⚙️</span>
                  <span>选股研判运行中...</span>
                </>
              ) : (
                <>
                  <span>🚀</span>
                  <span>一键启动选股决策 (运行 agent/main.py)</span>
                </>
              )}
            </button>

            <button
              id="stop-main-btn"
              className="btn-stop"
              onClick={handleStop}
              disabled={status !== 'running'}
              title="强制终止当前正在运行的选股进程"
            >
              <span>🛑</span>
              <span>终止</span>
            </button>
          </div>
        </div>

        {/* 快捷板块标签 */}
        <div className="preset-chips-row">
          <span className="preset-label">快捷板块推荐:</span>
          {PRESET_TOPICS.map((preset) => (
            <button
              key={preset.label}
              className={`preset-chip ${topic === preset.value ? 'active' : ''}`}
              onClick={() => setTopic(preset.value)}
              disabled={status === 'running'}
            >
              {preset.label}
            </button>
          ))}
        </div>
      </section>

      {/* 16 宫格实时看板就绪卡片提示 */}
      {dashboardUrl && (
        <div className="dashboard-alert-banner">
          <div className="dashboard-banner-left">
            <span className="dashboard-banner-icon">🖥️</span>
            <div className="dashboard-banner-text">
              <h4>分时 16 宫格实时监控看板大屏已就绪！</h4>
              <p>可直接在独立大屏窗口中查看多标的分时异动及量化均线回踩承接</p>
            </div>
          </div>
          <a
            href={dashboardUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-open-grid"
          >
            <span>👉 立即打开 16 宫格大屏 ({dashboardUrl})</span>
          </a>
        </div>
      )}

      {/* 运行时控制台窗口 (Core Window: 节点区分展示与准确换行) */}
      <section className={`terminal-window-wrapper ${isFullscreen ? 'fullscreen' : ''}`}>
        {/* 控制台顶部装饰与工具栏 */}
        <div className="terminal-title-bar">
          <div className="window-dots-group">
            <span className="win-dot red"></span>
            <span className="win-dot yellow"></span>
            <span className="win-dot green"></span>
          </div>

          <div className="terminal-title">
            <span>💻</span>
            <span>agent/main.py 控制台终端 | 节点分段实时流</span>
            <span className="terminal-tag">UTF-8 / Unbuffered</span>
          </div>

          <div className="terminal-actions-group">
            <input
              type="text"
              placeholder="🔍 过滤日志..."
              className="terminal-filter-input"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
            />
            <button
              className={`term-action-btn ${autoScroll ? 'active' : ''}`}
              onClick={() => setAutoScroll(!autoScroll)}
              title="切换自动滚动至底部"
            >
              <span>⬇️ 自动滚屏: {autoScroll ? '开' : '关'}</span>
            </button>
            <button
              className="term-action-btn"
              onClick={handleCopyLogs}
              title="复制当前视图内容"
            >
              <span>📋 复制</span>
            </button>
            <button
              className="term-action-btn"
              onClick={handleDownloadLogs}
              title="导出全部运行日志"
            >
              <span>💾 导出</span>
            </button>
            <button
              className="term-action-btn"
              onClick={handleClearLogs}
              title="清空当前控制台"
            >
              <span>🧹 清屏</span>
            </button>
            <button
              className="term-action-btn"
              onClick={() => setIsFullscreen(!isFullscreen)}
              title="切换全屏视图"
            >
              <span>{isFullscreen ? '✕ 退出全屏' : '⛶ 全屏'}</span>
            </button>
          </div>
        </div>

        {/* 节点分段切换选项卡 (Node Tabs Bar) */}
        <div className="node-tabs-bar">
          <button
            className={`node-tab-btn ${selectedNodeTab === 0 ? 'active' : ''}`}
            onClick={() => setSelectedNodeTab(0)}
          >
            <span>🌐 全部实时流</span>
            <span className="tab-badge-count">{nodeCounts[0]} 行</span>
          </button>

          {PIPELINE_NODES.map((node) => {
            const count = nodeCounts[node.id] || 0
            const isCurrentlyRunning = activeNode === node.id && status === 'running'
            return (
              <button
                key={node.id}
                className={`node-tab-btn ${selectedNodeTab === node.id ? 'active' : ''}`}
                onClick={() => setSelectedNodeTab(node.id)}
              >
                <span>{node.icon}</span>
                <span>{node.shortName}</span>
                <span className="tab-badge-count">{count} 行</span>
                {isCurrentlyRunning && <span className="tab-pulse-dot" title="节点运行中"></span>}
              </button>
            )
          })}
        </div>

        {/* 选中单节点时的专属信息横幅 */}
        {selectedNodeTab > 0 && currentSelectedNodeInfo && (
          <div className={`node-context-banner node-${selectedNodeTab}`}>
            <div className="node-context-left">
              <span>{currentSelectedNodeInfo.icon}</span>
              <span className="node-context-title">正在查看：{currentSelectedNodeInfo.name}</span>
              <span className="node-context-desc">({currentSelectedNodeInfo.desc})</span>
            </div>
            <button
              className="term-action-btn"
              onClick={() => setSelectedNodeTab(0)}
              style={{ fontSize: '0.74rem' }}
            >
              <span>↩ 返回全景流式视图</span>
            </button>
          </div>
        )}

        {/* 控制台内容主体 (保留空行、自然换行、高亮分块) */}
        <div className="terminal-screen" ref={terminalRef}>
          {displayLogs.length === 0 ? (
            <div className="terminal-placeholder">
              <div className="placeholder-icon">📊</div>
              <div className="placeholder-title">
                {selectedNodeTab === 0
                  ? '控制台就绪，等待执行启动'
                  : `${currentSelectedNodeInfo?.name} 暂无输出数据`}
              </div>
              <p className="placeholder-desc">
                {selectedNodeTab === 0
                  ? '点击上方 “一键启动选股决策 (运行 agent/main.py)” 按钮，系统将按 Node 1~6 节点自动划分并实时输出控制台内容。'
                  : '该节点尚未执行或无匹配输出，请点击“返回全景流式视图”或启动选股工作流。'}
              </p>
              {selectedNodeTab === 0 && (
                <div className="placeholder-command-box">
                  $ python -u agent/main.py {topic ? `--topic "${topic}"` : ''} --keep-alive {keepAlive}
                </div>
              )}
            </div>
          ) : (
            displayLogs.map((item) => (
              <React.Fragment key={item.id}>
                {/* 在全景流模式下，当检测到新节点开始时，渲染明显的节点划分卡片 */}
                {selectedNodeTab === 0 && item.isNewNodeStart && item.nodeId > 0 && (
                  <div className={`node-section-divider node-${item.nodeId}`}>
                    <div className="node-divider-badge">
                      <span className="node-divider-tag">PHASE 0{item.nodeId}</span>
                      <span>
                        {PIPELINE_NODES.find((n) => n.id === item.nodeId)?.icon}{' '}
                        {PIPELINE_NODES.find((n) => n.id === item.nodeId)?.name}
                      </span>
                    </div>
                    <div className="node-divider-time">阶段开始时间: {item.timestamp}</div>
                  </div>
                )}

                {/* 保证每行正确展示，遇到空行时保留标准垂直高度 */}
                <div className={getLineClassName(item.text)}>
                  <span className="log-ln">{(item.id).toString().padStart(4, '0')}</span>
                  <span className="log-content">
                    {item.text === '' ? (
                      <span className="log-empty-line">&nbsp;</span>
                    ) : (
                      renderLogLineContent(item.text)
                    )}
                  </span>
                </div>
              </React.Fragment>
            ))
          )}
        </div>

        {/* 控制台底部状态栏 */}
        <div className="terminal-footer-bar">
          <div className="terminal-footer-left">
            <span className={`status-badge ${status}`}>
              {status === 'idle' && 'STATUS: READY (就绪)'}
              {status === 'running' && 'STATUS: STREAMING (正在输出)'}
              {status === 'completed' && 'STATUS: SUCCESS (全部研报生成完毕)'}
              {status === 'stopped' && 'STATUS: STOPPED (已中止)'}
              {status === 'error' && 'STATUS: ERROR (执行异常)'}
            </span>
            <span>
              当前视图: {selectedNodeTab === 0 ? '全景流' : `Node ${selectedNodeTab}`} | 共 {displayLogs.length} 行
            </span>
          </div>

          <div className="terminal-footer-right">
            <span>⏱️ 耗时: {formatTimer(elapsedTime)}</span>
            <span>PID: {status === 'running' ? 'Active' : 'None'}</span>
          </div>
        </div>
      </section>

      {/* 吐司提示 */}
      {toast && (
        <div className="toast-notice">
          <span>🔔</span>
          <span>{toast}</span>
        </div>
      )}
    </div>
  )
}
