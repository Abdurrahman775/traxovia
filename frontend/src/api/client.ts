import axios from 'axios'

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000' })

export function getToken() {
  return localStorage.getItem('access_token') || sessionStorage.getItem('access_token')
}

export function setToken(token: string, remember: boolean) {
  if (remember) {
    localStorage.setItem('access_token', token)
    sessionStorage.removeItem('access_token')
  } else {
    sessionStorage.setItem('access_token', token)
    localStorage.removeItem('access_token')
  }
}

export function clearToken() {
  localStorage.removeItem('access_token')
  sessionStorage.removeItem('access_token')
}

api.interceptors.request.use(cfg => {
  const token = getToken()
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

let redirecting = false

api.interceptors.response.use(
  r => r,
  err => {
    if (
      err.response?.status === 401 &&
      !redirecting &&
      !window.location.pathname.startsWith('/login') &&
      !window.location.pathname.startsWith('/register') &&
      !window.location.pathname.startsWith('/forgot-password') &&
      !window.location.pathname.startsWith('/reset-password') &&
      getToken()
    ) {
      redirecting = true
      clearToken()
      window.dispatchEvent(new CustomEvent('auth:logout'))
      setTimeout(() => { redirecting = false }, 100)
    }
    return Promise.reject(err)
  }
)

export default api
