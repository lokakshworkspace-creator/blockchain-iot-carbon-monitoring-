/**
 * Self-service "change my password" - available to any logged-in user
 * (admin or regional_head), reachable from the sidebar next to Log out
 * (see App.jsx's AuthNav). Backs onto Gateway's POST
 * /api/auth/change-password, which verifies current_password against the
 * real stored hash and never trusts the client's claim to know it.
 *
 * On success this deliberately does NOT log the user out or reload the
 * page - the backend does not reissue a token on a password change (the
 * existing one stays valid until it naturally expires), so there is
 * nothing here that needs a fresh session either.
 */

import { useState } from 'react'

import { changePassword } from '../services/api.js'

// Mirrors Gateway/models.py's CHANGE_PASSWORD_MIN_LENGTH. Kept in sync by
// hand, same as every other cross-language constant in this project (e.g.
// ESP32/buzzer_alarm.h's CO2_ALARM_THRESHOLD_PPM vs Gateway/.env) - the
// server is still the real enforcement point (see its 422 on a
// violation); this is only so a user sees why before submitting instead
// of after.
const MIN_NEW_PASSWORD_LENGTH = 8

export default function ChangePassword() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(false)
  const [pending, setPending] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)
    setSuccess(false)

    if (newPassword !== confirmPassword) {
      setError('New password and confirmation do not match.')
      return
    }
    if (newPassword.length < MIN_NEW_PASSWORD_LENGTH) {
      setError(`New password must be at least ${MIN_NEW_PASSWORD_LENGTH} characters.`)
      return
    }

    setPending(true)
    try {
      await changePassword(currentPassword, newPassword)
      setSuccess(true)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      setError(err.message)
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="page">
      <h1>Change Password</h1>
      <p className="page-subtitle">Update the password for your own account.</p>

      <form className="card login-form" onSubmit={handleSubmit}>
        {success && <div className="empty success-text login-success">Password changed successfully.</div>}
        {error && <div className="empty error-text login-error">{error}</div>}

        <label className="login-field">
          <span>Current password</span>
          <input
            className="input"
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <label className="login-field">
          <span>New password</span>
          <input
            className="input"
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            autoComplete="new-password"
            minLength={MIN_NEW_PASSWORD_LENGTH}
            required
          />
        </label>
        <label className="login-field">
          <span>Confirm new password</span>
          <input
            className="input"
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            autoComplete="new-password"
            minLength={MIN_NEW_PASSWORD_LENGTH}
            required
          />
        </label>

        <button type="submit" className="btn-verify" disabled={pending}>
          {pending ? 'Changing…' : 'Change password'}
        </button>
      </form>
    </div>
  )
}
