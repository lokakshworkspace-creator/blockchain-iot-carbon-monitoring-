/**
 * Shell for the dashboard: persistent sidebar navigation across the five
 * pages, plus a live gateway-connection indicator in the header so it is
 * always obvious whether what you are looking at is live or stale.
 *
 * Routing is client-side only (react-router-dom); the gateway serves no
 * HTML, it only serves the REST + WebSocket API this app consumes.
 */

import { NavLink, Route, Routes } from 'react-router-dom'

import ConnectionStatus from './components/ConnectionStatus.jsx'
import BlockchainLogs from './pages/BlockchainLogs.jsx'
import Overview from './pages/Overview.jsx'
import RealTimeData from './pages/RealTimeData.jsx'
import SystemMonitor from './pages/SystemMonitor.jsx'
import Verification from './pages/Verification.jsx'

const NAV_ITEMS = [
  { to: '/', label: 'Overview', end: true },
  { to: '/realtime', label: 'Real-Time Data' },
  { to: '/verification', label: 'Verification' },
  { to: '/blockchain', label: 'Blockchain Logs' },
  { to: '/system', label: 'System Monitor' },
]

export default function App() {
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">CO₂</div>
          <div>
            <div className="brand-title">Carbon Monitor</div>
            <div className="brand-subtitle">Blockchain + IoT</div>
          </div>
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
        </Routes>
      </main>
    </div>
  )
}
