import { Link } from 'react-router-dom'
import localLogo from '../logo.webp'
import { useBranding } from '../hooks/useBranding'

export default function Unauthorized() {
  const { app_name, app_logo_url } = useBranding()

  return (
    <div className="min-h-screen flex items-center justify-center px-4"
      style={{ background: 'var(--color-bg)' }}>
      <div className="w-full max-w-md text-center">

        <div className="font-mono mb-6" style={{ color: 'var(--color-tx3)', fontSize: 11, letterSpacing: 2 }}>
          ERR_UNAUTHORIZED
        </div>

        <div className="font-head font-bold select-none"
          style={{ fontSize: 'clamp(80px, 18vw, 120px)', lineHeight: 1, color: 'transparent',
            backgroundImage: 'linear-gradient(135deg, #8b5cf6 0%, #4f8ef7 100%)',
            WebkitBackgroundClip: 'text', backgroundClip: 'text' }}>
          401
        </div>

        <div className="rounded-2xl p-7 mt-6"
          style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>

          <div className="flex items-center justify-center gap-3 mb-5">
            <img src={app_logo_url} alt="logo" className="w-8 h-8 rounded-lg object-contain"
              onError={e => { (e.currentTarget as HTMLImageElement).src = localLogo }} />
            <span className="font-head font-bold text-base" style={{ color: 'var(--color-cy)' }}>
              {app_name}
            </span>
          </div>

          <div className="font-mono text-[10px] tracking-[3px] uppercase mb-2"
            style={{ color: 'var(--color-tx3)' }}>
            Authentication Required
          </div>
          <p className="text-sm" style={{ color: 'var(--color-tx2)' }}>
            You need to be signed in to access this page.
          </p>
          <p className="text-xs mt-2" style={{ color: 'var(--color-tx3)' }}>
            Your session may have expired. Sign in again to continue.
          </p>

          <div className="flex gap-3 mt-6 justify-center">
            <Link to="/login"
              className="font-mono text-xs px-5 py-2 rounded-lg"
              style={{ background: 'linear-gradient(135deg,#8b5cf6,#4f8ef7)', color: '#fff', fontWeight: 700 }}>
              Sign In
            </Link>
            <Link to="/register"
              className="font-mono text-xs px-4 py-2 rounded-lg"
              style={{ background: 'var(--color-s3)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}>
              Create Account
            </Link>
          </div>
        </div>

        <p className="font-mono text-[10px] mt-5" style={{ color: 'var(--color-tx3)' }}>
          TRAXOVIA AI · SECURE ACCESS
        </p>
      </div>
    </div>
  )
}
