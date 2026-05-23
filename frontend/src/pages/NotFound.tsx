import { Link, useLocation } from 'react-router-dom'
import { getToken } from '../api/client'

export default function NotFound() {
  const { pathname } = useLocation()
  const authed = !!getToken()

  return (
    <div className="min-h-screen flex items-center justify-center px-4"
      style={{ background: 'var(--color-bg)' }}>
      <div className="w-full max-w-md text-center">

        {/* Glitch code block */}
        <div className="font-mono mb-6" style={{ color: 'var(--color-tx3)', fontSize: 11, letterSpacing: 2 }}>
          ERR_ROUTE_NOT_FOUND
        </div>

        {/* Big 404 */}
        <div className="font-head font-bold select-none"
          style={{ fontSize: 'clamp(80px, 18vw, 120px)', lineHeight: 1, color: 'transparent',
            backgroundImage: 'linear-gradient(135deg, #00e5cc 0%, #4f8ef7 100%)',
            WebkitBackgroundClip: 'text', backgroundClip: 'text' }}>
          404
        </div>

        {/* Card */}
        <div className="rounded-2xl p-7 mt-6"
          style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>

          <div className="font-mono text-[10px] tracking-[3px] uppercase mb-2"
            style={{ color: 'var(--color-tx3)' }}>
            Page Not Found
          </div>
          <p className="text-sm mb-1" style={{ color: 'var(--color-tx2)' }}>
            The page <code className="font-mono text-xs px-1.5 py-0.5 rounded"
              style={{ background: 'var(--color-s3)', color: 'var(--color-tx)' }}>
              {pathname}
            </code> does not exist.
          </p>
          <p className="text-xs mt-2" style={{ color: 'var(--color-tx3)' }}>
            It may have been moved, deleted, or you followed a bad link.
          </p>

          <div className="flex gap-3 mt-6 justify-center">
            {authed ? (
              <>
                <Link to="/dashboard"
                  className="font-mono text-xs px-4 py-2 rounded-lg transition-all"
                  style={{ background: 'linear-gradient(135deg,#00e5cc,#4f8ef7)', color: '#05080f', fontWeight: 700 }}>
                  ← Dashboard
                </Link>
                <Link to="/signals"
                  className="font-mono text-xs px-4 py-2 rounded-lg transition-all"
                  style={{ background: 'var(--color-s3)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}>
                  Signals
                </Link>
              </>
            ) : (
              <Link to="/login"
                className="font-mono text-xs px-5 py-2 rounded-lg"
                style={{ background: 'linear-gradient(135deg,#00e5cc,#4f8ef7)', color: '#05080f', fontWeight: 700 }}>
                ← Back to Login
              </Link>
            )}
          </div>
        </div>

        <p className="font-mono text-[10px] mt-5" style={{ color: 'var(--color-tx3)' }}>
          TRAXOVIA AI · STATUS OK
        </p>
      </div>
    </div>
  )
}
