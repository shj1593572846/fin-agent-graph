import React, { useState, useEffect, useRef } from 'react'

// 格式化简单 Markdown 为结构化 HTML 节点
function FormattedMarkdown({ content }) {
  if (!content) return null

  const lines = content.split('\n')
  const elements = []
  let tableRows = []
  let inTable = false
  let inCodeBlock = false
  let codeBuffer = []

  const flushTable = (key) => {
    if (tableRows.length === 0) return null
    const headerRow = tableRows[0]
    const bodyRows = tableRows.slice(1).filter((r) => !r.every((c) => /^[-:| ]+$/.test(c)))

    const tableEl = (
      <div key={`table-${key}`} className="rag-md-table-wrap">
        <table className="rag-md-table">
          <thead>
            <tr>
              {headerRow.map((col, idx) => (
                <th key={idx}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bodyRows.map((row, rIdx) => (
              <tr key={rIdx}>
                {row.map((cell, cIdx) => (
                  <td key={cIdx}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
    tableRows = []
    inTable = false
    return tableEl
  }

  const flushCode = (key) => {
    if (codeBuffer.length === 0) return null
    const codeEl = (
      <pre key={`code-${key}`} className="rag-md-code-block">
        <code>{codeBuffer.join('\n')}</code>
      </pre>
    )
    codeBuffer = []
    inCodeBlock = false
    return codeEl
  }

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i]
    const trimmed = rawLine.trim()

    // 代码块判定
    if (trimmed.startsWith('```')) {
      if (inCodeBlock) {
        elements.push(flushCode(i))
      } else {
        if (inTable) elements.push(flushTable(i))
        inCodeBlock = true
      }
      continue
    }

    if (inCodeBlock) {
      codeBuffer.push(rawLine)
      continue
    }

    // 表格判定
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      inTable = true
      const cells = trimmed
        .slice(1, -1)
        .split('|')
        .map((c) => c.trim())
      tableRows.push(cells)
      continue
    } else if (inTable) {
      elements.push(flushTable(i))
    }

    // 空行
    if (!trimmed) {
      elements.push(<div key={`empty-${i}`} className="rag-md-spacer" />)
      continue
    }

    // 标题判定
    if (trimmed.startsWith('# ')) {
      elements.push(<h2 key={i} className="rag-md-h1">{renderInlineText(trimmed.slice(2))}</h2>)
      continue
    }
    if (trimmed.startsWith('## ')) {
      elements.push(<h3 key={i} className="rag-md-h2">{renderInlineText(trimmed.slice(3))}</h3>)
      continue
    }
    if (trimmed.startsWith('### ')) {
      elements.push(<h4 key={i} className="rag-md-h3">{renderInlineText(trimmed.slice(4))}</h4>)
      continue
    }

    // 分割线
    if (/^[-*_]{3,}$/.test(trimmed)) {
      elements.push(<hr key={i} className="rag-md-hr" />)
      continue
    }

    // 列表判定
    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      elements.push(
        <li key={i} className="rag-md-list-item">
          <span className="bullet">●</span>
          <span>{renderInlineText(trimmed.slice(2))}</span>
        </li>
      )
      continue
    }

    // 编号列表
    const numMatch = trimmed.match(/^(\d+)\.\s+(.*)$/)
    if (numMatch) {
      elements.push(
        <div key={i} className="rag-md-num-item">
          <span className="num-badge">{numMatch[1]}</span>
          <span>{renderInlineText(numMatch[2])}</span>
        </div>
      )
      continue
    }

    // 普通段落
    elements.push(
      <p key={i} className="rag-md-p">
        {renderInlineText(rawLine)}
      </p>
    )
  }

  if (inTable) elements.push(flushTable(lines.length))
  if (inCodeBlock) elements.push(flushCode(lines.length))

  return <div className="rag-markdown-body">{elements}</div>
}

// 格式化行内加粗和高亮
function renderInlineText(text) {
  if (!text) return ''
  const parts = []
  const regex = /(\*\*.*?\*\*|`.*?`)/g
  let lastIndex = 0
  let match

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.substring(lastIndex, match.index))
    }
    const token = match[0]
    if (token.startsWith('**') && token.endsWith('**')) {
      parts.push(
        <strong key={match.index} className="rag-inline-bold">
          {token.slice(2, -2)}
        </strong>
      )
    } else if (token.startsWith('`') && token.endsWith('`')) {
      parts.push(
        <code key={match.index} className="rag-inline-code">
          {token.slice(1, -1)}
        </code>
      )
    }
    lastIndex = regex.lastIndex
  }

  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex))
  }

  return parts
}

export default function RagKnowledgeView({ getApiUrl, showToast, onDocCountChange }) {
  // 知识库数据状态
  const [docs, setDocs] = useState([])
  const [stats, setStats] = useState({
    total_docs: 0,
    research_docs: 0,
    financial_docs: 0,
    total_chunks: 0,
    stocks_count: 0,
    stocks_covered: [],
  })
  const [loadingDocs, setLoadingDocs] = useState(false)
  const [activeTab, setActiveTab] = useState('qa') // 'qa' | 'docs'

  // 文档筛选
  const [filterCategory, setFilterCategory] = useState('全部')
  const [searchQuery, setSearchQuery] = useState('')

  // 问答状态
  const [question, setQuestion] = useState('')
  const [qaCategory, setQaCategory] = useState('全部')
  const [qaStockCode, setQaStockCode] = useState('')
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState(null)
  const [sources, setSources] = useState([])
  const [showSources, setShowSources] = useState(true)

  // 手动上传本地文件模态框状态
  const [showUploadModal, setShowUploadModal] = useState(false)
  const [uploadFile, setUploadFile] = useState(null)
  const [uploadCategory, setUploadCategory] = useState('研报分析')
  const [uploadTitle, setUploadTitle] = useState('')
  const [uploadStockCode, setUploadStockCode] = useState('')
  const [uploadStockName, setUploadStockName] = useState('')
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef(null)

  // 机构研报自动抓取/导入模态框状态
  const [showFetchModal, setShowFetchModal] = useState(false)
  const [fetchTab, setFetchTab] = useState('batch') // 'batch' | 'preview'
  const [fetchSymbol, setFetchSymbol] = useState('')
  const [fetchCount, setFetchCount] = useState(5)
  const [fetchCategory, setFetchCategory] = useState('自动')
  const [fetchRating, setFetchRating] = useState('*')
  const [fetchKeyword, setFetchKeyword] = useState('')
  const [fetching, setFetching] = useState(false)
  const [previewReports, setPreviewReports] = useState([])
  const [previewReportsLoading, setPreviewReportsLoading] = useState(false)
  const [selectedInfoCodes, setSelectedInfoCodes] = useState(new Set())

  // 切片预览模态框
  const [previewDoc, setPreviewDoc] = useState(null)
  const [previewChunks, setPreviewChunks] = useState([])
  const [previewLoading, setPreviewLoading] = useState(false)

  // 快捷问题推荐
  const PRESET_QUESTIONS = [
    { text: '贵州茅台一季度营业收入与归母净利润增速是多少？渠道表现如何？', label: '📈 茅台一季度盈利与渠道', cat: '财报解读' },
    { text: '宁德时代券商研报的核心投资逻辑、目标价及全球市占率是多少？', label: '⚡ 宁德时代研报评级与壁垒', cat: '研报分析' },
    { text: '比亚迪汽车业务毛利率是多少？第五代DM混动系统有哪些技术突破？', label: '🚗 比亚迪毛利与DM技术', cat: '全部' },
    { text: '总结近期机构研报对宝丰能源煤制烯烃产能投放与盈利预期的核心观点。', label: '🏭 宝丰能源机构深度研判', cat: '研报分析' },
  ]

  // 拉取知识库统计
  const fetchStats = async () => {
    try {
      const res = await fetch(getApiUrl('/api/rag/stats'))
      if (res.ok) {
        const json = await res.json()
        if (json.success && json.data) {
          setStats(json.data)
          if (onDocCountChange) {
            onDocCountChange(json.data.total_docs)
          }
        }
      }
    } catch (e) {
      console.warn('Failed to fetch RAG stats:', e)
    }
  }

  // 拉取文档列表
  const fetchDocs = async () => {
    setLoadingDocs(true)
    try {
      let url = getApiUrl('/api/rag/documents?')
      const params = new URLSearchParams()
      if (filterCategory !== '全部') params.append('category', filterCategory)
      if (searchQuery.trim()) params.append('search', searchQuery.trim())
      url += params.toString()

      const res = await fetch(url)
      if (res.ok) {
        const json = await res.json()
        if (json.success && Array.isArray(json.data)) {
          setDocs(json.data)
        }
      }
    } catch (e) {
      console.warn('Failed to fetch RAG documents:', e)
    } finally {
      setLoadingDocs(false)
    }
  }

  useEffect(() => {
    fetchStats()
    fetchDocs()
  }, [filterCategory])

  // 提交 RAG 问答
  const handleQuery = async (customQ = null) => {
    const q = (customQ || question || '').trim()
    if (!q) {
      showToast('⚠️ 请输入你想咨询的研报核心逻辑或财报指标')
      return
    }

    setAsking(true)
    showToast('🔍 正在检索知识库分块并由大模型分析中...')
    try {
      const res = await fetch(getApiUrl('/api/rag/query'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: q,
          category: qaCategory !== '全部' ? qaCategory : null,
          stock_code: qaStockCode ? qaStockCode.trim() : null,
          top_k: 4,
          generate_answer: true,
        }),
      })
      const json = await res.json()
      if (json.success && json.data) {
        setAnswer(json.data.answer || '未生成有效分析内容')
        setSources(json.data.sources || [])
        setShowSources(true)
        showToast('✨ 投研研报与财报问答分析已完成')
      } else {
        showToast(`❌ 问答请求异常: ${json.error || '未知错误'}`)
      }
    } catch (err) {
      showToast(`❌ 网络请求失败: ${err.message}`)
    } finally {
      setAsking(false)
    }
  }

  // 点击快捷问题
  const handleSelectPreset = (p) => {
    setQuestion(p.text)
    if (p.cat) setQaCategory(p.cat)
    handleQuery(p.text)
  }

  // 复制解答
  const handleCopyAnswer = () => {
    if (!answer) return
    navigator.clipboard.writeText(answer).then(() => {
      showToast('📋 已复制解答内容到剪贴板！')
    })
  }

  // 打开上传弹窗
  const handleOpenUpload = () => {
    setUploadFile(null)
    setUploadTitle('')
    setUploadStockCode('')
    setUploadStockName('')
    setUploadCategory('研报分析')
    setShowUploadModal(true)
  }

  // 选择文件
  const handleFileChange = (e) => {
    const file = e.target.files?.[0]
    if (file) {
      setUploadFile(file)
      if (!uploadTitle) {
        const nameWithoutExt = file.name.replace(/\.[^/.]+$/, '')
        setUploadTitle(nameWithoutExt)
      }
    }
  }

  // 提交本地上传
  const handleSubmitUpload = async (e) => {
    if (e) e.preventDefault()
    if (!uploadFile) {
      showToast('⚠️ 请选择要上传的研报或财报文件')
      return
    }

    setUploading(true)
    showToast('⏳ 正在上传并由后端自动完成金融语义分块与向量化...')
    try {
      const formData = new FormData()
      formData.append('file', uploadFile)
      formData.append('category', uploadCategory)
      if (uploadTitle.trim()) formData.append('title', uploadTitle.trim())
      if (uploadStockCode.trim()) formData.append('stock_code', uploadStockCode.trim())
      if (uploadStockName.trim()) formData.append('stock_name', uploadStockName.trim())

      const res = await fetch(getApiUrl('/api/rag/upload'), {
        method: 'POST',
        body: formData,
      })
      const json = await res.json()
      if (json.success) {
        showToast(json.message || '🎉 文档上传与解析入库成功！')
        setShowUploadModal(false)
        fetchStats()
        fetchDocs()
      } else {
        showToast(`❌ 入库失败: ${json.error}`)
      }
    } catch (err) {
      showToast(`❌ 上传异常: ${err.message}`)
    } finally {
      setUploading(false)
    }
  }

  // 打开【加载机构/投行研报】模态框
  const handleOpenFetchModal = () => {
    setShowFetchModal(true)
    setFetchTab('batch')
    if (previewReports.length === 0) {
      loadPreviewReports()
    }
  }

  // 抓取并预览机构研报列表
  const loadPreviewReports = async (symbol = fetchSymbol, rating = fetchRating, kw = fetchKeyword) => {
    setPreviewReportsLoading(true)
    try {
      let url = getApiUrl('/api/rag/preview-reports?')
      const params = new URLSearchParams()
      if (symbol && symbol.trim()) params.append('symbol', symbol.trim())
      if (rating && rating !== '*') params.append('rating', rating)
      if (kw && kw.trim()) params.append('keyword', kw.trim())
      params.append('count', '25')
      url += params.toString()

      const res = await fetch(url)
      if (res.ok) {
        const json = await res.json()
        if (json.success && Array.isArray(json.data)) {
          setPreviewReports(json.data)
          // 默认全选前 5 篇
          const initialSelected = new Set(json.data.slice(0, 5).map((r) => r.infoCode))
          setSelectedInfoCodes(initialSelected)
        }
      }
    } catch (e) {
      console.warn('Failed to load preview reports:', e)
    } finally {
      setPreviewReportsLoading(false)
    }
  }

  // 执行批量抓取导入
  const handleBatchFetchReports = async () => {
    setFetching(true)
    showToast('⏳ 正在直连券商/投行权威研报库下载并向量化入库...')
    try {
      const res = await fetch(getApiUrl('/api/rag/fetch-reports'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: fetchSymbol.trim(),
          count: fetchCount,
          category: fetchCategory,
          rating: fetchRating,
          keyword: fetchKeyword.trim(),
        }),
      })
      const json = await res.json()
      if (json.success) {
        showToast(json.message || '🎉 机构研报已成功下载并入库！')
        setShowFetchModal(false)
        fetchStats()
        fetchDocs()
      } else {
        showToast(`❌ 抓取入库失败: ${json.error}`)
      }
    } catch (err) {
      showToast(`❌ 网络请求异常: ${err.message}`)
    } finally {
      setFetching(false)
    }
  }

  // 导入勾选的研报
  const handleImportSelectedReports = async () => {
    if (selectedInfoCodes.size === 0) {
      showToast('⚠️ 请勾选至少一篇要导入的机构研报')
      return
    }
    setFetching(true)
    showToast(`⏳ 正在下载并导入所选 ${selectedInfoCodes.size} 篇机构研报...`)
    try {
      const res = await fetch(getApiUrl('/api/rag/fetch-reports'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: fetchSymbol.trim(),
          count: selectedInfoCodes.size,
          category: fetchCategory,
          rating: fetchRating,
          keyword: fetchKeyword.trim(),
          selected_info_codes: Array.from(selectedInfoCodes),
        }),
      })
      const json = await res.json()
      if (json.success) {
        showToast(json.message || '🎉 所选研报已成功导入知识库！')
        setShowFetchModal(false)
        fetchStats()
        fetchDocs()
      } else {
        showToast(`❌ 导入失败: ${json.error}`)
      }
    } catch (err) {
      showToast(`❌ 网络请求异常: ${err.message}`)
    } finally {
      setFetching(false)
    }
  }

  const toggleSelectAllReports = () => {
    if (selectedInfoCodes.size === previewReports.length) {
      setSelectedInfoCodes(new Set())
    } else {
      setSelectedInfoCodes(new Set(previewReports.map((r) => r.infoCode)))
    }
  }

  const toggleSelectReport = (infoCode) => {
    const next = new Set(selectedInfoCodes)
    if (next.has(infoCode)) {
      next.delete(infoCode)
    } else {
      next.add(infoCode)
    }
    setSelectedInfoCodes(next)
  }

  // 删除文档
  const handleDeleteDoc = async (docId, docTitle) => {
    if (!window.confirm(`确认从知识库移除文档《${docTitle}》吗？其切片与向量数据将同步清理。`)) {
      return
    }
    try {
      const res = await fetch(getApiUrl(`/api/rag/documents/${docId}`), {
        method: 'DELETE',
      })
      const json = await res.json()
      if (json.success) {
        showToast(`🗑️ ${json.message || '文档已删除'}`)
        fetchStats()
        fetchDocs()
      } else {
        showToast(`❌ 删除失败: ${json.error}`)
      }
    } catch (err) {
      showToast(`❌ 删除异常: ${err.message}`)
    }
  }

  // 查看切片
  const handlePreviewChunks = async (doc) => {
    setPreviewDoc(doc)
    setPreviewChunks([])
    setPreviewLoading(true)
    try {
      const res = await fetch(getApiUrl(`/api/rag/documents/${doc.id}/chunks`))
      if (res.ok) {
        const json = await res.json()
        if (json.success && Array.isArray(json.data)) {
          setPreviewChunks(json.data)
        }
      }
    } catch (e) {
      console.warn('Failed to load chunks:', e)
    } finally {
      setPreviewLoading(false)
    }
  }

  // 恢复内置示例
  const handleInitSamples = async () => {
    showToast('🔄 正在检查并恢复示例研报与财报数据...')
    try {
      const res = await fetch(getApiUrl('/api/rag/init-samples'), { method: 'POST' })
      const json = await res.json()
      if (json.success) {
        showToast(`✅ ${json.message}`)
        fetchStats()
        fetchDocs()
      } else {
        showToast(`⚠️ ${json.error}`)
      }
    } catch (err) {
      showToast(`❌ 恢复样本异常: ${err.message}`)
    }
  }

  // 基于此文档提问
  const handleAskAboutDoc = (doc) => {
    setActiveTab('qa')
    const stockPrefix = doc.stock_name ? `${doc.stock_name}（${doc.stock_code}）` : `《${doc.title}》`
    setQuestion(`请基于《${doc.title}》，详细提炼其核心数据指标、成长驱动力以及存在的风险提示。`)
    setQaCategory(doc.category)
    if (doc.stock_code) setQaStockCode(doc.stock_code)
    showToast(`💡 已为您载入针对 ${stockPrefix} 的深度问答提示词，可直接点击解答！`)
  }

  return (
    <section className="rag-page-view">
      {/* 顶部标题与操作栏 */}
      <div className="rag-page-header">
        <div className="rag-page-title-box">
          <div className="rag-page-badge">📚 RAG 投研增强引擎</div>
          <h2>研报分析与财报解读 RAG 知识库</h2>
          <p className="rag-page-subtitle">
            集成多格式文档解析、金融文本切片与向量语义索引，支持一键实时下载机构/投行权威研报与财报解读并自动入库
          </p>
        </div>
        <div className="rag-page-actions">
          <button
            type="button"
            className="btn-fetch-reports"
            onClick={handleOpenFetchModal}
            title="直连头部券商与权威财经机构，在线下载最新研报与财报解读入库"
          >
            <span>📥 加载近期机构研报</span>
          </button>
          <button
            type="button"
            className="btn-upload-doc"
            onClick={handleOpenUpload}
            title="手动上传本地 PDF、Word、TXT、Markdown 等投研文档"
          >
            <span>➕ 上传本地文档</span>
          </button>
          <button
            type="button"
            className="btn-sample-doc"
            onClick={handleInitSamples}
            title="一键加载茅台、宁德时代、比亚迪等内置示范研报"
          >
            <span>✨ 恢复示范研报</span>
          </button>
          <button
            type="button"
            className="btn-refresh-rag"
            onClick={() => {
              fetchStats()
              fetchDocs()
              showToast('🔄 知识库数据已刷新')
            }}
            title="刷新知识库数据与索引"
          >
            <span>🔄 刷新</span>
          </button>
        </div>
      </div>

      {/* 核心指标统计卡片 */}
      <div className="rag-stats-grid">
        <div className="rag-stat-card">
          <div className="stat-icon-wrap blue">📚</div>
          <div className="stat-content">
            <span className="stat-label">入库文档总数</span>
            <span className="stat-value">
              {stats.total_docs} <small>篇</small>
            </span>
          </div>
        </div>

        <div className="rag-stat-card">
          <div className="stat-icon-wrap cyan">📈</div>
          <div className="stat-content">
            <span className="stat-label">研报分析文档</span>
            <span className="stat-value text-cyan">
              {stats.research_docs} <small>篇</small>
            </span>
          </div>
        </div>

        <div className="rag-stat-card">
          <div className="stat-icon-wrap emerald">📊</div>
          <div className="stat-content">
            <span className="stat-label">财报解读文档</span>
            <span className="stat-value text-emerald">
              {stats.financial_docs} <small>篇</small>
            </span>
          </div>
        </div>

        <div className="rag-stat-card">
          <div className="stat-icon-wrap purple">🧩</div>
          <div className="stat-content">
            <span className="stat-label">向量切片总量 (Chunks)</span>
            <span className="stat-value text-purple">
              {stats.total_chunks} <small>段</small>
            </span>
          </div>
        </div>

        <div className="rag-stat-card">
          <div className="stat-icon-wrap amber">🎯</div>
          <div className="stat-content">
            <span className="stat-label">覆盖标的个股</span>
            <span className="stat-value text-amber">
              {stats.stocks_count} <small>只</small>
            </span>
          </div>
        </div>
      </div>

      {/* 主功能区域切换导航 */}
      <div className="rag-tabs-nav">
        <button
          type="button"
          className={`rag-tab-btn ${activeTab === 'qa' ? 'active' : ''}`}
          onClick={() => setActiveTab('qa')}
        >
          <span className="tab-icon">🤖</span>
          <span className="tab-text">智能投研与财报问答 (RAG)</span>
          {sources.length > 0 && <span className="tab-chip">引用 {sources.length} 条</span>}
        </button>

        <button
          type="button"
          className={`rag-tab-btn ${activeTab === 'docs' ? 'active' : ''}`}
          onClick={() => setActiveTab('docs')}
        >
          <span className="tab-icon">📁</span>
          <span className="tab-text">投研文档管理中心</span>
          <span className="tab-chip">{docs.length} 篇</span>
        </button>
      </div>

      {/* 🤖 选项卡 1：智能投研与财报问答 */}
      {activeTab === 'qa' && (
        <div className="rag-qa-section">
          {/* 快捷问题提示词芯片栏 */}
          <div className="rag-preset-chips-box">
            <span className="preset-label">💡 猜你想问：</span>
            <div className="preset-chips-list">
              {PRESET_QUESTIONS.map((p, idx) => (
                <button
                  key={idx}
                  type="button"
                  className="preset-chip"
                  onClick={() => handleSelectPreset(p)}
                  title={p.text}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* 问答输入交互面板 */}
          <div className="rag-query-card">
            <div className="query-filter-bar">
              <div className="category-radios">
                <span className="filter-title">知识分类检索：</span>
                {['全部', '研报分析', '财报解读'].map((c) => (
                  <label key={c} className={`cat-radio-label ${qaCategory === c ? 'active' : ''}`}>
                    <input
                      type="radio"
                      name="qaCategory"
                      value={c}
                      checked={qaCategory === c}
                      onChange={() => setQaCategory(c)}
                    />
                    <span>{c === '全部' ? '🌐 全部' : c === '研报分析' ? '📈 研报分析' : '📊 财报解读'}</span>
                  </label>
                ))}
              </div>

              <div className="stock-code-filter-wrap">
                <span className="filter-title">限定股票代码：</span>
                <input
                  type="text"
                  className="stock-code-input"
                  placeholder="如 600519 (选填)"
                  value={qaStockCode}
                  onChange={(e) => setQaStockCode(e.target.value)}
                />
              </div>
            </div>

            <div className="query-input-row">
              <textarea
                className="rag-textarea"
                rows={3}
                placeholder="在此输入你想向知识库咨询的问题，例如：贵州茅台一季度净利润与毛利率表现如何？宁德时代有哪些核心催化剂？宝丰能源未来产能规划如何？"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault()
                    handleQuery()
                  }
                }}
              />
              <div className="query-actions-wrap">
                <button
                  type="button"
                  className="btn-submit-query"
                  disabled={asking}
                  onClick={() => handleQuery()}
                >
                  {asking ? (
                    <>
                      <span className="btn-spinner"></span>
                      <span>检索与研判中...</span>
                    </>
                  ) : (
                    <>
                      <span>🚀 深度解读与分析</span>
                      <small className="key-hint">(Ctrl+Enter)</small>
                    </>
                  )}
                </button>
                {question && (
                  <button
                    type="button"
                    className="btn-clear-query"
                    onClick={() => {
                      setQuestion('')
                      setAnswer(null)
                      setSources([])
                    }}
                  >
                    清空
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* AI 分析成果卡片 */}
          {answer && (
            <div className="rag-answer-container">
              <div className="rag-answer-header">
                <div className="answer-title-wrap">
                  <span className="answer-logo">✨</span>
                  <h3>AI 投研分析与深度解读报告</h3>
                  <span className="model-badge">Deep RAG Synthesis</span>
                </div>
                <div className="answer-tools">
                  <button
                    type="button"
                    className="btn-copy-answer"
                    onClick={handleCopyAnswer}
                    title="复制回答到剪贴板"
                  >
                    📋 复制分析
                  </button>
                  {sources.length > 0 && (
                    <button
                      type="button"
                      className="btn-toggle-sources"
                      onClick={() => setShowSources(!showSources)}
                    >
                      {showSources ? '收起引用来源 ▲' : `展开引用来源 (${sources.length}) ▼`}
                    </button>
                  )}
                </div>
              </div>

              <div className="rag-answer-body">
                <FormattedMarkdown content={answer} />
              </div>

              {/* 知识库引用切片面板 */}
              {showSources && sources.length > 0 && (
                <div className="rag-sources-panel">
                  <div className="sources-header">
                    <span>📎 本次回答依据的知识库切片来源 ({sources.length} 条)</span>
                  </div>
                  <div className="sources-grid">
                    {sources.map((s, idx) => (
                      <div key={idx} className="source-card">
                        <div className="source-card-header">
                          <div className="source-doc-title">
                            <span className="source-num">#{idx + 1}</span>
                            <strong>{s.title}</strong>
                          </div>
                          <div className="source-meta-badges">
                            <span className={`cat-pill ${s.category === '研报分析' ? 'research' : 'financial'}`}>
                              {s.category}
                            </span>
                            {s.stock_name && (
                              <span className="stock-pill">
                                {s.stock_code} {s.stock_name}
                              </span>
                            )}
                            <span className="score-pill" title="语义相关度匹配分数">
                              相似度 {Math.round(s.score * 100)}%
                            </span>
                          </div>
                        </div>
                        <div className="source-snippet">
                          <p>{s.text}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 📁 选项卡 2：投研文档管理中心 */}
      {activeTab === 'docs' && (
        <div className="rag-docs-section">
          <div className="docs-toolbar">
            <div className="docs-filter-group">
              <div className="doc-category-tabs">
                {['全部', '研报分析', '财报解读'].map((c) => (
                  <button
                    key={c}
                    type="button"
                    className={`doc-filter-btn ${filterCategory === c ? 'active' : ''}`}
                    onClick={() => setFilterCategory(c)}
                  >
                    {c}
                  </button>
                ))}
              </div>

              <div className="doc-search-box">
                <input
                  type="text"
                  placeholder="搜索文档名称、机构、股票代码、核心摘要..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && fetchDocs()}
                />
                <button type="button" className="btn-search-exec" onClick={fetchDocs}>
                  🔍 搜索
                </button>
              </div>
            </div>

            <div className="docs-action-group">
              <button
                type="button"
                className="btn-fetch-reports-sub"
                onClick={handleOpenFetchModal}
                title="直连券商/投行在线下载研报入库"
              >
                <span>📥 抓取机构研报</span>
              </button>
              <button
                type="button"
                className="btn-create-task"
                onClick={handleOpenUpload}
              >
                <span>➕ 上传本地文档</span>
              </button>
            </div>
          </div>

          {/* 文档列表渲染 */}
          {loadingDocs ? (
            <div className="docs-loading-state">
              <span className="loading-spinner"></span>
              <span>正在拉取知识库文档与向量索引...</span>
            </div>
          ) : docs.length === 0 ? (
            <div className="task-empty-state">
              <div className="task-empty-icon">📂</div>
              <div className="task-empty-title">知识库中暂无匹配文档</div>
              <p>点击上方“📥 抓取机构研报”在线下载券商研报，或上传本地 PDF / Word / Markdown 文件。</p>
              <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center' }}>
                <button type="button" className="btn-fetch-reports" onClick={handleOpenFetchModal}>
                  📥 在线抓取机构研报
                </button>
                <button type="button" className="btn-create-task" onClick={handleOpenUpload}>
                  ➕ 上传本地文档
                </button>
              </div>
            </div>
          ) : (
            <div className="rag-docs-grid">
              {docs.map((doc) => {
                const isInstitutional = doc.title?.includes('：') || doc.original_name?.includes('_AP')
                return (
                  <div key={doc.id} className="rag-doc-card">
                    <div className="doc-card-top">
                      <div className="doc-type-icon">
                        {doc.original_name?.endsWith('.pdf')
                          ? '📕'
                          : doc.original_name?.endsWith('.docx')
                          ? '📘'
                          : isInstitutional
                          ? '🏛️'
                          : '📄'}
                      </div>
                      <div className="doc-title-block">
                        <h4 className="doc-title" title={doc.title}>
                          {doc.title}
                        </h4>
                        <span className="doc-file-name" title={doc.original_name}>
                          {doc.original_name}
                        </span>
                      </div>
                    </div>

                    <div className="doc-card-tags">
                      <span className={`doc-cat-tag ${doc.category === '研报分析' ? 'research' : 'financial'}`}>
                        {doc.category === '研报分析' ? '📈 研报分析' : '📊 财报解读'}
                      </span>
                      {doc.stock_code && (
                        <span className="doc-stock-tag">
                          {doc.stock_code} {doc.stock_name}
                        </span>
                      )}
                      {isInstitutional && (
                        <span className="doc-org-tag">
                          🏛️ 权威机构
                        </span>
                      )}
                      <span className="doc-chunk-tag">
                        🧩 {doc.chunk_count} 个切片
                      </span>
                      <span className="doc-size-tag">
                        💾 {doc.file_size_human}
                      </span>
                    </div>

                    {doc.summary && (
                      <p className="doc-summary-text" title={doc.summary}>
                        {doc.summary}
                      </p>
                    )}

                    <div className="doc-card-footer">
                      <span className="doc-upload-time">📅 {doc.upload_time}</span>
                      <div className="doc-actions-wrap">
                        <button
                          type="button"
                          className="btn-doc-act view"
                          onClick={() => handlePreviewChunks(doc)}
                          title="查看此文档切分出的所有知识片段"
                        >
                          🔍 切片
                        </button>
                        <button
                          type="button"
                          className="btn-doc-act ask"
                          onClick={() => handleAskAboutDoc(doc)}
                          title="跳转并以此文档为上下文进行智能问答"
                        >
                          💬 问答
                        </button>
                        <button
                          type="button"
                          className="btn-doc-act delete"
                          onClick={() => handleDeleteDoc(doc.id, doc.title)}
                          title="从知识库移除文档与向量"
                        >
                          🗑️
                        </button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* 模态框 1：📥 在线下载并导入机构研报财报 */}
      {showFetchModal && (
        <div className="rec-modal-overlay" onClick={() => setShowFetchModal(false)}>
          <div className="rec-modal-dialog rag-fetch-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="rec-modal-header">
              <div className="rec-modal-title">
                <span>📥</span>
                <h3>加载机构/投行研报财报到知识库</h3>
                <span className="rec-modal-count">权威金融数据直连</span>
              </div>
              <button
                type="button"
                className="rec-modal-close"
                onClick={() => setShowFetchModal(false)}
              >
                ✕
              </button>
            </div>

            {/* 抓取模式子导航 */}
            <div className="fetch-sub-tabs">
              <button
                type="button"
                className={`fetch-sub-tab-btn ${fetchTab === 'batch' ? 'active' : ''}`}
                onClick={() => setFetchTab('batch')}
              >
                ⚡ 批量自动抓取入库
              </button>
              <button
                type="button"
                className={`fetch-sub-tab-btn ${fetchTab === 'preview' ? 'active' : ''}`}
                onClick={() => {
                  setFetchTab('preview')
                  if (previewReports.length === 0) loadPreviewReports()
                }}
              >
                📋 在线列表预览与自选入库
              </button>
            </div>

            {/* 子模式 1：批量自动抓取入库 */}
            {fetchTab === 'batch' && (
              <div className="task-edit-body">
                <div className="form-group">
                  <label className="form-label">1. 抓取标的范围:</label>
                  <div className="script-presets-group">
                    <button
                      type="button"
                      className={`script-preset-btn ${fetchSymbol === '' ? 'active' : ''}`}
                      onClick={() => setFetchSymbol('')}
                    >
                      🌟 全市场龙头最新研报 (跨券商最新发布)
                    </button>
                    <button
                      type="button"
                      className={`script-preset-btn ${fetchSymbol === '600519' ? 'active' : ''}`}
                      onClick={() => setFetchSymbol('600519')}
                    >
                      🍷 贵州茅台 (600519)
                    </button>
                    <button
                      type="button"
                      className={`script-preset-btn ${fetchSymbol === '300750' ? 'active' : ''}`}
                      onClick={() => setFetchSymbol('300750')}
                    >
                      ⚡ 宁德时代 (300750)
                    </button>
                    <button
                      type="button"
                      className={`script-preset-btn ${fetchSymbol === '002594' ? 'active' : ''}`}
                      onClick={() => setFetchSymbol('002594')}
                    >
                      🚗 比亚迪 (002594)
                    </button>
                  </div>
                  <input
                    type="text"
                    className="form-control"
                    placeholder="输入特定 A 股代码，例如 600036、000858（留空表示全市场龙头）"
                    value={fetchSymbol}
                    onChange={(e) => setFetchSymbol(e.target.value)}
                  />
                </div>

                <div className="form-row-two">
                  <div className="form-group">
                    <label className="form-label">2. 本次抓取篇数:</label>
                    <div className="cron-presets-group">
                      {[3, 5, 10, 15].map((cnt) => (
                        <button
                          key={cnt}
                          type="button"
                          className={`cron-preset-btn ${fetchCount === cnt ? 'active' : ''}`}
                          onClick={() => setFetchCount(cnt)}
                        >
                          {cnt} 篇
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="form-group">
                    <label className="form-label">3. 机构投资评级筛选:</label>
                    <div className="cron-presets-group">
                      {[
                        { label: '全部 (*)', val: '*' },
                        { label: '买入', val: '买入' },
                        { label: '增持', val: '增持' },
                      ].map((item) => (
                        <button
                          key={item.val}
                          type="button"
                          className={`cron-preset-btn ${fetchRating === item.val ? 'active' : ''}`}
                          onClick={() => setFetchRating(item.val)}
                        >
                          {item.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="form-row-two">
                  <div className="form-group">
                    <label className="form-label">4. 知识分类归属:</label>
                    <select
                      className="form-control"
                      value={fetchCategory}
                      onChange={(e) => setFetchCategory(e.target.value)}
                    >
                      <option value="自动">自动智能分类 (含季报/年报/中报判定为财报解读)</option>
                      <option value="研报分析">全部强制归为【研报分析】</option>
                      <option value="财报解读">全部强制归为【财报解读】</option>
                    </select>
                  </div>

                  <div className="form-group">
                    <label className="form-label">5. 关键词过滤 (选填):</label>
                    <input
                      type="text"
                      className="form-control"
                      placeholder="如: 半年报、出海、算力、高股息"
                      value={fetchKeyword}
                      onChange={(e) => setFetchKeyword(e.target.value)}
                    />
                  </div>
                </div>

                <div className="form-instant-notice">
                  <span className="notice-icon">⚡</span>
                  <div className="notice-text">
                    <strong>全流程自动化说明</strong>：系统将直连权威机构数据库拉取研报正文与投资要点，自动进行<strong>金融语义切片与向量化入库</strong>，并在完成后即刻刷新知识库。
                  </div>
                </div>

                <div className="task-edit-footer" style={{ padding: '1rem 0 0' }}>
                  <button
                    type="button"
                    className="btn-cancel"
                    onClick={() => setShowFetchModal(false)}
                    disabled={fetching}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="btn-fetch-reports"
                    onClick={handleBatchFetchReports}
                    disabled={fetching}
                  >
                    {fetching ? '⏳ 正在抓取并分块入库...' : '🚀 立即抓取并导入知识库'}
                  </button>
                </div>
              </div>
            )}

            {/* 子模式 2：在线列表预览与自选入库 */}
            {fetchTab === 'preview' && (
              <div className="task-edit-body preview-mode-body">
                <div className="preview-toolbar">
                  <div className="preview-inputs">
                    <input
                      type="text"
                      className="stock-code-input"
                      style={{ width: '150px' }}
                      placeholder="股票代码 (如 600519)"
                      value={fetchSymbol}
                      onChange={(e) => setFetchSymbol(e.target.value)}
                    />
                    <input
                      type="text"
                      className="stock-code-input"
                      style={{ width: '160px' }}
                      placeholder="标题/机构关键词"
                      value={fetchKeyword}
                      onChange={(e) => setFetchKeyword(e.target.value)}
                    />
                    <button
                      type="button"
                      className="btn-search-exec"
                      onClick={() => loadPreviewReports()}
                    >
                      🔄 刷新列表
                    </button>
                  </div>

                  <div className="preview-select-tools">
                    <button
                      type="button"
                      className="btn-select-toggle"
                      onClick={toggleSelectAllReports}
                    >
                      {selectedInfoCodes.size === previewReports.length && previewReports.length > 0
                        ? '取消全选'
                        : '全选'}
                    </button>
                    <span className="selected-counter">
                      已选 <strong>{selectedInfoCodes.size}</strong> 篇
                    </span>
                  </div>
                </div>

                {previewReportsLoading ? (
                  <div className="docs-loading-state" style={{ padding: '2rem' }}>
                    <span className="loading-spinner"></span>
                    <span>正在连接机构接口检索研报列表...</span>
                  </div>
                ) : previewReports.length === 0 ? (
                  <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '2rem' }}>
                    暂未检索到符合条件的机构研报，请调整筛选参数重试
                  </p>
                ) : (
                  <div className="preview-reports-list">
                    {previewReports.map((item) => {
                      const isSelected = selectedInfoCodes.has(item.infoCode)
                      return (
                        <div
                          key={item.infoCode}
                          className={`preview-report-row ${isSelected ? 'selected' : ''}`}
                          onClick={() => toggleSelectReport(item.infoCode)}
                        >
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelectReport(item.infoCode)}
                            onClick={(e) => e.stopPropagation()}
                          />
                          <div className="row-main">
                            <div className="row-badges">
                              <span className="row-org-badge">🏛️ {item.orgSName}</span>
                              <span className="row-stock-badge">
                                {item.stockCode} {item.stockName}
                              </span>
                              <span className="row-rating-badge">{item.emRatingName}</span>
                              <span className="row-cat-badge">{item.category}</span>
                              <span className="row-date">{item.publishDate}</span>
                            </div>
                            <h5 className="row-title" title={item.title}>
                              {item.title}
                            </h5>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}

                <div className="task-edit-footer" style={{ padding: '1rem 0 0' }}>
                  <button
                    type="button"
                    className="btn-cancel"
                    onClick={() => setShowFetchModal(false)}
                    disabled={fetching}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="btn-fetch-reports"
                    onClick={handleImportSelectedReports}
                    disabled={fetching || selectedInfoCodes.size === 0}
                  >
                    {fetching
                      ? '⏳ 正在下载并导入...'
                      : `📥 将勾选研报导入知识库 (${selectedInfoCodes.size} 篇)`}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 模态框 2：手动上传本地文档到知识库 */}
      {showUploadModal && (
        <div className="rec-modal-overlay" onClick={() => setShowUploadModal(false)}>
          <div className="rec-modal-dialog rag-upload-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="rec-modal-header">
              <div className="rec-modal-title">
                <span>📤</span>
                <h3>手动上传本地研报 / 财报文档</h3>
              </div>
              <button
                type="button"
                className="rec-modal-close"
                onClick={() => setShowUploadModal(false)}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSubmitUpload}>
              <div className="task-edit-body">
                <div className="form-group">
                  <label className="form-label">
                    1. 选择投研文档文件 <span className="req">*</span>:
                  </label>
                  <div
                    className="rag-drop-zone"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <input
                      type="file"
                      ref={fileInputRef}
                      style={{ display: 'none' }}
                      accept=".pdf,.docx,.doc,.txt,.md,.markdown"
                      onChange={handleFileChange}
                    />
                    <div className="drop-icon">📁</div>
                    {uploadFile ? (
                      <div className="drop-selected">
                        <span className="file-name">{uploadFile.name}</span>
                        <span className="file-size">
                          ({(uploadFile.size / 1024).toFixed(1)} KB)
                        </span>
                        <span className="change-tip">点击可重新选择文件</span>
                      </div>
                    ) : (
                      <div className="drop-prompt">
                        <strong>点击选择文件</strong> 或将文件拖拽至此处
                        <small>支持 PDF、Word (.docx)、Markdown (.md)、TXT 文件</small>
                      </div>
                    )}
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">
                    2. 文档知识分类 <span className="req">*</span>:
                  </label>
                  <div className="script-presets-group">
                    <button
                      type="button"
                      className={`script-preset-btn ${uploadCategory === '研报分析' ? 'active' : ''}`}
                      onClick={() => setUploadCategory('研报分析')}
                    >
                      📈 研报分析 (券商深度报告、行业评级、投资逻辑、目标价)
                    </button>
                    <button
                      type="button"
                      className={`script-preset-btn ${uploadCategory === '财报解读' ? 'active' : ''}`}
                      onClick={() => setUploadCategory('财报解读')}
                    >
                      📊 财报解读 (年报/季报、营收净利、毛利率、现金流诊断)
                    </button>
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">3. 文档标题 (可自拟):</label>
                  <input
                    type="text"
                    className="form-control"
                    placeholder="留空则自动使用文件名"
                    value={uploadTitle}
                    onChange={(e) => setUploadTitle(e.target.value)}
                  />
                </div>

                <div className="form-row-two">
                  <div className="form-group">
                    <label className="form-label">关联股票代码 (选填):</label>
                    <input
                      type="text"
                      className="form-control"
                      placeholder="如: 600519 或 300750"
                      value={uploadStockCode}
                      onChange={(e) => setUploadStockCode(e.target.value)}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">关联股票名称 (选填):</label>
                    <input
                      type="text"
                      className="form-control"
                      placeholder="如: 贵州茅台 或 宁德时代"
                      value={uploadStockName}
                      onChange={(e) => setUploadStockName(e.target.value)}
                    />
                  </div>
                </div>

                <div className="form-instant-notice">
                  <span className="notice-icon">⚡</span>
                  <div className="notice-text">
                    <strong>智能解析入库机制</strong>：文件上传后，后端将自动进行<strong>段落识别、表格抽取、金融语义切片并写入 Chroma 向量数据库</strong>，入库后即可立即进行自然语言问答提炼！
                  </div>
                </div>
              </div>

              <div className="task-edit-footer">
                <button
                  type="button"
                  className="btn-cancel"
                  onClick={() => setShowUploadModal(false)}
                  disabled={uploading}
                >
                  取消
                </button>
                <button type="submit" className="btn-save-task" disabled={uploading}>
                  {uploading ? '⏳ 正在解析并向量化...' : '🚀 立即解析入库'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 模态框 3：切片预览模态框 */}
      {previewDoc && (
        <div className="rec-modal-overlay" onClick={() => setPreviewDoc(null)}>
          <div className="rec-modal-dialog rag-chunks-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="rec-modal-header">
              <div className="rec-modal-title">
                <span>🧩</span>
                <h3>文档切片预览 - 《{previewDoc.title}》</h3>
                <span className="rec-modal-count">共 {previewChunks.length} 个分块</span>
              </div>
              <button
                type="button"
                className="rec-modal-close"
                onClick={() => setPreviewDoc(null)}
              >
                ✕
              </button>
            </div>

            <div className="rec-modal-body chunks-modal-body">
              {previewLoading ? (
                <div className="docs-loading-state">
                  <span className="loading-spinner"></span>
                  <span>正在读取向量分块片段...</span>
                </div>
              ) : previewChunks.length === 0 ? (
                <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '2rem' }}>
                  未获取到分块内容
                </p>
              ) : (
                <div className="chunks-list">
                  {previewChunks.map((c, idx) => (
                    <div key={idx} className="chunk-preview-card">
                      <div className="chunk-meta-bar">
                        <span className="chunk-idx-badge">分块 #{idx + 1}</span>
                        <span className="chunk-page-tag">第 {c.page} 页/节</span>
                        <span className="chunk-len-tag">{c.text?.length || 0} 字符</span>
                      </div>
                      <div className="chunk-text-box">
                        <pre>{c.text}</pre>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="rec-modal-footer">
              <span className="rec-footer-tip">
                分块规则：按研报/财报段落与三级标题自动切分，预留 120 字符重叠窗口保障语义连贯
              </span>
              <button
                type="button"
                className="btn-modal-done"
                onClick={() => setPreviewDoc(null)}
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
