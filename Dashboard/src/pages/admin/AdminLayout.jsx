/**
 * Layout + sub-nav for /admin/* - mounted under RequireAuth(roles=["admin"])
 * in App.jsx. <Outlet/> renders whichever admin page is currently active.
 */

import { NavLink, Outlet } from 'react-router-dom'

const ADMIN_NAV_ITEMS = [
  { to: '/admin/users', label: 'Users' },
  { to: '/admin/regions', label: 'Regions' },
  { to: '/admin/factories', label: 'Factories & Devices' },
  { to: '/admin/system-health', label: 'System Health' },
  { to: '/admin/blockchain-status', label: 'Blockchain Status' },
  { to: '/admin/audit-log', label: 'Audit Log' },
]

export default function AdminLayout() {
  return (
    <div className="page">
      <h1>Admin Panel</h1>
      <p className="page-subtitle">Regions, factories, devices, and user accounts.</p>
      <nav className="filters admin-subnav">
        {ADMIN_NAV_ITEMS.map((item) => (
          <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? 'chip active' : 'chip')}>
            {item.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  )
}
