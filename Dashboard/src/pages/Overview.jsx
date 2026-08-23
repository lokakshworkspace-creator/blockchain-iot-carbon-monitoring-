/**
 * Overview - the "glance and know the system's state" page.
 *
 * Deliberately thin: it introduces no data source of its own. The current
 * reading comes from the same useReadings hook Real-Time Data uses, the
 * status rollup is rollupHealth() applied to exactly the deriveHealth()
 * output System Monitor renders, and the alerts come from the shared
 * event buffer via lib/alerts.js. The only thing fetched just for this
 * page is GET /records/stats, which is two integers.
 */

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { useEventStream } from '../context/eventStreamContext.js'
import { useDevices } from '../hooks/useDevices.js'
import { useReadings } from '../hooks/useReadings.js'
import { useThresholds } from '../hooks/useThresholds.js'
import { useTick } from '../hooks/useTick.js'
import { activeAlerts, recentAlerts } from '../lib/alerts.js'
import { deriveHealth, rollupHealth } from '../lib/health.js'
import { LEVEL_COLOR } from '../lib/levels.js'
import { getRecordStats } from '../services/api.js'

const ROLLUP_HEADLINE = {
  ok: 'All systems normal',
  warn: 'Degraded',
  error: 'Attention needed',
  unknown: 'Awaiting data',
}

const SHORTCUTS = [
  { to: '/realtime', label: 'Real-Time Data', hint: 'Live chart and gauge' },
  { to: '/verification', label: 'Verification', hint: 'Check a record against the chain' },
  { to: '/blockchain', label: 'Blockchain Logs', hint: 'Anchored transactions' },
  { to: '/system', label: 'System Monitor', hint: 'Component health and raw feed' },
]

function formatTime(isoTimestamp) {
  const date = new Date(isoTimestamp)
  return Number.isNaN(date.getTime()) ? isoTimestamp : date.toLocaleTimeString([], { hour12: false })
}

export default function Overview() {
  const { events, status } = useEventStream()
  const { devices } = useDevices()
  const { thresholds } = useThresholds()
  const { current, level } = useReadings(thresholds)
  const tick = useTick()

  const [stats, setStats] = useState(null)

  // Refetched as readings are stored, so the counts track the demo rather
  // than showing whatever was true when the page first loaded.
  const storedCount = useMemo(
    () => events.filter((e) => e.event_type === 'DATABASE_STORED').length,
    [events],
  )

  useEffect(() => {
    let cancelled = false
    getRecordStats()
      .then((data) => {
        if (!cancelled) setStats(data)
      })
      .catch(() => {
        if (!cancelled) setStats(null)
      })
    return () => {
      cancelled = true
    }
  }, [storedCount])

  const rollup = useMemo(
    () => rollupHealth(deriveHealth(events, status, devices, Date.now())),
    // `tick` is intentionally a dependency: health.js has time-based
    // states, so the rollup has to be recomputed on a clock, not only
    // when an event arrives. Same interval as System Monitor's.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [events, status, devices, tick],
  )

  const alerts = useMemo(() => recentAlerts(events), [events])
  const active = useMemo(() => activeAlerts(events), [events])

  const onlineCount = devices.filter((device) => device.online).length

  return (
    <div className="page">
      <h1>Overview</h1>
      <p className="page-subtitle">System status at a glance, from the same live data the other pages use.</p>

      <section className="section">
        <div className={`card rollup state-${rollup.state}`}>
          <div className="rollup-main">
            <span className="health-dot" />
            <div>
              <div className="rollup-headline">{ROLLUP_HEADLINE[rollup.state]}</div>
              <div className="rollup-summary">{rollup.summary}</div>
            </div>
          </div>
          <div className="rollup-counts">
            <span className="pill pill-ok">{rollup.counts.ok} healthy</span>
            {rollup.counts.warn > 0 && <span className="pill pill-warn">{rollup.counts.warn} degraded</span>}
            {rollup.counts.error > 0 && <span className="pill pill-error">{rollup.counts.error} problem</span>}
            {rollup.counts.unknown > 0 && <span className="pill">{rollup.counts.unknown} unknown</span>}
          </div>
        </div>
      </section>

      <section className="section">
        <div className="stat-row">
          <div className="card stat-card">
            <div className="stat-label">Current CO₂</div>
            <div className="stat-value" style={{ color: LEVEL_COLOR[level] ?? 'var(--text)' }}>
              {current ? current.co2 : '—'}
              <span className="stat-unit">ppm</span>
            </div>
            <div className="stat-sub">{current ? `${level} · at ${current.time}` : 'waiting for first reading'}</div>
          </div>

          <div className="card stat-card">
            <div className="stat-label">Anchored on-chain</div>
            <div className="stat-value">{stats ? stats.anchored : '—'}</div>
            <div className="stat-sub">{stats ? `of ${stats.total} readings stored` : 'loading…'}</div>
          </div>

          <div className="card stat-card">
            <div className="stat-label">Devices online</div>
            <div className="stat-value">
              {onlineCount}
              <span className="stat-unit">{`of ${devices.length}`}</span>
            </div>
            <div className="stat-sub">{devices.length === 0 ? 'none reporting yet' : 'reporting to the gateway'}</div>
          </div>

          <div className="card stat-card">
            <div className="stat-label">Active alerts</div>
            <div className="stat-value" style={{ color: active.total > 0 ? LEVEL_COLOR.CRITICAL : undefined }}>
              {active.total}
            </div>
            <div className="stat-sub">
              {active.tamperCount > 0 ? `${active.tamperCount} tampering detected` : 'threshold alerts open'}
            </div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Recent alerts</h2>
          <Link className="chip" to="/system">
            View full feed
          </Link>
        </div>
        <div className="card">
          {alerts.length === 0 ? (
            <div className="empty">No threshold or tampering events yet.</div>
          ) : (
            <div className="feed">
              {alerts.map((alert) => (
                <div key={alert._id} className={`feed-row alert-row sev-${alert.severity}`}>
                  <span className="feed-time">{formatTime(alert.timestamp)}</span>
                  <span className={`badge badge-${alert.severity}`}>{alert.severity}</span>
                  <span className="feed-message">{alert.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="section">
        <h2>Go to</h2>
        <div className="shortcuts">
          {SHORTCUTS.map((shortcut) => (
            <Link key={shortcut.to} to={shortcut.to} className="card shortcut">
              <span className="shortcut-label">{shortcut.label}</span>
              <span className="shortcut-hint">{shortcut.hint}</span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}
