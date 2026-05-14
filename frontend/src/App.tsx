import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
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
import Referral from './pages/Referral'
import AuditLog from './pages/AuditLog'
import Community from './pages/Community'
import Profile from './pages/Profile'
import DataManagement from './pages/DataManagement'
import { useAdminUser } from './hooks/useAdminUser'

function RequireAuth({ children }: { children: JSX.Element }) {
  return localStorage.getItem('access_token') ? children : <Navigate to="/login" replace />
}

function RequireAdmin({ children }: { children: JSX.Element }) {
  const { isAdmin } = useAdminUser()
  if (!localStorage.getItem('access_token')) return <Navigate to="/login" replace />
  return isAdmin ? children : <Navigate to="/dashboard" replace />
}

// Listens for auth:logout events dispatched by the axios interceptor and
// navigates to /login via React Router (no hard reload, no page flash).
function AuthRedirector() {
  const navigate = useNavigate()
  useEffect(() => {
    const handler = () => navigate('/login', { replace: true })
    window.addEventListener('auth:logout', handler)
    return () => window.removeEventListener('auth:logout', handler)
  }, [navigate])
  return null
}

export default function App() {
  return (
    <ThemeProvider>
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AuthRedirector />
      <Routes>
        <Route path="/login"    element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/" element={<RequireAuth><Layout /></RequireAuth>}>
          <Route index            element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="regime"    element={<RegimeDetector />} />
          <Route path="signals"   element={<Signals />} />
          <Route path="trades"    element={<Trades />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="model"     element={<RequireAdmin><ModelRetrain /></RequireAdmin>} />
          <Route path="billing"   element={<Billing />} />
          <Route path="referral"  element={<Referral />} />
          <Route path="auditlog"  element={<AuditLog />} />
          <Route path="settings"  element={<Settings />} />
          <Route path="profile"   element={<Profile />} />
          <Route path="community"       element={<RequireAdmin><Community /></RequireAdmin>} />
          <Route path="admin"           element={<RequireAdmin><AdminPanel /></RequireAdmin>} />
          <Route path="data-management" element={<RequireAdmin><DataManagement /></RequireAdmin>} />
        </Route>
      </Routes>
    </BrowserRouter>
    </ThemeProvider>
  )
}
