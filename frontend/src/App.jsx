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
  const [recommendations, setRecommendations] = useState([])
  const [showRecModal, setShowRecModal] = useState(false)

  // 定时任务调度管理状态
  const [tasks, setTasks] = useState([])
  const [showTaskModal, setShowTaskModal] = useState(false)
  const [showEditTaskModal, setShowEditTaskModal] = useState(false)
  const [editingTask, setEditingTask] = useState(null)
  const [taskRunningId, setTaskRunningId] = useState(null)
  const [taskFormData, setTaskFormData] = useState({
    name: 'A股收盘价自动同步',
    python_script: 'agent/sync_close_price.py',
    cron_expr: '10 15 * * 1-5',
    enabled: true,
  })

  const socketRef = useRef(null)
  const terminalRef = useRef(null)
  const timerRef = useRef(null)
  
  // 流式缓冲器与序号计数器
  const streamBufferRef = useRef('')
  const lineCounterRef = useRef(0)
  const currentNodeRef = useRef(0)
  // 用于记录当前运行中已展示过划分横幅的节点，保证每个节点只出现一次横幅
  const seenNodeStartsRef = useRef(new Set())

  // 通用后端 API 地址计算
  const getApiUrl = (endpoint) => {
    if (window.location.port === '5173') {
      const hostname = window.location.hostname === 'localhost' ? '127.0.0.1' : (window.location.hostname || '127.0.0.1')
      return `http://${hostname}:8000${endpoint}`
    }
    return endpoint
  }

  // 拉取 MySQL stock_recommendation 最新记录
  const fetchRecommendations = async () => {
    try {
      const res = await fetch(getApiUrl('/api/recommendations?limit=20'))
      if (res.ok) {
        const json = await res.json()
        if (json.success && Array.isArray(json.data)) {
          setRecommendations(json.data)
        }
      }
    } catch (e) {
      console.warn('Failed to fetch recommendations:', e)
    }
  }

  // 拉取定时任务列表
  const fetchTasks = async () => {
    try {
      const res = await fetch(getApiUrl('/api/tasks'))
      if (res.ok) {
        const json = await res.json()
        if (json.success && Array.isArray(json.data)) {
          setTasks(json.data)
        }
      }
    } catch (e) {
      console.warn('Failed to fetch tasks:', e)
    }
  }

  const handleOpenCreateTask = () => {
    setEditingTask(null)
    setTaskFormData({
      name: 'A股收盘价自动同步',
      python_script: 'agent/sync_close_price.py',
      cron_expr: '10 15 * * 1-5',
      enabled: true,
    })
    setShowEditTaskModal(true)
  }

  const handleOpenEditTask = (task) => {
    setEditingTask(task)
    setTaskFormData({
      name: task.name || '',
      python_script: task.python_script || 'agent/sync_close_price.py',
      cron_expr: task.cron_expr || '10 15 * * 1-5',
      enabled: task.enabled !== false,
    })
    setShowEditTaskModal(true)
  }

  const handleSaveTask = async (e) => {
    if (e) e.preventDefault()
    if (!taskFormData.name.trim()) {
      showToast('⚠️ 请填写任务名称')
      return
    }
    if (!taskFormData.python_script.trim()) {
      showToast('⚠️ 请填写运行的 Python 文件路径')
      return
    }
    if (!taskFormData.cron_expr.trim()) {
      showToast('⚠️ 请填写 Cron 表达式')
      return
    }
    try {
      let url = getApiUrl('/api/tasks')
      let method = 'POST'
      if (editingTask && editingTask.id) {
        url = getApiUrl(`/api/tasks/${editingTask.id}`)
        method = 'PUT'
      }
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: taskFormData.name.trim(),
          python_script: taskFormData.python_script.trim(),
          cron_expr: taskFormData.cron_expr.trim(),
          enabled: taskFormData.enabled,
        }),
      })
      const json = await res.json()
      if (json.success) {
        showToast(`🎉 ${json.message || '定时任务保存成功并立刻热生效！'}`)
        setShowEditTaskModal(false)
        fetchTasks()
      } else {
        showToast(`❌ 保存失败: ${json.error || json.message}`)
      }
    } catch (err) {
      showToast(`❌ 网络请求异常: ${err.message}`)
    }
  }

  const handleDeleteTask = async (taskId, taskName) => {
    if (!window.confirm(`确认删除定时任务【${taskName}】吗？删除后立刻卸载生效。`)) {
      return
    }
    try {
      const res = await fetch(getApiUrl(`/api/tasks/${taskId}`), { method: 'DELETE' })
      const json = await res.json()
      if (json.success) {
        showToast(`🗑️ 任务【${taskName}】已删除并立刻卸载生效`)
        fetchTasks()
      } else {
        showToast(`❌ 删除失败: ${json.message}`)
      }
    } catch (err) {
      showToast(`❌ 删除异常: ${err.message}`)
    }
  }

  const handleToggleTask = async (taskId) => {
    try {
      const res = await fetch(getApiUrl(`/api/tasks/${taskId}/toggle`), { method: 'POST' })
      const json = await res.json()
      if (json.success) {
        showToast(json.message)
        fetchTasks()
      }
    } catch (err) {
      showToast(`❌ 状态切换失败: ${err.message}`)
    }
  }

  const handleRunTaskNow = async (task) => {
    setTaskRunningId(task.id)
    showToast(`⚡ 正在立即触发执行任务【${task.name}】...`)
    try {
      const res = await fetch(getApiUrl(`/api/tasks/${task.id}/run`), { method: 'POST' })
      const json = await res.json()
      if (json.success) {
        showToast(`✅ 任务【${task.name}】执行完毕: ${json.message || '操作成功'}`)
        fetchTasks()
        fetchRecommendations()
      } else {
        showToast(`⚠️ 任务执行提示: ${json.error || json.message}`)
      }
    } catch (err) {
      showToast(`❌ 执行触发异常: ${err.message}`)
    } finally {
      setTaskRunningId(null)
    }
  }

  const handleDirectSyncClosePrices = async () => {
    showToast('🔍 正在拉取今日收盘价更新 stock_recommendation...')
    try {
      const res = await fetch(getApiUrl('/api/tasks/sync-close-prices'), { method: 'POST' })
      const json = await res.json()
      if (json.success) {
        showToast(`✅ ${json.message}`)
        fetchRecommendations()
        fetchTasks()
      } else {
        showToast(`⚠️ ${json.message || json.error}`)
      }
    } catch (err) {
      showToast(`❌ 同步收盘价异常: ${err.message}`)
    }
  }

  // 显示吐司提示
  const showToast = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }

  // 定期检测后端健康状态及定时任务
  useEffect(() => {
    const checkServer = async () => {
      try {
        const res = await fetch(getApiUrl('/api/health'))
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
    fetchRecommendations()
    fetchTasks()
    const interval = setInterval(() => {
      checkServer()
      fetchTasks()
    }, 5000)
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
    // 如果在 Vite 开发服务器 (如 5173 端口)，优先直连后端端口 8000 保证稳定流式推送
    let wsUrl = `${protocol}//${window.location.host}/ws/run`
    if (window.location.port === '5173') {
      const hostname = window.location.hostname === 'localhost' ? '127.0.0.1' : (window.location.hostname || '127.0.0.1')
      wsUrl = `${protocol}//${hostname}:8000/ws/run`
    }

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
          if (msg.exit_code === 0) {
            fetchRecommendations()
          }
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
    if (text.includes('数据库入库成功') || text.includes('stock_recommendation') || text.includes('数据库排重')) return 'log-line-item db-line'
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
          <button
            type="button"
            className="btn-header-task"
            onClick={() => {
              setShowTaskModal(true)
              fetchTasks()
            }}
            title="打开定时任务调度中心 (支持增删改查、热更新即刻生效)"
          >
            <span>⏰ 定时任务调度</span>
            <span className="task-count-chip">
              {tasks.filter((t) => t.enabled).length} 活跃
            </span>
          </button>
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

      {/* 数据库荐股入库记录展示卡片 (stock_recommendation) */}
      {recommendations.length > 0 && (
        <div className="recommendation-alert-banner">
          <div className="recommendation-banner-left">
            <span className="recommendation-banner-icon">🏆</span>
            <div className="recommendation-banner-text">
              <div className="recommendation-banner-title">
                <h4>策略第一名已入库 <code>stock_recommendation</code> 表</h4>
                <span className="rec-badge-tag">自动排重生效 (股票代码+买入日期唯一)</span>
              </div>
              <div className="recommendation-meta-row">
                <span className="rec-chip code">股票代码: <strong>{recommendations[0].stock_code}</strong></span>
                <span className="rec-chip name">股票名称: <strong>{recommendations[0].stock_name}</strong></span>
                <span className="rec-chip price">买入价格: <strong>¥{Number(recommendations[0].buy_price || 0).toFixed(2)}</strong></span>
                <span className="rec-chip date">买入日期: <strong>{recommendations[0].buy_date}</strong></span>
                <span className="rec-chip time">创建时间: <strong>{recommendations[0].created_at}</strong></span>
              </div>
            </div>
          </div>
          <div className="rec-banner-actions">
            <button
              type="button"
              className="btn-sync-close-direct"
              onClick={handleDirectSyncClosePrices}
              title="立即查询今日推荐标的并拉取行情回写收盘价"
            >
              <span>⚡ 立即同步收盘价</span>
            </button>
            <button
              type="button"
              className="btn-view-recs"
              onClick={() => setShowRecModal(true)}
              title="查看 stock_recommendation 历史记录"
            >
              <span>📋 查看荐股记录 ({recommendations.length} 条)</span>
            </button>
            <button
              type="button"
              className="btn-open-task-modal"
              onClick={() => {
                setShowTaskModal(true)
                fetchTasks()
              }}
              title="定时任务调度管理中心"
            >
              <span>⏰ 定时任务 ({tasks.length})</span>
            </button>
          </div>
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

      {/* 荐股记录弹窗 (stock_recommendation) */}
      {showRecModal && (
        <div className="rec-modal-overlay" onClick={() => setShowRecModal(false)}>
          <div className="rec-modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="rec-modal-header">
              <div className="rec-modal-title">
                <span>📊</span>
                <h3>MySQL `stock_recommendation` 荐股入库记录</h3>
                <span className="rec-modal-count">共 {recommendations.length} 条</span>
              </div>
              <button className="rec-modal-close" onClick={() => setShowRecModal(false)}>✕</button>
            </div>
            <div className="rec-modal-body">
              <table className="rec-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>股票代码</th>
                    <th>股票名称</th>
                    <th>买入价格</th>
                    <th>买入日期</th>
                    <th>创建时间</th>
                  </tr>
                </thead>
                <tbody>
                  {recommendations.map((rec) => (
                    <tr key={rec.id}>
                      <td>#{rec.id}</td>
                      <td><span className="rec-code-badge">{rec.stock_code}</span></td>
                      <td><strong>{rec.stock_name}</strong></td>
                      <td className="rec-price-cell">¥{Number(rec.buy_price || 0).toFixed(2)}</td>
                      <td>{rec.buy_date}</td>
                      <td className="rec-time-cell">{rec.created_at}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="rec-modal-footer">
              <span className="rec-footer-tip">💡 数据表规则：仅当 (股票代码 + 买入日期) 不重复时自动插入</span>
              <button className="btn-modal-done" onClick={() => setShowRecModal(false)}>关闭</button>
            </div>
          </div>
        </div>
      )}

      {/* ⏰ 定时任务调度管理中心主弹窗 (sys_cron_task) */}
      {showTaskModal && (
        <div className="task-modal-overlay" onClick={() => setShowTaskModal(false)}>
          <div className="task-modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="task-modal-header">
              <div className="task-modal-title">
                <span className="task-title-icon">⏰</span>
                <div>
                  <h3>系统定时任务调度管理中心</h3>
                  <p className="task-modal-sub">
                    支持对 A 股定时任务动态增删改查，修改后立刻热生效，无需重启服务
                  </p>
                </div>
              </div>
              <div className="task-header-right-actions">
                <button
                  type="button"
                  className="btn-create-task"
                  onClick={handleOpenCreateTask}
                  title="新建定时任务"
                >
                  <span>➕ 新增定时任务</span>
                </button>
                <button
                  type="button"
                  className="btn-sync-now-head"
                  onClick={handleDirectSyncClosePrices}
                  title="一键拉取今日推荐标的并回写收盘价"
                >
                  <span>⚡ 立即同步收盘价</span>
                </button>
                <button
                  type="button"
                  className="btn-refresh-tasks"
                  onClick={fetchTasks}
                  title="刷新任务列表"
                >
                  <span>🔄 刷新</span>
                </button>
                <button
                  className="rec-modal-close"
                  onClick={() => setShowTaskModal(false)}
                >
                  ✕
                </button>
              </div>
            </div>

            <div className="task-modal-body">
              {tasks.length === 0 ? (
                <div className="task-empty-state">
                  <div className="task-empty-icon">📭</div>
                  <div className="task-empty-title">暂无定时任务</div>
                  <p>点击上方“➕ 新增定时任务”即可创建自动任务，保存后立刻生效。</p>
                  <button
                    type="button"
                    className="btn-create-task"
                    onClick={handleOpenCreateTask}
                  >
                    ➕ 立即创建任务
                  </button>
                </div>
              ) : (
                <div className="task-cards-list">
                  {tasks.map((t) => (
                    <div
                      key={t.id}
                      className={`task-item-card ${t.enabled ? 'is-enabled' : 'is-disabled'}`}
                    >
                      <div className="task-card-main">
                        <div className="task-card-header">
                          <div className="task-card-title-wrap">
                            <span className="task-id-badge">#{t.id}</span>
                            <h4 className="task-card-name">{t.name}</h4>
                            <span
                              className="task-script-badge"
                              title={`运行脚本文件: ${t.python_script || 'agent/sync_close_price.py'}`}
                            >
                              🐍 {t.python_script || 'agent/sync_close_price.py'}
                            </span>
                          </div>

                          <div className="task-switch-container">
                            <label
                              className="task-toggle-switch"
                              title={t.enabled ? '点击停用' : '点击启用'}
                            >
                              <input
                                type="checkbox"
                                checked={t.enabled}
                                onChange={() => handleToggleTask(t.id)}
                              />
                              <span className="task-slider"></span>
                            </label>
                            <span
                              className={`task-switch-label ${
                                t.enabled ? 'enabled' : 'disabled'
                              }`}
                            >
                              {t.enabled ? '运行中' : '已暂停'}
                            </span>
                          </div>
                        </div>

                        <div className="task-meta-grid">
                          <div className="task-meta-item">
                            <span className="meta-label">⏰ cron表达式:</span>
                            <span className="meta-val cron-val">{t.cron_expr}</span>
                          </div>

                          <div className="task-meta-item">
                            <span className="meta-label">⏳ 下次触发:</span>
                            <span className="meta-val next-val">
                              {t.enabled
                                ? t.next_run_time || '计算中...'
                                : '— (任务已暂停)'}
                            </span>
                          </div>

                          <div className="task-meta-item">
                            <span className="meta-label">⏱️ 上次运行:</span>
                            <span className="meta-val last-val">
                              {t.last_run_time ? (
                                <>
                                  <span>{t.last_run_time}</span>
                                  <span
                                    className={`task-status-pill ${
                                      t.last_status === 'success'
                                        ? 'status-success'
                                        : t.last_status === 'running'
                                        ? 'status-running'
                                        : 'status-error'
                                    }`}
                                  >
                                    {t.last_status === 'success' && '✓ 成功'}
                                    {t.last_status === 'running' && '● 运行中'}
                                    {t.last_status === 'error' && '✕ 异常'}
                                    {t.last_status === 'idle' && '就绪'}
                                  </span>
                                </>
                              ) : (
                                '尚未触发'
                              )}
                            </span>
                          </div>
                        </div>

                        {t.last_result && (
                          <div className="task-result-box">
                            <span className="result-icon">📋</span>
                            <span className="result-text">{t.last_result}</span>
                          </div>
                        )}
                      </div>

                      <div className="task-card-actions">
                        <button
                          type="button"
                          className="btn-task-action run-now"
                          disabled={taskRunningId === t.id}
                          onClick={() => handleRunTaskNow(t)}
                          title="立即手动触发执行一次"
                        >
                          {taskRunningId === t.id ? '⚡ 执行中...' : '⚡ 立即执行'}
                        </button>
                        <button
                          type="button"
                          className="btn-task-action edit-task"
                          onClick={() => handleOpenEditTask(t)}
                          title="修改配置 (保存后立刻热重载)"
                        >
                          ✏️ 编辑
                        </button>
                        <button
                          type="button"
                          className="btn-task-action delete-task"
                          onClick={() => handleDeleteTask(t.id, t.name)}
                          title="删除此定时任务"
                        >
                          🗑️ 删除
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="task-modal-footer">
              <div className="task-footer-tip">
                <span className="tip-pulse">●</span>
                <span>
                  💡 <strong>热重载机制保障</strong>：后台常驻调度守护进程运行中，新增、修改、暂停或删除任务<strong>立即生效，无需重启服务</strong>。
                </span>
              </div>
              <button
                type="button"
                className="btn-modal-done"
                onClick={() => setShowTaskModal(false)}
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ✏️ 定时任务 新增 / 编辑 弹窗 */}
      {showEditTaskModal && (
        <div
          className="task-edit-overlay"
          onClick={() => setShowEditTaskModal(false)}
        >
          <div
            className="task-edit-dialog"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="task-edit-header">
              <div className="task-edit-title">
                <span>{editingTask ? '✏️' : '➕'}</span>
                <h3>{editingTask ? '编辑定时任务' : '新增定时任务'}</h3>
              </div>
              <button
                className="rec-modal-close"
                onClick={() => setShowEditTaskModal(false)}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSaveTask}>
              <div className="task-edit-body">
                <div className="form-group">
                  <label className="form-label">
                    1. 任务名称 <span className="req">*</span>:
                  </label>
                  <input
                    type="text"
                    className="form-control"
                    placeholder="例如: A股收盘价自动同步"
                    value={taskFormData.name}
                    onChange={(e) =>
                      setTaskFormData({ ...taskFormData, name: e.target.value })
                    }
                    required
                  />
                  <span className="form-hint">为定时任务命名，便于识别与日志回溯</span>
                </div>

                <div className="form-group">
                  <label className="form-label">
                    2. 运行的python文件 <span className="req">*</span>:
                  </label>
                  <div className="script-presets-group">
                    <button
                      type="button"
                      className={`script-preset-btn ${
                        taskFormData.python_script === 'agent/sync_close_price.py' ? 'active' : ''
                      }`}
                      onClick={() =>
                        setTaskFormData({
                          ...taskFormData,
                          python_script: 'agent/sync_close_price.py',
                          name:
                            !taskFormData.name || taskFormData.name === '早盘全市场智能选股'
                              ? 'A股收盘价自动同步'
                              : taskFormData.name,
                          cron_expr:
                            !taskFormData.cron_expr || taskFormData.cron_expr === '30 9 * * 1-5'
                              ? '10 15 * * 1-5'
                              : taskFormData.cron_expr,
                        })
                      }
                    >
                      📊 agent/sync_close_price.py (A股收盘价同步)
                    </button>
                    <button
                      type="button"
                      className={`script-preset-btn ${
                        taskFormData.python_script === 'agent/main.py' ? 'active' : ''
                      }`}
                      onClick={() =>
                        setTaskFormData({
                          ...taskFormData,
                          python_script: 'agent/main.py',
                          name:
                            !taskFormData.name || taskFormData.name === 'A股收盘价自动同步'
                              ? '早盘全市场智能选股'
                              : taskFormData.name,
                          cron_expr:
                            !taskFormData.cron_expr || taskFormData.cron_expr === '10 15 * * 1-5'
                              ? '30 9 * * 1-5'
                              : taskFormData.cron_expr,
                        })
                      }
                    >
                      🚀 agent/main.py (选股流水线)
                    </button>
                  </div>
                  <input
                    type="text"
                    className="form-control"
                    style={{ fontFamily: "'Fira Code', Consolas, Monaco, monospace" }}
                    placeholder="例如: agent/sync_close_price.py 或 agent/main.py"
                    value={taskFormData.python_script}
                    onChange={(e) =>
                      setTaskFormData({
                        ...taskFormData,
                        python_script: e.target.value,
                      })
                    }
                    required
                  />
                  <span className="form-hint">
                    指定待执行的 Python 脚本相对路径，触发时将自动在后台异步调用 <code>python -u &lt;文件路径&gt;</code> 执行
                  </span>
                </div>

                <div className="form-group">
                  <label className="form-label">
                    3. cron表达式 <span className="req">*</span>:
                  </label>
                  <div className="cron-presets-group">
                    <button
                      type="button"
                      className={`cron-preset-btn ${
                        taskFormData.cron_expr === '10 15 * * 1-5' ? 'active' : ''
                      }`}
                      onClick={() =>
                        setTaskFormData({ ...taskFormData, cron_expr: '10 15 * * 1-5' })
                      }
                    >
                      10 15 * * 1-5 (开盘日 15:10)
                    </button>
                    <button
                      type="button"
                      className={`cron-preset-btn ${
                        taskFormData.cron_expr === '30 9 * * 1-5' ? 'active' : ''
                      }`}
                      onClick={() =>
                        setTaskFormData({ ...taskFormData, cron_expr: '30 9 * * 1-5' })
                      }
                    >
                      30 9 * * 1-5 (开盘日 09:30)
                    </button>
                    <button
                      type="button"
                      className={`cron-preset-btn ${
                        taskFormData.cron_expr === '0 10 15 * * ?' ? 'active' : ''
                      }`}
                      onClick={() =>
                        setTaskFormData({ ...taskFormData, cron_expr: '0 10 15 * * ?' })
                      }
                    >
                      0 10 15 * * ? (Quartz 6段)
                    </button>
                    <button
                      type="button"
                      className={`cron-preset-btn ${
                        taskFormData.cron_expr === '15:10' ? 'active' : ''
                      }`}
                      onClick={() =>
                        setTaskFormData({ ...taskFormData, cron_expr: '15:10' })
                      }
                    >
                      15:10 (简写)
                    </button>
                    <button
                      type="button"
                      className={`cron-preset-btn ${
                        taskFormData.cron_expr === '09:30' ? 'active' : ''
                      }`}
                      onClick={() =>
                        setTaskFormData({ ...taskFormData, cron_expr: '09:30' })
                      }
                    >
                      09:30 (简写)
                    </button>
                  </div>
                  <input
                    type="text"
                    className="form-control"
                    style={{ fontFamily: "'Fira Code', Consolas, Monaco, monospace" }}
                    placeholder="输入 Cron 表达式如 10 15 * * 1-5 或 0 53 22 * * ? 或 15:10"
                    value={taskFormData.cron_expr}
                    onChange={(e) =>
                      setTaskFormData({
                        ...taskFormData,
                        cron_expr: e.target.value,
                      })
                    }
                    required
                  />
                  <span className="form-hint">
                    全面支持标准 5 段 Linux Cron (<code>分 时 日 月 周</code>)、6 段 Spring/Quartz 格式 (<code>秒 分 时 日 月 周</code>，如 <code>0 53 22 * * ?</code>) 及 <code>15:10</code> 时间简写
                  </span>
                </div>

                <div className="form-group-checkboxes">
                  <label className="checkbox-item">
                    <input
                      type="checkbox"
                      checked={taskFormData.enabled}
                      onChange={(e) =>
                        setTaskFormData({
                          ...taskFormData,
                          enabled: e.target.checked,
                        })
                      }
                    />
                    <span>
                      ⚡ <strong>立即启用该定时任务</strong> (保存后立刻计入后台调度引擎热重载监听)
                    </span>
                  </label>
                </div>

                <div className="form-instant-notice">
                  <span className="notice-icon">⚡</span>
                  <div className="notice-text">
                    <strong>即刻热生效机制保障</strong>：表单提交后后台调度引擎立即重新计算触发周期与下次执行时间，<strong>无需重启服务或任何额外操作</strong>！
                  </div>
                </div>
              </div>

              <div className="task-edit-footer">
                <button
                  type="button"
                  className="btn-cancel"
                  onClick={() => setShowEditTaskModal(false)}
                >
                  取消
                </button>
                <button type="submit" className="btn-save-task">
                  💾 保存并立即生效
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {toast && (
        <div className="toast-notice">
          <span>🔔</span>
          <span>{toast}</span>
        </div>
      )}
    </div>
  )
}
