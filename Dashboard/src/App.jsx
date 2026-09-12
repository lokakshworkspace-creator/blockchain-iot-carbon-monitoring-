/**
 * Shell for the dashboard: persistent sidebar navigation, plus a live
 * gateway-connection indicator in the header so it is always obvious
 * whether what you are looking at is live or stale.
 *
 * Phase 7 adds real auth (login, role-aware routing, an admin panel, a
 * Regional Head dashboard) alongside the original five pages - it does
 * NOT replace or gate them. Those five (Overview, Real-Time Data,
 * Verification, Blockchain Logs, System Monitor) predate the RBAC work,
 * have no role concept, and stay exactly as they were: unauthenticated,
 * reachable at their existing paths. /login renders outside the sidebar
 * shell (a login screen showing nav links to pages behind auth would be
 * confusing); everything else, old and new, renders inside it.
 *
 * Routing is client-side only (react-router-dom); the gateway serves no
 * HTML, it only serves the REST + WebSocket API this app consumes.
 */

import { NavLink, Navigate, Outlet, Route, Routes } from 'react-router-dom'

import ConnectionStatus from './components/ConnectionStatus.jsx'
import NotificationBell from './components/NotificationBell.jsx'
import RequireAuth from './components/RequireAuth.jsx'
import { useAuth } from './context/authContext.js'
import AdminAuditLog from './pages/admin/AdminAuditLog.jsx'
import AdminBlockchainStatus from './pages/admin/AdminBlockchainStatus.jsx'
import AdminFactoriesDevices from './pages/admin/AdminFactoriesDevices.jsx'
import AdminLayout from './pages/admin/AdminLayout.jsx'
import AdminRegions from './pages/admin/AdminRegions.jsx'
import AdminSystemHealth from './pages/admin/AdminSystemHealth.jsx'
import AdminUsers from './pages/admin/AdminUsers.jsx'
import BlockchainLogs from './pages/BlockchainLogs.jsx'
import FactoryDetail from './pages/dashboard/FactoryDetail.jsx'
import RegionalDashboard from './pages/dashboard/RegionalDashboard.jsx'
import Login from './pages/Login.jsx'
import Overview from './pages/Overview.jsx'
import RealTimeData from './pages/RealTimeData.jsx'
import SystemMonitor from './pages/SystemMonitor.jsx'
import Verification from './pages/Verification.jsx'

// Unchanged since before the RBAC work - see the module docstring.
const NAV_ITEMS = [
  { to: '/', label: 'Overview', end: true },
  { to: '/realtime', label: 'Real-Time Data' },
  { to: '/verification', label: 'Verification' },
  { to: '/blockchain', label: 'Blockchain Logs' },
  { to: '/system', label: 'System Monitor' },
]

function AuthNav() {
  const { user, logout } = useAuth()

  if (!user) {
    return (
      <nav className="nav-secondary">
        <NavLink to="/login" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
          Login
        </NavLink>
      </nav>
    )
  }

  return (
    <nav className="nav-secondary">
      {user.role === 'admin' && (
        <NavLink to="/admin" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
          Admin Panel
        </NavLink>
      )}
      {/* Admin can view the Regional Head dashboard too, per the brief. */}
      <NavLink to="/dashboard" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
        {user.role === 'admin' ? 'Regional Dashboard' : 'Dashboard'}
      </NavLink>
      <button type="button" className="nav-link nav-logout" onClick={logout}>
        Log out ({user.username})
      </button>
    </nav>
  )
}

function Shell() {
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">CO₂</div>
          <div>
            <div className="brand-title">Carbon Monitor</div>
            <div className="brand-subtitle">Blockchain + IoT</div>
          </div>
          <NotificationBell />
        </div>

        <nav>
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <AuthNav />

        <div className="sidebar-footer">
          <ConnectionStatus />
        </div>
      </aside>

      <main className="content">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/realtime" element={<RealTimeData />} />
          <Route path="/verification" element={<Verification />} />
          <Route path="/blockchain" element={<BlockchainLogs />} />
          <Route path="/system" element={<SystemMonitor />} />

          <Route
            path="/admin"
            element={
              <RequireAuth roles={['admin']}>
                <AdminLayout />
              </RequireAuth>
            }
          >
            <Route index element={<Navigate to="/admin/users" replace />} />
            <Route path="users" element={<AdminUsers />} />
            <Route path="regions" element={<AdminRegions />} />
            <Route path="factories" element={<AdminFactoriesDevices />} />
            <Route path="system-health" element={<AdminSystemHealth />} />
            <Route path="blockchain-status" element={<AdminBlockchainStatus />} />
            <Route path="audit-log" element={<AdminAuditLog />} />
          </Route>

          <Route
            path="/dashboard"
            element={
              <RequireAuth roles={['admin', 'regional_head']}>
                <Outlet />
              </RequireAuth>
            }
          >
            <Route index element={<RegionalDashboard />} />
            <Route path="factories/:factoryId" element={<FactoryDetail />} />
          </Route>
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={<Shell />} />
    </Routes>
  )
}
