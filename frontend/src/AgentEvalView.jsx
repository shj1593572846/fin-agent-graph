import React, { useState, useEffect } from 'react'

export default function AgentEvalView({ getApiUrl }) {
  // 启动评测表单配置
  const [evalMode, setEvalMode] = useState('benchmark') // 'benchmark' | 'offline' | 'live'
  const [benchmarkCase, setBenchmarkCase] = useState('local_cache') // 'local_cache' | 'bear_defensive'
  const [topic, setTopic] = useState('')
  const [useLlmJudge, setUseLlmJudge] = useState(true)

  // 运行状态与结果
  const [isRunning, setIsRunning] = useState(false)
  const [currentResult, setCurrentResult] = useState(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [activeStepTab, setActiveStepTab] = useState(null) // 展开查看特定中间步骤详情

  // 历史报告归档
  const [historyReports, setHistoryReports] = useState([])
  const [selectedReportId, setSelectedReportId] = useState('')
  const [loadingHistory, setLoadingHistory] = useState(false)

  // 获取历史报告列表
  const fetchHistoryReports = async () => {
    setLoadingHistory(true)
    try {
      const res = await fetch(getApiUrl('/api/eval/reports'))
      if (res.ok) {
        const json = await res.json()
        if (json.success && Array.isArray(json.data)) {
          setHistoryReports(json.data)
          // 首次默认载入最新一份评测报告展示
          if (json.data.length > 0 && !currentResult) {
            loadReportDetail(json.data[0])
          }
        }
      }
    } catch (e) {
      console.warn('获取历史评测报告失败:', e)
    } finally {
      setLoadingHistory(false)
    }
  }

  // 载入特定历史报告详情
  const loadReportDetail = async (reportMeta) => {
    try {
      setSelectedReportId(reportMeta.eval_id)
      const fileName = reportMeta.json_file ? reportMeta.json_file.split('\\').pop().split('/').pop() : ''
      if (!fileName) return

      const res = await fetch(getApiUrl(`/api/eval/reports/${fileName}/json`))
      if (res.ok) {
        const json = await res.json()
        if (json.success && json.data) {
          setCurrentResult(json.data)
          setErrorMessage('')
        }
      }
    } catch (e) {
      console.warn('加载报告详情失败:', e)
    }
  }

  // 触发页面启动评测
  const handleStartEvaluation = async () => {
    if (isRunning) return
    setIsRunning(true)
    setErrorMessage('')
    try {
      const payload = {
        mode: evalMode,
        topic: topic.trim(),
        case: benchmarkCase,
        use_llm_judge: useLlmJudge,
      }

      const res = await fetch(getApiUrl('/api/eval/run'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      const json = await res.json()
      if (json.success && json.data) {
        setCurrentResult(json.data)
        setSelectedReportId(json.data.eval_id)
        // 刷新历史列表
        fetchHistoryReports()
      } else {
        setErrorMessage(json.error || '评测运行失败，请检查控制台或后端日志')
      }
    } catch (e) {
      setErrorMessage(`网络或服务端异常: ${e.message}`)
    } finally {
      setIsRunning(false)
    }
  }

  useEffect(() => {
    fetchHistoryReports()
  }, [])

  // 分数对应颜色
  const getScoreColor = (score) => {
    if (score >= 90) return '#10b981'
    if (score >= 80) return '#3b82f6'
    if (score >= 70) return '#f59e0b'
    return '#ef4444'
  }

  // 打开独立完整 HTML 仪表盘报告
  const handleOpenHtmlReport = () => {
    if (!currentResult) return
    const baseName = `${currentResult.eval_id}_${currentResult.target_topic || '全市场'}`.replace(/\//g, '_').replace(/\\/g, '_').replace(/ /g, '_')
    window.open(getApiUrl(`/api/eval/reports/${baseName}.html/html`), '_blank')
  }

  return (
    <div className="agent-eval-container">
      {/* 顶部标题区 */}
      <div className="eval-top-header">
        <div className="eval-header-title">
          <h2>📊 选股 Agent 评测中心与中间步骤诊断</h2>
          <p className="eval-header-sub">
            全链路中间步骤插桩追踪 · 确定性规则与大模型投研专家双引擎评分 · 实时报告输出
          </p>
        </div>
        <div className="eval-header-actions">
          <button
            type="button"
            className="eval-btn-secondary"
            onClick={fetchHistoryReports}
            disabled={loadingHistory}
          >
            🔄 刷新历史报告
          </button>
          {currentResult && (
            <button
              type="button"
              className="eval-btn-primary"
              onClick={handleOpenHtmlReport}
            >
              🌐 打开独立 HTML 仪表盘
            </button>
          )}
        </div>
      </div>

      {/* 核心主网格：左侧启动控制台与历史报告，右侧实时评测报告与诊断 */}
      <div className="eval-main-grid">
        {/* 左侧控制栏 */}
        <aside className="eval-sidebar">
          {/* 1. 页面启动评测控制卡片 */}
          <div className="eval-card launch-card">
            <div className="eval-card-header">
              <span className="card-badge">CONTROL</span>
              <h3>🚀 页面启动评测</h3>
            </div>

            {/* 评测模式选择 */}
            <div className="eval-form-group">
              <label>评测模式</label>
              <div className="eval-mode-tabs">
                <button
                  type="button"
                  className={`mode-tab ${evalMode === 'benchmark' ? 'active' : ''}`}
                  onClick={() => setEvalMode('benchmark')}
                >
                  🧪 标杆场景
                </button>
                <button
                  type="button"
                  className={`mode-tab ${evalMode === 'offline' ? 'active' : ''}`}
                  onClick={() => setEvalMode('offline')}
                >
                  💾 本地缓存
                </button>
                <button
                  type="button"
                  className={`mode-tab ${evalMode === 'live' ? 'active' : ''}`}
                  onClick={() => setEvalMode('live')}
                >
                  ⚡ 实时链路
                </button>
              </div>
            </div>

            {/* 标杆用例下拉 */}
            {evalMode === 'benchmark' && (
              <div className="eval-form-group">
                <label>标杆回归场景</label>
                <select
                  value={benchmarkCase}
                  onChange={(e) => setBenchmarkCase(e.target.value)}
                  className="eval-select"
                >
                  <option value="local_cache">🌟 本地实盘复现 (多达标标的高动能)</option>
                  <option value="bear_defensive">🛡️ 弱势震荡防守场景 (严查空仓纪律)</option>
                </select>
              </div>
            )}

            {/* 主题选择 (live 模式生效) */}
            {evalMode === 'live' && (
              <div className="eval-form-group">
                <label>选股分析主题/板块</label>
                <input
                  type="text"
                  placeholder="留空为全市场，或输入 如: 人工智能、低空经济"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  className="eval-input"
                />
                <div className="eval-quick-topics">
                  {['全市场', '低空经济', '人工智能', '新能源'].map((t) => (
                    <button
                      key={t}
                      type="button"
                      className="quick-topic-chip"
                      onClick={() => setTopic(t === '全市场' ? '' : t)}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* 大模型裁判开关 */}
            <div className="eval-toggle-group">
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={useLlmJudge}
                  onChange={(e) => setUseLlmJudge(e.target.checked)}
                />
                <span className="toggle-slider"></span>
                <span className="toggle-text">启用 LLM 投研专家裁判 (深度语义打分)</span>
              </label>
              <p className="eval-hint">
                {useLlmJudge
                  ? '融合评分机制：60% 确定性规则体检 + 40% 资深量化基金操盘专家语义深度评审'
                  : '极速纯规则体检：100% 规则指标核验，0 成本秒级出分'}
              </p>
            </div>

            {/* 启动按钮 */}
            <button
              type="button"
              className={`eval-start-btn ${isRunning ? 'running' : ''}`}
              onClick={handleStartEvaluation}
              disabled={isRunning}
            >
              {isRunning ? (
                <>
                  <span className="eval-spinner"></span>
                  正在全链路插桩评测中...
                </>
              ) : (
                '🚀 即刻启动 Agent 评测'
              )}
            </button>

            {errorMessage && (
              <div className="eval-error-alert">
                <span>⚠️ {errorMessage}</span>
              </div>
            )}
          </div>

          {/* 2. 历史评测报告列表 */}
          <div className="eval-card history-card">
            <div className="eval-card-header">
              <span className="card-badge">ARCHIVE</span>
              <h3>📋 历史评测报告 ({historyReports.length})</h3>
            </div>
            <div className="history-list">
              {historyReports.length === 0 ? (
                <div className="history-empty">暂无历史评测记录，请点击上方启动评测</div>
              ) : (
                historyReports.map((item) => (
                  <div
                    key={item.eval_id}
                    className={`history-item ${selectedReportId === item.eval_id ? 'active' : ''}`}
                    onClick={() => loadReportDetail(item)}
                  >
                    <div className="history-item-top">
                      <span className="history-topic">{item.target_topic || '全市场'}</span>
                      <span
                        className="history-score-chip"
                        style={{ color: getScoreColor(item.total_score || 0) }}
                      >
                        {item.total_score != null ? `${Number(item.total_score).toFixed(1)}分` : '--'}
                      </span>
                    </div>
                    <div className="history-item-meta">
                      <span>{item.evaluation_time || ''}</span>
                      <span className="history-grade">{item.total_grade || ''}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </aside>

        {/* 右侧评测结果与诊断大盘 */}
        <main className="eval-content-area">
          {isRunning ? (
            <div className="eval-loading-box">
              <div className="eval-loading-spinner"></div>
              <h3>🧠 选股 Agent 评测引擎全力运行中</h3>
              <p>正在调度各中间步骤插桩监听，并执行 28 项量化逻辑体检与大模型专家审阅...</p>
            </div>
          ) : !currentResult ? (
            <div className="eval-placeholder-box">
              <div className="placeholder-icon">📊</div>
              <h3>尚未选择或运行评测</h3>
              <p>请点击左侧「🚀 即刻启动 Agent 评测」按钮，或从历史列表中挑选一份报告进行深度审阅。</p>
            </div>
          ) : (
            <div className="eval-report-view">
              {/* 核心总分面板 */}
              <div className="eval-score-banner">
                <div className="score-main-card">
                  <div className="score-ring-wrap">
                    <div
                      className="score-number"
                      style={{ color: getScoreColor(currentResult.total_score) }}
                    >
                      {currentResult.total_score != null ? currentResult.total_score.toFixed(1) : '--'}
                    </div>
                    <div className="score-subtext">综合评测总分 (满分 100)</div>
                  </div>
                  <div className="grade-badge-wrap">
                    <span
                      className="grade-badge"
                      style={{
                        borderColor: getScoreColor(currentResult.total_score),
                        color: getScoreColor(currentResult.total_score),
                      }}
                    >
                      🏆 评级：{currentResult.total_grade}
                    </span>
                  </div>
                </div>

                <div className="score-meta-grid">
                  <div className="meta-card">
                    <div className="meta-label">确定性规则得分</div>
                    <div className="meta-val" style={{ color: '#38bdf8' }}>
                      {currentResult.rule_score != null ? `${currentResult.rule_score.toFixed(1)} 分` : '--'}
                    </div>
                    <div className="meta-tip">28项合规及战法数学体检 (权重 60%)</div>
                  </div>
                  <div className="meta-card">
                    <div className="meta-label">LLM 专家裁判评分</div>
                    <div className="meta-val" style={{ color: '#c084fc' }}>
                      {currentResult.llm_judge_score != null
                        ? `${currentResult.llm_judge_score.toFixed(1)} 分`
                        : '未开启/离线'}
                    </div>
                    <div className="meta-tip">资深量化操盘视角深度语义 (权重 40%)</div>
                  </div>
                  <div className="meta-card">
                    <div className="meta-label">全流程执行耗时</div>
                    <div className="meta-val" style={{ color: '#94a3b8' }}>
                      {currentResult.execution_duration != null ? `${currentResult.execution_duration.toFixed(1)}s` : '--'}
                    </div>
                    <div className="meta-tip">拓扑 6 节点完整流转时间</div>
                  </div>
                  <div className="meta-card">
                    <div className="meta-label">终审选拔龙头标的</div>
                    <div className="meta-val" style={{ color: '#10b981' }}>
                      {currentResult.trace_summary?.top_stock || '无/空仓防守'}
                    </div>
                    <div className="meta-tip">综合排名第一推荐标的</div>
                  </div>
                </div>
              </div>

              {/* 资深量化投研专家裁判总评 (如有) */}
              {currentResult.llm_critique && (
                <div className="eval-critique-box">
                  <div className="critique-header">
                    <span className="critique-badge">AI JUDGE</span>
                    <strong>🤖 资深量化投研专家裁判深度总评</strong>
                  </div>
                  <p className="critique-content">{currentResult.llm_critique}</p>
                </div>
              )}

              {/* 一、五大核心评测维度 */}
              <div className="eval-section">
                <div className="section-title">
                  <span className="section-dot"></span>
                  <h3>一、📈 五大评测维度量化雷达</h3>
                </div>
                <div className="dim-cards-grid">
                  {currentResult.dimension_scores &&
                    Object.values(currentResult.dimension_scores).map((dim) => {
                      const pct = dim.percentage || 0
                      const color = getScoreColor(pct)
                      return (
                        <div key={dim.dimension} className="dim-progress-card">
                          <div className="dim-progress-header">
                            <span className="dim-card-name">{dim.dimension_name}</span>
                            <span className="dim-card-score" style={{ color }}>
                              {dim.score.toFixed(1)} / {dim.max_score.toFixed(1)} ({pct.toFixed(0)}%)
                            </span>
                          </div>
                          <div className="dim-progress-track">
                            <div
                              className="dim-progress-bar"
                              style={{ width: `${pct}%`, backgroundColor: color }}
                            ></div>
                          </div>
                          <div className="dim-card-strengths">
                            {dim.strengths && dim.strengths.length > 0
                              ? dim.strengths.slice(0, 2).map((st, i) => (
                                  <div key={i} className="dim-tag-item">
                                    ✔ {st}
                                  </div>
                                ))
                              : '执行平稳规范'}
                          </div>
                        </div>
                      )
                    })}
                </div>
              </div>

              {/* 二、各中间执行步骤逐节点体检 (Node 1 - Node 6) */}
              <div className="eval-section">
                <div className="section-title">
                  <span className="section-dot"></span>
                  <h3>二、🔍 Agent 中间执行步骤逐节点深度体检 (Node 1 - Node 6)</h3>
                </div>
                <div className="step-diagnostics-list">
                  {currentResult.step_diagnostics &&
                    currentResult.step_diagnostics.map((step) => {
                      const isExpanded = activeStepTab === step.step_id
                      const stepColor = getScoreColor(step.score)
                      return (
                        <div
                          key={step.step_id}
                          className={`step-diag-card ${isExpanded ? 'expanded' : ''}`}
                        >
                          <div
                            className="step-diag-header"
                            onClick={() =>
                              setActiveStepTab(isExpanded ? null : step.step_id)
                            }
                          >
                            <div className="step-diag-left">
                              <span className="step-code-badge">{step.step_id.toUpperCase()}</span>
                              <strong className="step-title-text">{step.step_name}</strong>
                            </div>
                            <div className="step-diag-right">
                              <span className="step-duration">⏱️ {step.duration_seconds.toFixed(1)}s</span>
                              <span
                                className="step-score-badge"
                                style={{ borderColor: stepColor, color: stepColor }}
                              >
                                {step.score.toFixed(1)}分 ({step.grade})
                              </span>
                              <span className="step-expand-icon">{isExpanded ? '▲' : '▼'}</span>
                            </div>
                          </div>

                          {/* 展开内容 */}
                          {isExpanded && (
                            <div className="step-diag-body">
                              {step.passed_checks && step.passed_checks.length > 0 && (
                                <div className="step-check-block passed-block">
                                  <div className="check-block-title">✅ 达标核验项 ({step.passed_checks.length})</div>
                                  <ul>
                                    {step.passed_checks.map((p, idx) => (
                                      <li key={idx}>{p}</li>
                                    ))}
                                  </ul>
                                </div>
                              )}

                              {step.failed_checks && step.failed_checks.length > 0 && (
                                <div className="step-check-block failed-block">
                                  <div className="check-block-title">❌ 异常或扣分项 ({step.failed_checks.length})</div>
                                  <ul>
                                    {step.failed_checks.map((f, idx) => (
                                      <li key={idx}>{f}</li>
                                    ))}
                                  </ul>
                                </div>
                              )}

                              {step.key_findings && step.key_findings.length > 0 && (
                                <div className="step-check-block findings-block">
                                  <div className="check-block-title">📌 关键产物特征</div>
                                  <ul>
                                    {step.key_findings.map((k, idx) => (
                                      <li key={idx}>{k}</li>
                                    ))}
                                  </ul>
                                </div>
                              )}

                              {step.raw_report && (
                                <div className="step-check-block report-full-block">
                                  <div className="check-block-title">
                                    📑 节点交付技术研报全文 ({step.raw_report.length} 字)
                                  </div>
                                  <pre className="step-raw-report-pre">{step.raw_report}</pre>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      )
                    })}
                </div>
              </div>

              {/* 三、洞察与优化建议 */}
              <div className="eval-section">
                <div className="section-title">
                  <span className="section-dot"></span>
                  <h3>三、🛠️ 策略诊断亮点与优化路线图</h3>
                </div>
                <div className="insights-tri-grid">
                  <div className="insight-column strengths-col">
                    <h4>✨ 核心优势与战法亮点</h4>
                    <ul>
                      {currentResult.strengths && currentResult.strengths.length > 0 ? (
                        currentResult.strengths.map((s, idx) => <li key={idx}>{s}</li>)
                      ) : (
                        <li>全链路规范执行</li>
                      )}
                    </ul>
                  </div>

                  <div className="insight-column weaknesses-col">
                    <h4>⚠️ 薄弱环节与风险提示</h4>
                    <ul>
                      {currentResult.weaknesses && currentResult.weaknesses.length > 0 ? (
                        currentResult.weaknesses.map((w, idx) => <li key={idx}>{w}</li>)
                      ) : (
                        <li>未发现显著阻断性缺陷</li>
                      )}
                    </ul>
                  </div>

                  <div className="insight-column recommendations-col">
                    <h4>💡 建设性优化改进建议</h4>
                    <ul>
                      {currentResult.recommendations && currentResult.recommendations.length > 0 ? (
                        currentResult.recommendations.map((r, idx) => <li key={idx}>{r}</li>)
                      ) : (
                        <li>建议强化盘口大单回踩承接核验</li>
                      )}
                    </ul>
                  </div>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
