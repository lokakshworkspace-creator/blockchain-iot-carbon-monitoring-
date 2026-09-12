/**
 * Regions tab of the admin panel: list + create. No edit/delete UI in
 * this phase (structure/routing/wiring first, per the brief) - the
 * gateway supports PATCH/DELETE (Gateway/routers/admin_regions.py)
 * already, for a later pass.
 */

import { useEffect, useState } from 'react'

import { adminCreateRegion, adminListRegions } from '../../services/api.js'

export default function AdminRegions() {
  const [regions, setRegions] = useState([])
  const [error, setError] = useState(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [pending, setPending] = useState(false)

  function refresh() {
    adminListRegions()
      .then(setRegions)
      .catch((err) => setError(err.message))
  }

  useEffect(refresh, [])

  async function handleCreate(event) {
    event.preventDefault()
    setPending(true)
    setError(null)
    try {
      await adminCreateRegion({ name, description })
      setName('')
      setDescription('')
      refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="section">
      <h2>Regions</h2>
      {error && <div className="empty error-text">{error}</div>}

      <form className="card card-pad admin-form" onSubmit={handleCreate}>
        <input className="input" placeholder="Name" value={name} onChange={(event) => setName(event.target.value)} required />
        <input
          className="input"
          placeholder="Description (optional)"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <button type="submit" className="btn-verify" disabled={pending}>
          {pending ? 'Creating…' : 'Create region'}
        </button>
      </form>

      <div className="card">
        {regions.length === 0 ? (
          <div className="empty">No regions yet.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {regions.map((region) => (
                <tr key={region.id}>
                  <td>{region.name}</td>
                  <td className="dim">{region.description || '—'}</td>
                  <td className="mono dim">{region.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}
