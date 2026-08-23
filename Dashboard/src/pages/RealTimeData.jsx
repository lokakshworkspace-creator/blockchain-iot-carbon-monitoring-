/**
 * Real-Time Data - the live CO2 view: current reading, its level against
 * the configured thresholds, the gateway's current alert state, and a
 * rolling chart of recent readings.
 *
 * Everything here is driven off the shared EventStream context, so this
 * page adds no second WebSocket connection - it reads the same buffer the
 * System Monitor does.
 */

import { useEffect, useMemo, useState } from 'react'

import Co2Chart from '../components/Co2Chart.jsx'
import Co2Gauge from '../components/Co2Gauge.jsx'
import { useEventStream } from '../context/eventStreamContext.js'
import { LEVEL_COLOR, classify } from '../lib/levels.js'
import { getHealth } from '../services/api.js'

// Enough history to show a full demo sequence without the x-axis turning
// into an unreadable smear.
const MAX_POINTS = 60

const ALERT_LABEL = {
  THRESHOLD_WARNING: 'WARNING alert active',
  THRESHOLD_CRITICAL: 'CRITICAL alert active',
  THRESHOLD_RESOLVED: 'No active alert',
}

export default function RealTimeData() {
  const { events } = useEventStream()
  const [thresholds, setThresholds] = useState(null)
  const [healthError, setHealthError] = useState(null)

  useEffect(() => {
    let cancelled = false
    getHealth()
      .then((health) => {
        if (cancelled) return
        setThresholds({
          warning: health.co2_warning_threshold,
          critical: health.co2_critical_threshold,
        })
        setHealthError(null)
      })
      .catch((err) => {
        if (!cancelled) setHealthError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // SENSOR_READING is emitted once per reading, so this is every data
  // point the gateway has seen since the page connected - reversed into
  // chronological order for the chart.
  const points = useMemo(() => {
    const readings = events.filter((e) => e.event_type === 'SENSOR_READING' && e.data)
    return readings
      .slice(0, MAX_POINTS)
      .reverse()
      .map((e) => ({
        time: new Date(e.timestamp).toLocaleTimeString([], { hour12: false }),
        co2: e.data.co2,
        level: classify(e.data.co2, thresholds),
      }))
  }, [events, thresholds])

  const current = points.length > 0 ? points[points.length - 1] : null
  const currentLevel = current ? current.level : 'UNKNOWN'

  // The gateway's own alert state, taken from the most recent threshold
  // event rather than re-derived here - threshold.py owns cooldown and
  // hysteresis, and a second implementation in the browser would drift.
  const alertState = useMemo(() => {
    const event = events.find((e) => e.event_type?.startsWith('THRESHOLD_'))
    if (event === undefined) return 'No alerts yet'
    return ALERT_LABEL[event.event_type] ?? event.event_type
  }, [events])

  return (
    <div className="page">
      <h1>Real-Time Data</h1>
      <p className="page-subtitle">Live CO₂ readings streamed from the gateway as each one arrives.</p>

      {healthError && <div className="empty error-text">{healthError}</div>}

      <section className="section">
        <div className="stat-row">
          <div className="card stat-card">
            <div className="stat-label">Current reading</div>
            <div className="stat-value" style={{ color: LEVEL_COLOR[currentLevel] ?? 'var(--text)' }}>
              {current ? current.co2 : '—'}
              <span className="stat-unit">ppm</span>
            </div>
            <div className="stat-sub">{current ? `at ${current.time}` : 'waiting for first reading'}</div>
          </div>

          <div className="card stat-card">
            <div className="stat-label">Level</div>
            <div className="stat-value" style={{ color: LEVEL_COLOR[currentLevel] ?? 'var(--text-dim)' }}>
              {currentLevel}
            </div>
            <div className="stat-sub">
              {thresholds
                ? `warning ≥ ${thresholds.warning}, critical ≥ ${thresholds.critical} ppm`
                : 'loading thresholds…'}
            </div>
          </div>

          <div className="card stat-card">
            <div className="stat-label">Gateway alert state</div>
            <div className="stat-value small">{alertState}</div>
            <div className="stat-sub">with cooldown &amp; hysteresis applied</div>
          </div>
        </div>
      </section>

      <section className="section">
        <h2>Current level</h2>
        <div className="card card-pad">
          <Co2Gauge co2={current?.co2} level={currentLevel} thresholds={thresholds} />
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Recent readings (ppm)</h2>
          <span className="dim count">{points.length} points</span>
        </div>
        <div className="card card-pad">
          <Co2Chart points={points} thresholds={thresholds} />
        </div>
      </section>
    </div>
  )
}
