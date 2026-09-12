/**
 * Regional Head landing page: region name at top, a grid of the
 * region's factories below (visual treatment is Phase 8 - this phase
 * just needs a working list). Admin can reach this page too (per the
 * brief), in which case GET /api/regions/me returns every region rather
 * than one, so there's no single region name to show - handled below
 * rather than assumed away.
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { useAuth } from '../../context/authContext.js'
import { getMyFactories, getMyRegion } from '../../services/api.js'

export default function RegionalDashboard() {
  const { user } = useAuth()
  const [region, setRegion] = useState(null)
  const [factories, setFactories] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    getMyRegion()
      .then((result) => setRegion(Array.isArray(result) ? null : result))
      .catch((err) => setError(err.message))
    getMyFactories()
      .then(setFactories)
      .catch((err) => setError(err.message))
  }, [])

  const isAdmin = user.role === 'admin'

  return (
    <div className="page">
      <h1>{region ? region.name : isAdmin ? 'All Regions' : 'Region Dashboard'}</h1>
      <p className="page-subtitle">
        {isAdmin ? "Every region's factories." : "Your region's factories."}
      </p>

      {error && <div className="empty error-text">{error}</div>}

      <section className="section">
        <h2>Factories</h2>
        {!error && factories.length === 0 && <div className="empty">No factories yet.</div>}
        <div className="factory-grid">
          {factories.map((factory) => (
            <Link key={factory.id} to={`/dashboard/factories/${factory.id}`} className="card factory-card">
              <div className="factory-card-name">{factory.name}</div>
              <div className="dim">{factory.location || 'No location set'}</div>
              <span className={factory.is_simulated ? 'badge badge-pending' : 'badge badge-online'}>
                {factory.is_simulated ? 'Simulated' : 'Real'}
              </span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}
