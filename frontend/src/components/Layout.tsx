import { useState } from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import api, { clearToken } from '../api/client'
import { useAdminUser } from '../hooks/useAdminUser'
import { useTheme } from '../contexts/ThemeContext'
import { useBranding } from '../hooks/useBranding'
import localLogo from '../logo.webp'

const NAV_GROUPS = [
  {
    label: 'Trading',
    items: [
      { to: '/dashboard', label: 'Dashboard',        icon: '⬛' },
      { to: '/regime',    label: 'Regime Detector',  icon: '◈' },
      { to: '/signals',   label: 'Signals',          icon: '◆' },
      { to: '/trades',    label: 'Trades',           icon: '↯' },
      { to: '/news',      label: 'News',             icon: '📰' },
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
  { to: '/admin',           label: 'Admin Panel',     icon: '◈' },
  { to: '/model',           label: 'Model & Retrain', icon: '◉' },
  { to: '/data-management', label: 'Data Management', icon: '⬢' },
  { to: '/community',       label: 'Community',       icon: '⬡' },
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
    <div className="topbar-ticker flex gap-6 text-xs font-mono text-tx2 overflow-hidden">
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
  const { app_name, app_logo_url } = useBranding()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  function logout() {
    clearToken()
    navigate('/login')
  }

  function navTo() {
    setSidebarOpen(false)
  }

  return (
    <div className="flex h-screen overflow-hidden">

      {/* Mobile backdrop */}
      <div
        className={`sb-overlay${sidebarOpen ? ' open' : ''}`}
        onClick={() => setSidebarOpen(false)}
      />

      {/* Sidebar */}
      <aside className={`sidebar-desktop${sidebarOpen ? ' open' : ''} bg-s1 border-r border-s3 flex flex-col shrink-0`}
        style={{ width: 224 }}>
        <div className="px-5 py-5 border-b border-s3 flex items-center gap-3">
          <img src={app_logo_url} alt="logo" className="w-7 h-7 rounded object-contain shrink-0" onError={e => { (e.currentTarget as HTMLImageElement).src = localLogo }} />
          <span className="sidebar-logo-text font-head font-bold text-cy text-lg tracking-wide truncate">{app_name}</span>
        </div>
        <nav className="flex-1 py-4 space-y-0.5 px-2 overflow-y-auto">
          {NAV_GROUPS.map(g => (
            <div key={g.label} className="mb-3">
              <div className="nav-group-label px-3 py-1 text-[9px] font-mono tracking-widest text-tx3 uppercase">{g.label}</div>
              {g.items.map(n => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  onClick={navTo}
                  className={({ isActive }) =>
                    `nav-link-item flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm ` +
                    (isActive ? 'bg-cy/10 text-cy font-medium' : 'text-tx2 hover:text-tx hover:bg-s2')
                  }
                >
                  <span className="nav-icon text-base w-4 text-center shrink-0">{n.icon}</span>
                  <span className="nav-label-text">{n.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
          {isAdmin && (
            <div className="mb-3">
              <div className="nav-group-label px-3 py-1 text-[9px] font-mono tracking-widest text-tx3 uppercase">Admin</div>
              {ADMIN_ITEMS.map(n => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  onClick={navTo}
                  className={({ isActive }) =>
                    `nav-link-item flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm ` +
                    (isActive ? 'bg-cy/10 text-cy font-medium' : 'text-tx2 hover:text-tx hover:bg-s2')
                  }
                >
                  <span className="nav-icon text-base w-4 text-center shrink-0">{n.icon}</span>
                  <span className="nav-label-text">{n.label}</span>
                </NavLink>
              ))}
            </div>
          )}
        </nav>
        <div className="sidebar-footer px-4 py-4 border-t border-s3 space-y-2">
          {isAdmin && (
            <div className="flex items-center gap-2 px-3 min-w-0">
              <span className="shrink-0 text-[10px] font-bold uppercase tracking-widest text-cy border border-cy/30 bg-cy/10 rounded px-1.5 py-0.5">
                ADMIN
              </span>
              <span className="nav-label-text text-tx2 text-xs truncate min-w-0">{email}</span>
            </div>
          )}
          <button
            onClick={logout}
            className="w-full flex items-center gap-2 whitespace-nowrap text-xs text-tx2 hover:text-rd transition-colors px-3 py-2 rounded-lg hover:bg-rd/5"
          >
            <span className="shrink-0">⏻</span>
            <span className="nav-label-text truncate">Sign out</span>
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Topbar */}
        <header className="h-12 bg-s1 border-b border-s3 flex items-center px-4 gap-4 shrink-0 relative">
          {/* Hamburger */}
          <button
            className={`hbg${sidebarOpen ? ' open' : ''}`}
            onClick={() => setSidebarOpen(o => !o)}
            aria-label="Toggle menu"
          >
            <span /><span /><span />
          </button>

          {/* Logo / ticker */}
          <div className="topbar-logo flex-1 min-w-0">
            <Ticker />
          </div>

          {/* Theme toggle — pinned to far right */}
          <button
            onClick={toggle}
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            className="ml-auto shrink-0 flex items-center gap-1.5 font-mono text-[10px] tracking-widest px-3 py-1.5 rounded-lg transition-colors"
            style={{
              background: 'var(--color-s2)',
              border: '1px solid var(--color-card-border)',
              color: 'var(--color-tx2)',
            }}
          >
            {theme === 'dark' ? '☀' : '☾'}
            <span className="hide-mobile">{theme === 'dark' ? ' LIGHT' : ' DARK'}</span>
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
