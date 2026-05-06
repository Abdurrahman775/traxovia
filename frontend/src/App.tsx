import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import Signals from './pages/Signals'
import Trades from './pages/Trades'
import Analytics from './pages/Analytics'
import BridgeMonitor from './pages/BridgeMonitor'
import Billing from './pages/Billing'
import Settings from './pages/Settings'
import AdminPanel from './pages/AdminPanel'
import RegimeDetector from './pages/RegimeDetector'
import ModelRetrain from './pages/ModelRetrain'
import Referral from './pages/Referral'
import AuditLog from './pages/AuditLog'
import Community from './pages/Community'
import { useAdminUser } from './hooks/useAdminUser'

function RequireAuth({ children }: { children: JSX.Element }) {
  return localStorage.getItem('access_token') ? children : <Navigate to="/login" replace />
}

function RequireAdmin({ children }: { children: JSX.Element }) {
  const { isAdmin } = useAdminUser()
  if (!localStorage.getItem('access_token')) return <Navigate to="/login" replace />
  return isAdmin ? children : <Navigate to="/dashboard" replace />
}

export default function App() {
  return (
    <BrowserRouter>
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
          <Route path="model"     element={<ModelRetrain />} />
          <Route path="billing"   element={<Billing />} />
          <Route path="referral"  element={<Referral />} />
          <Route path="auditlog"  element={<AuditLog />} />
          <Route path="settings"  element={<Settings />} />
          <Route path="bridge"    element={<BridgeMonitor />} />
          <Route path="community" element={<RequireAdmin><Community /></RequireAdmin>} />
          <Route path="admin"     element={<RequireAdmin><AdminPanel /></RequireAdmin>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
