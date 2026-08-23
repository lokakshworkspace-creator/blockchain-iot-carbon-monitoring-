/**
 * Real-Time Data - the live CO2 view: current reading, its level against
 * the configured thresholds, the gateway's current alert state, and a
 * rolling chart of recent readings.
 *
 * Everything here is driven off the shared EventStream context, so this
 * page adds no second WebSocket connection - it reads the same buffer the
 * System Monitor does. The reading derivation, threshold fetch and alert
 * state all come from shared hooks/lib modules that Overview uses too.
 */

import { useMemo } from 'react'

import Co2Chart from '../components/Co2Chart.jsx'
import Co2Gauge from '../components/Co2Gauge.jsx'
import { useEventStream } from '../context/eventStreamContext.js'
import { useReadings } from '../hooks/useReadings.js'
import { useThresholds } from '../hooks/useThresholds.js'
import { currentAlertState } from '../lib/alerts.js'
import { LEVEL_COLOR } from '../lib/levels.js'

export default function RealTimeData() {
  const { events } = useEventStream()
  const { thresholds, error: thresholdError } = useThresholds()
  const { points, current, level } = useReadings(thresholds)

  const alertState = useMemo(() => currentAlertState(events), [events])

  return (
    <div className="page">
      <h1>Real-Time Data</h1>
      <p className="page-subtitle">Live CO₂ readings streamed from the gateway as each one arrives.</p>

      {thresholdError && <div className="empty error-text">{thresholdError}</div>}

      <section className="section">
        <div className="stat-row">
          <div className="card stat-card">
            <div className="stat-label">Current reading</div>
            <div className="stat-value" style={{ color: LEVEL_COLOR[level] ?? 'var(--text)' }}>
              {current ? current.co2 : '—'}
              <span className="stat-unit">ppm</span>
            </div>
            <div className="stat-sub">{current ? `at ${current.time}` : 'waiting for first reading'}</div>
          </div>

          <div className="card stat-card">
            <div className="stat-label">Level</div>
            <div className="stat-value" style={{ color: LEVEL_COLOR[level] ?? 'var(--text-dim)' }}>
              {level}
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
          <Co2Gauge co2={current?.co2} level={level} thresholds={thresholds} />
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
