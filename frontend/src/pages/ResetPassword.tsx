import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import api from '../api/client'
import { useBranding } from '../hooks/useBranding'
import bgImage from '../bg-image.webp'
import localLogo from '../logo.webp'

export default function ResetPassword() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''

  const [password,  setPassword]  = useState('')
  const [confirm,   setConfirm]   = useState('')
  const [showPw,    setShowPw]    = useState(false)
  const [done,      setDone]      = useState(false)
  const [error,     setError]     = useState('')
  const [loading,   setLoading]   = useState(false)
  const { app_name, app_logo_url } = useBranding()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (password !== confirm) { setError('Passwords do not match'); return }
    setLoading(true)
    setError('')
    try {
      await api.post('/auth/reset-password', { token, password })
      setDone(true)
    } catch (err: any) {
      const detail = err.response?.data?.detail
      if (Array.isArray(detail)) {
        setError(detail.map((d: any) => d.msg).join('. '))
      } else {
        setError(detail || 'Reset failed. The link may have expired.')
      }
    } finally {
      setLoading(false)
    }
  }

  const INPUT = "w-full mt-1 px-3 py-2.5 bg-s3 border border-s3 rounded-lg text-sm text-tx focus:outline-none focus:border-cy/60 transition-colors"
  const LABEL = "text-[10px] font-mono tracking-widest uppercase"

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundImage: `url(${bgImage})`, backgroundSize: 'cover', backgroundPosition: 'center', position: 'relative' }}>
        <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.62)', backdropFilter: 'blur(2px)' }} />
        <div className="w-full max-w-sm rounded-2xl p-8 text-center space-y-4" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)', position: 'relative', zIndex: 1 }}>
          <div className="text-sm font-mono" style={{ color: '#e8544f' }}>✗ Invalid reset link</div>
          <Link to="/forgot-password" style={{ color: 'var(--color-cy)' }} className="text-xs font-mono hover:underline">
            Request a new one
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ backgroundImage: `url(${bgImage})`, backgroundSize: 'cover', backgroundPosition: 'center', position: 'relative' }}>
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.62)', backdropFilter: 'blur(2px)' }} />
      <div className="w-full max-w-sm rounded-2xl p-8" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)', position: 'relative', zIndex: 1 }}>

        <div className="mb-7 flex items-center gap-3">
          <img src={app_logo_url} alt="logo" className="w-10 h-10 rounded-xl object-contain shrink-0" onError={e => { (e.currentTarget as HTMLImageElement).src = localLogo }} />
          <div>
            <div className="font-head font-bold text-xl" style={{ color: 'var(--color-cy)' }}>{app_name}</div>
            <div className="text-xs font-mono" style={{ color: 'var(--color-tx3)' }}>Set a new password</div>
          </div>
        </div>

        {done ? (
          <div className="space-y-4">
            <div className="px-4 py-4 rounded-xl text-sm font-mono text-center"
              style={{ background: 'rgba(212,168,83,0.08)', color: 'var(--color-cy)', border: '1px solid rgba(212,168,83,0.2)' }}>
              ✓ Password updated successfully
            </div>
            <Link to="/login"
              className="block w-full py-2.5 rounded-xl font-mono font-bold text-sm tracking-widest text-center"
              style={{ background: '#d4a853', color: '#000', border: 'none' }}>
              SIGN IN
            </Link>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className={LABEL} style={{ color: 'var(--color-tx3)' }}>New password</label>
              <div className="relative mt-1">
                <input
                  value={password} onChange={e => setPassword(e.target.value)}
                  type={showPw ? 'text' : 'password'} required minLength={8}
                  className="w-full px-3 py-2.5 pr-10 bg-s3 border border-s3 rounded-lg text-sm text-tx focus:outline-none focus:border-cy/60 transition-colors"
                />
                <button type="button" onClick={() => setShowPw(v => !v)} tabIndex={-1}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-xs select-none"
                  style={{ color: 'var(--color-tx3)', opacity: 0.7 }}>
                  {showPw ? '🙈' : '👁'}
                </button>
              </div>
              <p className="mt-1 text-[10px] font-mono" style={{ color: 'var(--color-tx3)' }}>
                Min 8 chars, one uppercase, one number
              </p>
            </div>

            <div>
              <label className={LABEL} style={{ color: 'var(--color-tx3)' }}>Confirm password</label>
              <input
                value={confirm} onChange={e => setConfirm(e.target.value)}
                type={showPw ? 'text' : 'password'} required
                className={INPUT}
              />
            </div>

            {error && (
              <div className="text-xs font-mono px-3 py-2 rounded-lg"
                style={{ background: 'rgba(232,84,79,0.08)', color: '#e8544f', border: '1px solid rgba(232,84,79,0.2)' }}>
                ✗ {error}
              </div>
            )}

            <button type="submit" disabled={loading}
              className="w-full py-2.5 rounded-xl font-mono font-bold text-sm tracking-widest transition-colors disabled:opacity-50"
              style={{ background: '#d4a853', color: '#000', border: 'none' }}>
              {loading ? 'UPDATING…' : 'SET NEW PASSWORD'}
            </button>

            <div className="text-center text-xs font-mono" style={{ color: 'var(--color-tx3)' }}>
              <Link to="/login" style={{ color: 'var(--color-cy)' }} className="hover:underline">
                Back to login
              </Link>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
