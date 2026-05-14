import axios from 'axios'

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000' })

api.interceptors.request.use(cfg => {
  const token = localStorage.getItem('access_token')
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
      localStorage.getItem('access_token')
    ) {
      redirecting = true
      localStorage.removeItem('access_token')
      // Notify the React app via event so it navigates with React Router
      // (avoids hard page reload that causes the "disappearing" flash)
      window.dispatchEvent(new CustomEvent('auth:logout'))
      // Reset flag after a tick so subsequent 401s after re-login are caught
      setTimeout(() => { redirecting = false }, 100)
    }
    return Promise.reject(err)
  }
)

export default api
