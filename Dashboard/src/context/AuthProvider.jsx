/**
 * Session state for the whole app: the decoded current user (or null),
 * restored from a stored token on mount so a page reload doesn't force a
 * re-login, and cleared automatically on any 401 from api.js (see
 * onUnauthorized() there) - that's what makes a route wrapped in
 * RequireAuth redirect to /login the moment a token expires or is
 * revoked server-side, not just when the user explicitly logs out.
 *
 * `user` is a client-side JWT decode (lib/jwt.js) - UX only. The real
 * access check happens on every request, server-side, regardless of
 * what this component believes.
 */

import { useEffect, useMemo, useState } from 'react'

import { decodeToken } from '../lib/jwt.js'
import { clearStoredToken, getStoredToken, login as apiLogin, onUnauthorized, setStoredToken } from '../services/api.js'
import { AuthContext } from './authContext.js'

export function AuthProvider({ children }) {
  // Lazy initializer: restores a session from localStorage synchronously
  // on first render, so there is no flash of "logged out" before an
  // effect gets a chance to run.
  const [user, setUser] = useState(() => decodeToken(getStoredToken()))

  useEffect(() => onUnauthorized(() => setUser(null)), [])

  async function login(username, password) {
    const result = await apiLogin(username, password) // throws on 401/network failure - LoginPage's own try/catch handles the message
    setStoredToken(result.access_token)
    const decoded = decodeToken(result.access_token)
    setUser(decoded)
    return decoded
  }

  function logout() {
    clearStoredToken()
    setUser(null)
  }

  const value = useMemo(() => ({ user, login, logout }), [user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
