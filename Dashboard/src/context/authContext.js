/**
 * Context object + hook only - the provider component lives in
 * AuthProvider.jsx, split the same way EventStream.jsx/
 * eventStreamContext.js are, so Fast Refresh can hot-swap the provider
 * without losing this module's identity.
 */

import { createContext, useContext } from 'react'

export const AuthContext = createContext(null)

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === null) {
    throw new Error('useAuth() called outside an <AuthProvider>')
  }
  return context
}
