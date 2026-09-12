/**
 * Client-side route guard for /admin/* and /dashboard/* - redirects to
 * /login if there's no session, or to the caller's own role-appropriate
 * landing page if they're logged in but the role doesn't match (never a
 * dead end, and never back to /login for someone who IS authenticated).
 *
 * This is UX only, same caveat as lib/jwt.js: the gateway's own
 * require_role()/get_current_user() enforce the real access control on
 * every request, regardless of what this component lets through.
 */

import { Navigate, useLocation } from 'react-router-dom'

import { useAuth } from '../context/authContext.js'

export default function RequireAuth({ roles, children }) {
  const { user } = useAuth()
  const location = useLocation()

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  if (roles && !roles.includes(user.role)) {
    return <Navigate to={user.role === 'admin' ? '/admin' : '/dashboard'} replace />
  }
  return children
}
