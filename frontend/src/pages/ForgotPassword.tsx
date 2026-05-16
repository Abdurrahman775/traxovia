import { useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import { useBranding } from '../hooks/useBranding'
import bgImage from '../bg-image.webp'
import localLogo from '../logo.webp'

export default function ForgotPassword() {
  const [email,   setEmail]   = useState('')
  const [sent,    setSent]    = useState(false)
  const [error,   setError]   = useState('')
  const [loading, setLoading] = useState(false)
  const { app_name, app_logo_url } = useBranding()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await api.post('/auth/forgot-password', { email })
      setSent(true)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Something went wrong. Try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ backgroundImage: `url(${bgImage})`, backgroundSize: 'cover', backgroundPosition: 'center', position: 'relative' }}>
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.62)', backdropFilter: 'blur(2px)' }} />
      <div className="w-full max-w-sm rounded-2xl p-8" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)', position: 'relative', zIndex: 1 }}>

        <div className="mb-7 flex items-center gap-3">
          <img src={app_logo_url} alt="logo" className="w-10 h-10 rounded-xl object-contain shrink-0" onError={e => { (e.currentTarget as HTMLImageElement).src = localLogo }} />
          <div>
            <div className="font-head font-bold text-xl" style={{ color: 'var(--color-cy)' }}>{app_name}</div>
            <div className="text-xs font-mono" style={{ color: 'var(--color-tx3)' }}>Reset your password</div>
          </div>
        </div>

        {sent ? (
          <div className="space-y-4">
            <div className="px-4 py-4 rounded-xl text-sm font-mono text-center"
              style={{ background: 'rgba(0,229,204,0.08)', color: 'var(--color-cy)', border: '1px solid rgba(0,229,204,0.2)' }}>
              ✓ Check your email for a reset link.<br />
              <span style={{ color: 'var(--color-tx3)', fontSize: '11px' }}>It expires in 15 minutes.</span>
            </div>
            <Link to="/login"
              className="block w-full py-2.5 rounded-xl font-mono font-bold text-sm tracking-widest text-center transition-colors"
              style={{ background: 'var(--color-s3)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}>
              BACK TO LOGIN
            </Link>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <p className="text-xs font-mono" style={{ color: 'var(--color-tx3)' }}>
              Enter your email and we'll send you a link to reset your password.
            </p>
            <div>
              <label className="text-[10px] font-mono tracking-widest uppercase" style={{ color: 'var(--color-tx3)' }}>
                Email
              </label>
              <input
                value={email} onChange={e => setEmail(e.target.value)}
                type="email" required autoFocus
                className="w-full mt-1 px-3 py-2.5 bg-s3 border border-s3 rounded-lg text-sm text-tx focus:outline-none focus:border-cy/60 transition-colors"
              />
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
              {loading ? 'SENDING…' : 'SEND RESET LINK'}
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
