import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useBranding } from '../hooks/useBranding'
import bgImage from '../bg-image.webp'
import localLogo from '../logo.webp'

export default function Login() {
  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')
  const [show,     setShow]     = useState(false)
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)
  const navigate = useNavigate()
  const { app_name, app_logo_url } = useBranding()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const res = await api.post('/auth/login', { email, password })
      localStorage.setItem('access_token', res.data.access_token)
      navigate('/dashboard')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  const INPUT = "w-full mt-1 px-3 py-2.5 bg-s3 border border-s3 rounded-lg text-sm text-tx focus:outline-none focus:border-cy/60 transition-colors"
  const LABEL = "text-[10px] font-mono tracking-widest uppercase"

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ backgroundImage: `url(${bgImage})`, backgroundSize: 'cover', backgroundPosition: 'center', backgroundRepeat: 'no-repeat', position: 'relative' }}>
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.62)', backdropFilter: 'blur(2px)' }} />
      <div className="w-full max-w-sm rounded-2xl p-8" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)', position: 'relative', zIndex: 1 }}>

        <div className="mb-7 flex items-center gap-3">
          <img src={app_logo_url} alt="logo" className="w-10 h-10 rounded-xl object-contain shrink-0" onError={e => { (e.currentTarget as HTMLImageElement).src = localLogo }} />
          <div>
            <div className="font-head font-bold text-xl" style={{ color: 'var(--color-cy)' }}>{app_name}</div>
            <div className="text-xs font-mono" style={{ color: 'var(--color-tx3)' }}>Sign in to your account</div>
          </div>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className={LABEL} style={{ color: 'var(--color-tx3)' }}>Email</label>
            <input
              value={email} onChange={e => setEmail(e.target.value)}
              type="email" required autoFocus
              className={INPUT}
            />
          </div>

          <div>
            <label className={LABEL} style={{ color: 'var(--color-tx3)' }}>Password</label>
            <div className="relative mt-1">
              <input
                value={password} onChange={e => setPassword(e.target.value)}
                type={show ? 'text' : 'password'} required
                className="w-full px-3 py-2.5 pr-10 bg-s3 border border-s3 rounded-lg text-sm text-tx focus:outline-none focus:border-cy/60 transition-colors"
              />
              <button
                type="button"
                onClick={() => setShow(v => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-xs select-none transition-opacity"
                style={{ color: 'var(--color-tx3)', opacity: 0.7 }}
                tabIndex={-1}
              >
                {show ? '🙈' : '👁'}
              </button>
            </div>
          </div>

          {error && (
            <div className="text-xs font-mono px-3 py-2 rounded-lg"
              style={{ background: 'rgba(255,61,90,0.08)', color: '#ff3d5a', border: '1px solid rgba(255,61,90,0.2)' }}>
              ✗ {error}
            </div>
          )}

          <button type="submit" disabled={loading}
            className="w-full py-2.5 rounded-xl font-mono font-bold text-sm tracking-widest transition-colors disabled:opacity-50"
            style={{ background: '#00e5cc', color: '#000', border: 'none' }}>
            {loading ? 'SIGNING IN…' : 'SIGN IN'}
          </button>
        </form>

        <div className="mt-5 text-center text-xs font-mono" style={{ color: 'var(--color-tx3)' }}>
          No account?{' '}
          <a href="/register" style={{ color: 'var(--color-cy)' }} className="hover:underline">Register</a>
        </div>
      </div>
    </div>
  )
}
