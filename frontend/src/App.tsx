import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ThemeProvider } from './contexts/ThemeContext'
import Layout from './components/Layout'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import Signals from './pages/Signals'
import Trades from './pages/Trades'
import Analytics from './pages/Analytics'
import Billing from './pages/Billing'
import Settings from './pages/Settings'
import AdminPanel from './pages/AdminPanel'
import RegimeDetector from './pages/RegimeDetector'
import ModelRetrain from './pages/ModelRetrain'

import AuditLog from './pages/AuditLog'
import Community from './pages/Community'
import Profile from './pages/Profile'
import DataManagement from './pages/DataManagement'
import AdminPairs from './pages/AdminPairs'
import News from './pages/News'
import ForgotPassword from './pages/ForgotPassword'
import ResetPassword from './pages/ResetPassword'
import NotFound from './pages/NotFound'
import ServerError from './pages/ServerError'
import Unauthorized from './pages/Unauthorized'
import UpgradeRequired from './pages/UpgradeRequired'
import Trial from './pages/Trial'
import Landing from './pages/Landing'
import { useAdminUser } from './hooks/useAdminUser'
import { getToken } from './api/client'
import api from './api/client'

function RequireAuth({ children }: { children: JSX.Element }) {
  return getToken() ? children : <Landing />
}

function RequireAdmin({ children }: { children: JSX.Element }) {
  const { isAdmin } = useAdminUser()
  if (!getToken()) return <Unauthorized />
  return isAdmin ? children : <UpgradeRequired requiredPlan="elite" />
}

function AuthRedirector() {
  const navigate = useNavigate()
  useEffect(() => {
    const handler = () => navigate('/login', { replace: true })
    window.addEventListener('auth:logout', handler)
    return () => window.removeEventListener('auth:logout', handler)
  }, [navigate])
  return null
}

function MaintenancePage() {
  const { isAdmin } = useAdminUser()
  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#05080f', flexDirection: 'column', gap: 16 }}>
      <div style={{ fontSize: 48 }}>🔧</div>
      <h1 style={{ color: '#d4a853', fontFamily: 'Figtree,sans-serif', fontWeight: 800, fontSize: 28, margin: 0 }}>Under Maintenance</h1>
      <p style={{ color: '#445570', fontFamily: 'IBM Plex Mono,monospace', fontSize: 13, textAlign: 'center', maxWidth: 400, margin: 0 }}>
        The platform is temporarily down for maintenance. Please check back shortly.
      </p>
      {isAdmin && (
        <a href="/admin" style={{ color: '#00e5cc', fontFamily: 'IBM Plex Mono,monospace', fontSize: 12, marginTop: 8 }}>
          Admin: go to panel →
        </a>
      )}
    </div>
  )
}

function AppRoutes() {
  const { isAdmin } = useAdminUser()

  const { data: flags, isLoading } = useQuery({
    queryKey: ['site-flags'],
    queryFn: () => api.get('/config/flags').then(r => r.data),
    staleTime: 10_000,
    refetchInterval: 30_000,
  })

  if (isLoading) return null

  const maintenance = !!flags?.maintenance_mode

  // Non-admins see maintenance page; admins always pass through
  if (maintenance && !isAdmin) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<MaintenancePage />} />
      </Routes>
    )
  }

  // Admins bypass maintenance mode so they can turn it off
  if (maintenance && !isAdmin) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<MaintenancePage />} />
      </Routes>
    )
  }

  return (
    <Routes>
      <Route path="/login"           element={<Login />} />
      <Route path="/register"        element={<Register />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password"  element={<ResetPassword />} />
      <Route path="/" element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index            element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="regime"    element={<RegimeDetector />} />
        <Route path="signals"   element={<Signals />} />
        <Route path="trades"    element={<Trades />} />
        <Route path="news"     element={<News />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="model"     element={<RequireAdmin><ModelRetrain /></RequireAdmin>} />
        <Route path="billing"   element={<Billing />} />
        <Route path="referral"  element={<Navigate to="/settings" replace />} />
        <Route path="auditlog"  element={<AuditLog />} />
        <Route path="settings"  element={<Settings />} />
        <Route path="trial"     element={<Trial />} />
        <Route path="profile"   element={<Profile />} />
        <Route path="community"       element={<RequireAdmin><Community /></RequireAdmin>} />
        <Route path="admin"           element={<RequireAdmin><AdminPanel /></RequireAdmin>} />
        <Route path="data-management" element={<RequireAdmin><DataManagement /></RequireAdmin>} />
        <Route path="pairs"           element={<RequireAdmin><AdminPairs /></RequireAdmin>} />
      </Route>
      <Route path="/500" element={<ServerError />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}

export default function App() {
  return (
    <ThemeProvider>
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AuthRedirector />
      <AppRoutes />
    </BrowserRouter>
    </ThemeProvider>
  )
}
