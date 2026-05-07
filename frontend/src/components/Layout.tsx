import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'
import { useAdminUser } from '../hooks/useAdminUser'
import { useTheme } from '../contexts/ThemeContext'

const NAV_GROUPS = [
  {
    label: 'Trading',
    items: [
      { to: '/dashboard', label: 'Dashboard',        icon: '⬛' },
      { to: '/regime',    label: 'Regime Detector',  icon: '◈' },
      { to: '/signals',   label: 'Signals',          icon: '◆' },
      { to: '/trades',    label: 'Trades',           icon: '↯' },
      { to: '/analytics', label: 'Analytics',        icon: '◬' },
    ],
  },
  {
    label: 'Account',
    items: [
      { to: '/profile',   label: 'Profile',   icon: '◉' },
      { to: '/billing',   label: 'Billing',   icon: '◎' },
      { to: '/referral',  label: 'Referral',  icon: '★' },
      { to: '/auditlog',  label: 'Audit Log', icon: '≡' },
      { to: '/settings',  label: 'Settings',  icon: '◇' },
    ],
  },
]

const ADMIN_ITEMS = [
  { to: '/admin',     label: 'Admin Panel',    icon: '●' },
  { to: '/model',     label: 'Model & Retrain', icon: '◉' },
  { to: '/community', label: 'Community',      icon: '⬡' },
  { to: '/bridge',    label: 'Bridge Monitor', icon: '▲' },
]

function Ticker() {
  const { data } = useQuery({
    queryKey: ['prices'],
    queryFn: () => api.get('/prices').then(r => r.data),
    retry: false,
    refetchInterval: (query) => query.state.status === 'error' ? 30_000 : 2_000,
  })
  const pairs = data ? Object.entries(data).slice(0, 5) : []
  return (
    <div className="flex gap-6 text-xs font-mono text-tx2 overflow-hidden">
      {pairs.length === 0
        ? <span style={{ color: 'var(--color-tx2)', opacity: 0.4 }}>— prices unavailable —</span>
        : pairs.map(([pair, price]: [string, unknown]) => (
            <span key={pair}>
              <span className="text-tx2">{pair}</span>{' '}
              <span className="text-cy">{String(price)}</span>
            </span>
          ))
      }
    </div>
  )
}

export default function Layout() {
  const navigate = useNavigate()
  const { isAdmin, email } = useAdminUser()
  const { theme, toggle } = useTheme()
  function logout() {
    localStorage.removeItem('access_token')
    navigate('/login')
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 bg-s1 border-r border-s3 flex flex-col shrink-0">
        <div className="px-5 py-5 border-b border-s3">
          <span className="font-head font-bold text-cy text-lg tracking-wide">TRADING AI</span>
          <span className="text-tx2 text-xs ml-1">V3</span>
        </div>
        <nav className="flex-1 py-4 space-y-0.5 px-2 overflow-y-auto">
          {NAV_GROUPS.map(g => (
            <div key={g.label} className="mb-3">
              <div className="px-3 py-1 text-[9px] font-mono tracking-widest text-tx3 uppercase">{g.label}</div>
              {g.items.map(n => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ` +
                    (isActive ? 'bg-cy/10 text-cy font-medium' : 'text-tx2 hover:text-tx hover:bg-s2')
                  }
                >
                  <span className="text-base w-4 text-center">{n.icon}</span>
                  {n.label}
                </NavLink>
              ))}
            </div>
          ))}
          {isAdmin && (
            <div className="mb-3">
              <div className="px-3 py-1 text-[9px] font-mono tracking-widest text-tx3 uppercase">Admin</div>
              {ADMIN_ITEMS.map(n => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ` +
                    (isActive ? 'bg-cy/10 text-cy font-medium' : 'text-tx2 hover:text-tx hover:bg-s2')
                  }
                >
                  <span className="text-base w-4 text-center">{n.icon}</span>
                  {n.label}
                </NavLink>
              ))}
            </div>
          )}
        </nav>
        <div className="px-4 py-4 border-t border-s3 space-y-2">
          {isAdmin && (
            <div className="flex items-center gap-2 px-3">
              <span className="text-[10px] font-bold uppercase tracking-widest text-cy border border-cy/30 bg-cy/10 rounded px-1.5 py-0.5">
                ADMIN
              </span>
              <span className="text-tx2 text-xs truncate">{email}</span>
            </div>
          )}
          <button
            onClick={logout}
            className="w-full text-left text-xs text-tx2 hover:text-rd transition-colors px-3 py-2"
          >
            ⏻ Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Topbar */}
        <header className="h-12 bg-s1 border-b border-s3 flex items-center px-6 gap-6 shrink-0">
          <div className="flex-1 min-w-0">
            <Ticker />
          </div>
          <button
            onClick={toggle}
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            className="shrink-0 flex items-center gap-1.5 font-mono text-[10px] tracking-widest px-3 py-1.5 rounded-lg transition-colors"
            style={{
              background: 'var(--color-s2)',
              border: '1px solid var(--color-card-border)',
              color: 'var(--color-tx2)',
            }}
          >
            {theme === 'dark' ? '☀ LIGHT' : '☾ DARK'}
          </button>
        </header>
        {/* Page content */}
        <main className="flex-1 overflow-y-auto bg-bg p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
