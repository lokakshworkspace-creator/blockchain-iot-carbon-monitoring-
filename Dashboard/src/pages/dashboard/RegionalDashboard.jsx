/**
 * Regional Head landing page: a hierarchical grid, not a geographic map -
 * region as a labeled section, factory tiles inside it. Admin can reach
 * this page too (per the brief), in which case GET /api/regions/me
 * returns every region rather than one, so factories are grouped into
 * one labeled section per region instead of one flat, unlabeled grid.
 *
 * Each factory tile's status dot + current CO2 reading are derived
 * entirely from hooks/endpoints that already existed before this
 * styling pass - no new endpoint, no new polling. getFactoryDevices()
 * (Phase 3/7) resolves which device_ids belong to which factory;
 * useEventStream() (used by every other page already) supplies the same
 * shared, already-open WebSocket buffer everything else reads live
 * readings from. A factory with no reading yet in that buffer shows a
 * neutral dot rather than guessing a color.
 */

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { useAuth } from '../../context/authContext.js'
import { useEventStream } from '../../context/eventStreamContext.js'
import { useThresholds } from '../../hooks/useThresholds.js'
import { classify } from '../../lib/levels.js'
import { getFactoryDevices, getMyFactories, getMyRegion } from '../../services/api.js'

function FactoryTile({ factory, status }) {
  const level = status ? status.level.toLowerCase() : null
  return (
    <Link
      to={`/dashboard/factories/${factory.id}`}
      className={`card factory-card${level ? ` factory-card-${level}` : ''}`}
    >
      <div className="factory-card-top">
        <span className={`factory-dot${level ? ` factory-dot-${level}` : ''}`} aria-hidden="true" />
        <div className="factory-card-name">{factory.name}</div>
      </div>
      <div className="dim">{factory.location || 'No location set'}</div>
      <div className="factory-card-reading mono">{status ? `${status.co2} ppm` : 'No live reading yet'}</div>
      <span className={factory.is_simulated ? 'badge badge-pending' : 'badge badge-online'}>
        {factory.is_simulated ? 'Simulated' : 'Real'}
      </span>
    </Link>
  )
}

export default function RegionalDashboard() {
  const { user } = useAuth()
  const { events } = useEventStream()
  const { thresholds } = useThresholds()

  const [region, setRegion] = useState(null) // regional_head: their one region
  const [regions, setRegions] = useState([]) // admin: every region, for section labels
  const [factories, setFactories] = useState([])
  const [factoryDeviceIds, setFactoryDeviceIds] = useState({}) // factoryId -> [device_id, ...]
  const [error, setError] = useState(null)

  const isAdmin = user.role === 'admin'

  useEffect(() => {
    getMyRegion()
      .then((result) => {
        if (Array.isArray(result)) {
          setRegions(result)
        } else if (result) {
          setRegion(result)
        }
      })
      .catch((err) => setError(err.message))
    getMyFactories()
      .then(setFactories)
      .catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    if (factories.length === 0) return
    let cancelled = false
    Promise.all(
      factories.map((factory) =>
        getFactoryDevices(factory.id)
          .then((devices) => [factory.id, devices.map((d) => d.device_id)])
          .catch(() => [factory.id, []]),
      ),
    ).then((pairs) => {
      if (!cancelled) setFactoryDeviceIds(Object.fromEntries(pairs))
    })
    return () => {
      cancelled = true
    }
  }, [factories])

  // Most recent SENSOR_READING per factory, from the buffer every other
  // page already shares - events are newest-first, so the first match
  // per factory is its latest reading.
  const factoryStatus = useMemo(() => {
    const status = {}
    for (const factory of factories) {
      const deviceIds = factoryDeviceIds[factory.id]
      if (!deviceIds || deviceIds.length === 0) continue
      const latest = events.find((e) => e.event_type === 'SENSOR_READING' && deviceIds.includes(e.device_id))
      if (latest) {
        status[factory.id] = { co2: latest.data.co2, level: classify(latest.data.co2, thresholds) }
      }
    }
    return status
  }, [events, factories, factoryDeviceIds, thresholds])

  const regionName = useMemo(() => {
    const byId = new Map(regions.map((r) => [r.id, r.name]))
    return (regionId) => byId.get(regionId) ?? 'Unknown region'
  }, [regions])

  const factoriesByRegion = useMemo(() => {
    const grouped = new Map()
    for (const factory of factories) {
      const list = grouped.get(factory.region_id) ?? []
      list.push(factory)
      grouped.set(factory.region_id, list)
    }
    return grouped
  }, [factories])

  return (
    <div className="page">
      <h1>{region ? region.name : isAdmin ? 'All Regions' : 'Region Dashboard'}</h1>
      <p className="page-subtitle">{isAdmin ? "Every region's factories." : "Your region's factories."}</p>

      {error && <div className="empty error-text">{error}</div>}
      {!error && factories.length === 0 && <div className="empty">No factories yet.</div>}

      {isAdmin
        ? [...factoriesByRegion.entries()].map(([regionId, regionFactories]) => (
            <section className="section" key={regionId}>
              <h2 className="region-section-title">{regionName(regionId)}</h2>
              <div className="factory-grid">
                {regionFactories.map((factory) => (
                  <FactoryTile key={factory.id} factory={factory} status={factoryStatus[factory.id]} />
                ))}
              </div>
            </section>
          ))
        : factories.length > 0 && (
            <section className="section">
              <h2>Factories</h2>
              <div className="factory-grid">
                {factories.map((factory) => (
                  <FactoryTile key={factory.id} factory={factory} status={factoryStatus[factory.id]} />
                ))}
              </div>
            </section>
          )}
    </div>
  )
}
