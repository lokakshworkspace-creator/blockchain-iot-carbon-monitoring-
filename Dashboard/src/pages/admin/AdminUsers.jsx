/**
 * Users tab of the admin panel: list, create a Regional Head, deactivate/
 * reactivate, and reassign region. Never creates a second admin from
 * this form - Gateway/routers/admin_users.py rejects role="admin"
 * without an explicit confirm_admin_creation flag this form never sets,
 * matching this phase's scope (Regional Head accounts only).
 */

import { useEffect, useState } from 'react'

import { adminCreateUser, adminListRegions, adminListUsers, adminUpdateUser } from '../../services/api.js'

const EMPTY_FORM = { username: '', email: '', password: '', regionId: '' }

export default function AdminUsers() {
  const [users, setUsers] = useState([])
  const [regions, setRegions] = useState([])
  const [error, setError] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [pending, setPending] = useState(false)

  function refreshUsers() {
    adminListUsers()
      .then(setUsers)
      .catch((err) => setError(err.message))
  }

  useEffect(() => {
    refreshUsers()
    adminListRegions()
      .then(setRegions)
      .catch(() => {}) // the region dropdown just stays empty; user list/create still work
  }, [])

  async function handleCreate(event) {
    event.preventDefault()
    setPending(true)
    setError(null)
    try {
      await adminCreateUser({
        username: form.username,
        email: form.email,
        password: form.password,
        role: 'regional_head',
        regionId: form.regionId || null,
      })
      setForm(EMPTY_FORM)
      refreshUsers()
    } catch (err) {
      setError(err.message)
    } finally {
      setPending(false)
    }
  }

  async function toggleActive(user) {
    setError(null)
    try {
      await adminUpdateUser(user.id, { isActive: !user.is_active })
      refreshUsers()
    } catch (err) {
      setError(err.message)
    }
  }

  async function reassignRegion(user, regionId) {
    setError(null)
    try {
      await adminUpdateUser(user.id, { regionId: regionId || null })
      refreshUsers()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section className="section">
      <h2>Users</h2>
      {error && <div className="empty error-text">{error}</div>}

      <form className="card card-pad admin-form" onSubmit={handleCreate}>
        <input
          className="input"
          placeholder="Username"
          value={form.username}
          onChange={(event) => setForm({ ...form, username: event.target.value })}
          required
        />
        <input
          className="input"
          placeholder="Email"
          type="email"
          value={form.email}
          onChange={(event) => setForm({ ...form, email: event.target.value })}
          required
        />
        <input
          className="input"
          placeholder="Password"
          type="password"
          value={form.password}
          onChange={(event) => setForm({ ...form, password: event.target.value })}
          required
        />
        <select
          className="device-select"
          value={form.regionId}
          onChange={(event) => setForm({ ...form, regionId: event.target.value })}
          required
        >
          <option value="">Select a region…</option>
          {regions.map((region) => (
            <option key={region.id} value={region.id}>
              {region.name}
            </option>
          ))}
        </select>
        <button type="submit" className="btn-verify" disabled={pending}>
          {pending ? 'Creating…' : 'Create Regional Head'}
        </button>
      </form>

      <div className="card">
        {users.length === 0 ? (
          <div className="empty">No users yet.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Email</th>
                <th>Role</th>
                <th>Region</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td className="mono">{user.username}</td>
                  <td className="dim">{user.email}</td>
                  <td>
                    <span className="badge badge-online">{user.role}</span>
                  </td>
                  <td>
                    {user.role === 'admin' ? (
                      <span className="dim">—</span>
                    ) : (
                      <select
                        className="device-select"
                        value={user.region_id ?? ''}
                        onChange={(event) => reassignRegion(user, event.target.value)}
                      >
                        <option value="">Unassigned</option>
                        {regions.map((region) => (
                          <option key={region.id} value={region.id}>
                            {region.name}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                  <td>
                    <span className={user.is_active ? 'badge badge-online' : 'badge badge-offline'}>
                      {user.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td>
                    <button type="button" className="chip" onClick={() => toggleActive(user)}>
                      {user.is_active ? 'Deactivate' : 'Reactivate'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}
