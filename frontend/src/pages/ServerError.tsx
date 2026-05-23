import { Link, useLocation } from 'react-router-dom'
import { getToken } from '../api/client'

export default function ServerError() {
  const authed = !!getToken()

  return (
    <div className="min-h-screen flex items-center justify-center px-4"
      style={{ background: 'var(--color-bg)' }}>
      <div className="w-full max-w-md text-center">

        <div className="font-mono mb-6" style={{ color: 'var(--color-tx3)', fontSize: 11, letterSpacing: 2 }}>
          ERR_INTERNAL_SERVER
        </div>

        <div className="font-head font-bold select-none"
          style={{ fontSize: 'clamp(80px, 18vw, 120px)', lineHeight: 1, color: 'transparent',
            backgroundImage: 'linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)',
            WebkitBackgroundClip: 'text', backgroundClip: 'text' }}>
          500
        </div>

        <div className="rounded-2xl p-7 mt-6"
          style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>

          <div className="font-mono text-[10px] tracking-[3px] uppercase mb-2"
            style={{ color: 'var(--color-tx3)' }}>
            Server Error
          </div>
          <p className="text-sm mb-1" style={{ color: 'var(--color-tx2)' }}>
            Something went wrong on our end.
          </p>
          <p className="text-xs mt-2" style={{ color: 'var(--color-tx3)' }}>
            Our systems are being monitored. Please try again in a moment — your trades and account data are safe.
          </p>

          {/* Animated status indicator */}
          <div className="flex items-center justify-center gap-2 mt-5 py-2 rounded-lg"
            style={{ background: 'rgba(245,158,11,0.07)', border: '1px solid rgba(245,158,11,0.2)' }}>
            <span className="inline-block w-2 h-2 rounded-full animate-pulse"
              style={{ background: '#f59e0b', boxShadow: '0 0 6px #f59e0b' }} />
            <span className="font-mono text-[10px] tracking-widest" style={{ color: '#f59e0b' }}>
              INVESTIGATING INCIDENT
            </span>
          </div>

          <div className="flex gap-3 mt-6 justify-center">
            <button onClick={() => window.location.reload()}
              className="font-mono text-xs px-4 py-2 rounded-lg transition-all cursor-pointer"
              style={{ background: 'linear-gradient(135deg,#f59e0b,#ef4444)', color: '#fff', fontWeight: 700, border: 'none' }}>
              ↺ Retry
            </button>
            {authed && (
              <Link to="/dashboard"
                className="font-mono text-xs px-4 py-2 rounded-lg"
                style={{ background: 'var(--color-s3)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}>
                ← Dashboard
              </Link>
            )}
          </div>
        </div>

        <p className="font-mono text-[10px] mt-5" style={{ color: 'var(--color-tx3)' }}>
          TRAXOVIA AI · INCIDENT ACTIVE
        </p>
      </div>
    </div>
  )
}
