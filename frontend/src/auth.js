/**
 * 前端全局用户鉴权与 Fetch 拦截器服务
 * 1. 自动为所有发往 /api/ 与 /rag/ 的请求携带 Authorization: Bearer <Token>
 * 2. 捕获 401 未授权响应，触发全局 fin_auth_unauthorized 事件唤醒登录弹窗
 */

export const AUTH_TOKEN_KEY = 'fin_auth_token'
export const AUTH_USER_KEY = 'fin_auth_user'

export function getToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY) || ''
}

export function setToken(token, user = null) {
  if (token) {
    localStorage.setItem(AUTH_TOKEN_KEY, token)
  }
  if (user) {
    localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user))
  }
}

export function removeToken() {
  localStorage.removeItem(AUTH_TOKEN_KEY)
  localStorage.removeItem(AUTH_USER_KEY)
}

export function getCurrentUser() {
  try {
    const raw = localStorage.getItem(AUTH_USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch (e) {
    return null
  }
}

let isInterceptorInstalled = false

export function initAuthInterceptor() {
  if (isInterceptorInstalled || typeof window === 'undefined') return
  isInterceptorInstalled = true

  const originalFetch = window.fetch

  window.fetch = async function (input, init = {}) {
    const urlStr = typeof input === 'string' ? input : (input?.url || '')
    const options = { ...init }
    const headers = new Headers(options.headers || (typeof input === 'object' && input?.headers ? input.headers : {}))

    const isApiRequest = urlStr.includes('/api/') || urlStr.includes('/rag/')
    const isPublicAuth = urlStr.includes('/api/auth/login') || urlStr.includes('/api/auth/captcha')

    if (isApiRequest && !isPublicAuth) {
      const token = getToken()
      if (token && !headers.has('Authorization')) {
        headers.set('Authorization', `Bearer ${token}`)
      }
    }

    options.headers = headers

    const response = await originalFetch(input, options)

    // 遇到 401 凭证过期或未授权，自动清除缓存并广播通知
    if (response.status === 401 && !isPublicAuth) {
      removeToken()
      window.dispatchEvent(new CustomEvent('fin_auth_unauthorized'))
    }

    return response
  }
}
