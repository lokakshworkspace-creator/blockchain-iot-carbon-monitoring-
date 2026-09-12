/**
 * Username/password -> POST /api/auth/login (via AuthContext.login()),
 * which stores the token and redirects by role: admin -> /admin,
 * regional_head -> /dashboard. See services/api.js's TOKEN_STORAGE_KEY
 * comment for why the token lives in localStorage rather than
 * in-memory-only.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../context/authContext.js'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [pending, setPending] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setPending(true)
    setError(null)
    try {
      const user = await login(username, password)
      navigate(user.role === 'admin' ? '/admin' : '/dashboard', { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="login-page">
      <form className="card login-form" onSubmit={handleSubmit}>
        <div className="login-brand">
          <div className="brand-mark">CO₂</div>
          <h1>Carbon Monitor</h1>
        </div>
        <p className="page-subtitle login-subtitle">Sign in to continue.</p>

        {error && <div className="empty error-text login-error">{error}</div>}

        <label className="login-field">
          <span>Username</span>
          <input
            className="input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoFocus
            autoComplete="username"
            required
          />
        </label>
        <label className="login-field">
          <span>Password</span>
          <input
            className="input"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        <button type="submit" className="btn-verify" disabled={pending}>
          {pending ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
