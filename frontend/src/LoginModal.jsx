import React, { useState, useEffect } from 'react'
import { setToken } from './auth.js'

export default function LoginModal({ isOpen, onLoginSuccess }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [captchaCode, setCaptchaCode] = useState('')
  const [captchaId, setCaptchaId] = useState('')
  const [captchaImg, setCaptchaImg] = useState('')
  const [isLoadingCaptcha, setIsLoadingCaptcha] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  // 刷新验证码
  const fetchCaptcha = async () => {
    setIsLoadingCaptcha(true)
    setErrorMsg('')
    try {
      // 兼容开发环境 5173/3000 端口跨域与生产环境相对路径
      let url = '/api/auth/captcha'
      if (typeof window !== 'undefined' && (window.location.port === '5173' || window.location.port === '3000')) {
        const host = window.location.hostname === 'localhost' ? '127.0.0.1' : (window.location.hostname || '127.0.0.1')
        url = `http://${host}:8000/api/auth/captcha`
      }

      const res = await fetch(url)
      if (res.ok) {
        const json = await res.json()
        if (json.success && json.data) {
          setCaptchaId(json.data.captcha_id)
          setCaptchaImg(json.data.image)
          setCaptchaCode('')
        }
      }
    } catch (err) {
      console.warn('获取验证码失败:', err)
      setErrorMsg('网络异常，无法获取验证码，请检查后端运行状态')
    } finally {
      setIsLoadingCaptcha(false)
    }
  }

  useEffect(() => {
    if (isOpen) {
      fetchCaptcha()
    }
  }, [isOpen])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!username.trim()) {
      setErrorMsg('请输入管理员用户名')
      return
    }
    if (!password) {
      setErrorMsg('请输入访问密码')
      return
    }
    if (!captchaCode.trim()) {
      setErrorMsg('请输入4位图形验证码')
      return
    }

    setIsSubmitting(true)
    setErrorMsg('')

    try {
      let url = '/api/auth/login'
      if (typeof window !== 'undefined' && (window.location.port === '5173' || window.location.port === '3000')) {
        const host = window.location.hostname === 'localhost' ? '127.0.0.1' : (window.location.hostname || '127.0.0.1')
        url = `http://${host}:8000/api/auth/login`
      }

      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username: username.trim(),
          password: password,
          captcha_id: captchaId,
          captcha_code: captchaCode.trim(),
        }),
      })

      const json = await res.json()

      if (res.ok && json.success) {
        setToken(json.token, json.user || { username: username.trim() })
        if (onLoginSuccess) {
          onLoginSuccess(json.user || { username: username.trim() })
        }
      } else {
        setErrorMsg(json.error || '登录失败，请检查账号密码与验证码')
        // 失败立即刷新验证码防重放
        fetchCaptcha()
      }
    } catch (err) {
      setErrorMsg('登录请求发生网络异常，请稍后重试')
      fetchCaptcha()
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!isOpen) return null

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      zIndex: 99999,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: 'rgba(3, 7, 18, 0.85)',
      backdropFilter: 'blur(16px)',
      padding: '16px',
    }}>
      <div style={{
        width: '100%',
        maxWidth: '430px',
        backgroundColor: '#0f172a',
        border: '1px solid rgba(56, 189, 248, 0.25)',
        borderRadius: '20px',
        boxShadow: '0 25px 60px -15px rgba(0, 0, 0, 0.7), 0 0 40px rgba(56, 189, 248, 0.15)',
        overflow: 'hidden',
        color: '#f8fafc',
        fontFamily: 'system-ui, -apple-system, sans-serif',
      }}>
        {/* 顶部发光条与标题 */}
        <div style={{
          background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.9) 100%)',
          padding: '28px 24px 20px',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          textAlign: 'center',
          position: 'relative',
        }}>
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            backgroundColor: 'rgba(56, 189, 248, 0.12)',
            border: '1px solid rgba(56, 189, 248, 0.3)',
            borderRadius: '9999px',
            padding: '4px 14px',
            fontSize: '12px',
            color: '#38bdf8',
            fontWeight: 600,
            marginBottom: '12px',
          }}>
            <span style={{ fontSize: '14px' }}>🛡️</span> 安全审计认证中心
          </div>
          <h2 style={{
            margin: '0 0 6px 0',
            fontSize: '22px',
            fontWeight: 700,
            letterSpacing: '0.5px',
            background: 'linear-gradient(to right, #ffffff, #93c5fd)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}>
            LangGraph 智能投研中台
          </h2>
          <p style={{
            margin: 0,
            fontSize: '13px',
            color: '#94a3b8',
          }}>
            多智能体量化选股 · 研报财报知识库 · 全端点守护
          </p>
        </div>

        {/* 表单内容 */}
        <form onSubmit={handleSubmit} style={{ padding: '24px 28px 28px' }}>
          {errorMsg && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              backgroundColor: 'rgba(239, 68, 68, 0.12)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              borderRadius: '8px',
              padding: '10px 14px',
              marginBottom: '18px',
              fontSize: '13px',
              color: '#f87171',
            }}>
              <span>⚠️</span>
              <span style={{ flex: 1 }}>{errorMsg}</span>
            </div>
          )}

          {/* 用户名 */}
          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, color: '#cbd5e1', marginBottom: '6px' }}>
              管理员账号
            </label>
            <div style={{ position: 'relative' }}>
              <span style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#64748b', fontSize: '15px' }}>
                👤
              </span>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="请输入登录用户名"
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  backgroundColor: 'rgba(30, 41, 59, 0.6)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  borderRadius: '10px',
                  padding: '10px 14px 10px 38px',
                  color: '#fff',
                  fontSize: '14px',
                  outline: 'none',
                  transition: 'border-color 0.2s',
                }}
                onFocus={(e) => e.target.style.borderColor = '#38bdf8'}
                onBlur={(e) => e.target.style.borderColor = 'rgba(255, 255, 255, 0.12)'}
              />
            </div>
          </div>

          {/* 密码 */}
          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, color: '#cbd5e1', marginBottom: '6px' }}>
              访问密码
            </label>
            <div style={{ position: 'relative' }}>
              <span style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#64748b', fontSize: '15px' }}>
                🔒
              </span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="请输入访问密码"
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  backgroundColor: 'rgba(30, 41, 59, 0.6)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  borderRadius: '10px',
                  padding: '10px 14px 10px 38px',
                  color: '#fff',
                  fontSize: '14px',
                  outline: 'none',
                  transition: 'border-color 0.2s',
                }}
                onFocus={(e) => e.target.style.borderColor = '#38bdf8'}
                onBlur={(e) => e.target.style.borderColor = 'rgba(255, 255, 255, 0.12)'}
              />
            </div>
          </div>

          {/* 验证码 */}
          <div style={{ marginBottom: '22px' }}>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, color: '#cbd5e1', marginBottom: '6px' }}>
              安全图形验证码
            </label>
            <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
              <div style={{ position: 'relative', flex: 1 }}>
                <span style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#64748b', fontSize: '15px' }}>
                  🛡️
                </span>
                <input
                  type="text"
                  maxLength={6}
                  value={captchaCode}
                  onChange={(e) => setCaptchaCode(e.target.value.toUpperCase())}
                  placeholder="4位字符"
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    backgroundColor: 'rgba(30, 41, 59, 0.6)',
                    border: '1px solid rgba(255, 255, 255, 0.12)',
                    borderRadius: '10px',
                    padding: '10px 14px 10px 38px',
                    color: '#38bdf8',
                    fontSize: '15px',
                    fontWeight: 700,
                    letterSpacing: '2px',
                    textTransform: 'uppercase',
                    outline: 'none',
                  }}
                  onFocus={(e) => e.target.style.borderColor = '#38bdf8'}
                  onBlur={(e) => e.target.style.borderColor = 'rgba(255, 255, 255, 0.12)'}
                />
              </div>

              {/* 验证码图形预览 */}
              <div
                onClick={fetchCaptcha}
                title="点击刷新验证码"
                style={{
                  height: '42px',
                  width: '124px',
                  backgroundColor: '#020617',
                  border: '1px solid rgba(56, 189, 248, 0.3)',
                  borderRadius: '8px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: 'pointer',
                  overflow: 'hidden',
                  userSelect: 'none',
                  position: 'relative',
                }}
              >
                {isLoadingCaptcha ? (
                  <span style={{ fontSize: '12px', color: '#64748b' }}>加载中...</span>
                ) : captchaImg ? (
                  <img
                    src={captchaImg}
                    alt="验证码"
                    style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                  />
                ) : (
                  <span style={{ fontSize: '12px', color: '#38bdf8' }}>点击获取</span>
                )}
              </div>

              <button
                type="button"
                onClick={fetchCaptcha}
                title="刷新验证码"
                style={{
                  backgroundColor: 'transparent',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  borderRadius: '8px',
                  color: '#94a3b8',
                  padding: '10px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s',
                }}
              >
                🔄
              </button>
            </div>
          </div>

          {/* 登录按钮 */}
          <button
            type="submit"
            disabled={isSubmitting}
            style={{
              width: '100%',
              padding: '12px',
              backgroundColor: isSubmitting ? '#0284c7' : '#0ea5e9',
              background: 'linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%)',
              border: 'none',
              borderRadius: '10px',
              color: '#ffffff',
              fontSize: '15px',
              fontWeight: 700,
              cursor: isSubmitting ? 'not-allowed' : 'pointer',
              boxShadow: '0 4px 14px rgba(14, 165, 233, 0.35)',
              transition: 'opacity 0.2s, transform 0.1s',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
            }}
          >
            {isSubmitting ? '正在验证身份...' : '🚀 立即登录投研系统'}
          </button>

          {/* 底部提示 */}
          <div style={{
            marginTop: '18px',
            paddingTop: '14px',
            borderTop: '1px solid rgba(255, 255, 255, 0.08)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            fontSize: '12px',
            color: '#64748b',
          }}>
            <span style={{ color: '#22c55e', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#22c55e', display: 'inline-block' }}></span>
              全端点 API 鉴权与防暴力破解守护中
            </span>
          </div>
        </form>
      </div>
    </div>
  )
}
