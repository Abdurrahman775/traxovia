import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useBranding } from '../hooks/useBranding'
import localLogo from '../logo.webp'

const HERO = 'https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=1600&q=80&auto=format&fit=crop'
const G    = '#d4a853'
const TX3  = '#445570'
const INPUT_STYLE: React.CSSProperties = { background: '#0d1117', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, color: '#dde4f0', fontSize: 14, padding: '10px 12px', width: '100%', outline: 'none', boxSizing: 'border-box' }

export default function Register() {
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
      await api.post('/auth/register', { email, password })
      const res = await api.post('/auth/login', { email, password })
      localStorage.setItem('access_token', res.data.access_token)
      navigate('/dashboard')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#05080f', position: 'relative', overflow: 'hidden' }}>
      <div style={{ position: 'absolute', inset: 0, backgroundImage: `url(${HERO})`, backgroundSize: 'cover', backgroundPosition: 'center', opacity: 0.07 }} />
      <div style={{ position: 'absolute', inset: 0, background: 'radial-gradient(ellipse 70% 50% at 50% 0%, rgba(212,168,83,0.09) 0%, transparent 65%)' }} />

      <div style={{ background: '#0a0e19', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 20, padding: 32, width: '100%', maxWidth: 380, position: 'relative', zIndex: 1 }}>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 28 }}>
          <img src={app_logo_url} alt="logo" style={{ width: 40, height: 40, borderRadius: 10, objectFit: 'contain', flexShrink: 0 }} onError={e => { (e.currentTarget as HTMLImageElement).src = localLogo }} />
          <div>
            <div style={{ fontWeight: 800, fontSize: 20, color: G, fontFamily: 'Figtree,sans-serif' }}>{app_name}</div>
            <div style={{ fontSize: 11, fontFamily: 'IBM Plex Mono,monospace', color: TX3 }}>Create your account</div>
          </div>
        </div>

        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div>
            <label style={{ fontSize: 10, fontFamily: 'IBM Plex Mono,monospace', letterSpacing: 3, textTransform: 'uppercase', color: TX3, display: 'block', marginBottom: 6 }}>Email</label>
            <input value={email} onChange={e => setEmail(e.target.value)} type="email" required autoFocus style={INPUT_STYLE} />
          </div>

          <div>
            <label style={{ fontSize: 10, fontFamily: 'IBM Plex Mono,monospace', letterSpacing: 3, textTransform: 'uppercase', color: TX3, display: 'block', marginBottom: 6 }}>Password</label>
            <div style={{ position: 'relative' }}>
              <input value={password} onChange={e => setPassword(e.target.value)} type={show ? 'text' : 'password'} required minLength={8} style={{ ...INPUT_STYLE, paddingRight: 40 }} />
              <button type="button" onClick={() => setShow(v => !v)} tabIndex={-1} style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, color: TX3 }}>
                {show ? '🙈' : '👁'}
              </button>
            </div>
            <p style={{ fontSize: 10, fontFamily: 'IBM Plex Mono,monospace', color: TX3, marginTop: 4 }}>Minimum 8 characters</p>
          </div>

          {error && (
            <div style={{ fontSize: 12, fontFamily: 'IBM Plex Mono,monospace', padding: '8px 12px', borderRadius: 8, background: 'rgba(232,84,79,0.08)', color: '#e8544f', border: '1px solid rgba(232,84,79,0.2)' }}>
              ✗ {error}
            </div>
          )}

          <button type="submit" disabled={loading} style={{ background: G, color: '#000', border: 'none', borderRadius: 10, padding: '11px 0', fontFamily: 'IBM Plex Mono,monospace', fontWeight: 700, fontSize: 13, letterSpacing: 2, cursor: 'pointer', opacity: loading ? 0.6 : 1 }}>
            {loading ? 'CREATING…' : 'CREATE ACCOUNT'}
          </button>
        </form>

        <div style={{ marginTop: 20, textAlign: 'center', fontSize: 12, fontFamily: 'IBM Plex Mono,monospace', color: TX3 }}>
          Have an account?{' '}
          <a href="/login" style={{ color: G, textDecoration: 'none' }}>Sign in</a>
        </div>
      </div>
    </div>
  )
}
