/**
 * Real-Time Data - the live CO2 view: current reading, its level against
 * the configured thresholds, the gateway's current alert state, and a
 * rolling chart of recent readings.
 *
 * Everything here is driven off the shared EventStream context, so this
 * page adds no second WebSocket connection - it reads the same buffer the
 * System Monitor does. The reading derivation, threshold fetch and alert
 * state all come from shared hooks/lib modules that Overview uses too.
 *
 * With more than one device publishing, every stat here (current
 * reading, level, gauge, chart) is a single-value-per-device view, so
 * they all filter to one selected device rather than trying to show
 * several devices' current values at once - a device selector picks
 * which one, defaulting to the first device seen. This is what keeps
 * the chart from silently interleaving two devices' readings into one
 * misleading line.
 */

import { useMemo, useState } from 'react'

import Co2Chart from '../components/Co2Chart.jsx'
import Co2Gauge from '../components/Co2Gauge.jsx'
import { useEventStream } from '../context/eventStreamContext.js'
import { useDevices } from '../hooks/useDevices.js'
import { useReadings } from '../hooks/useReadings.js'
import { useThresholds } from '../hooks/useThresholds.js'
import { currentAlertState } from '../lib/alerts.js'
import { LEVEL_COLOR } from '../lib/levels.js'

export default function RealTimeData() {
  const { events } = useEventStream()
  const { devices } = useDevices()
  const { thresholds, error: thresholdError } = useThresholds()

  // manualSelection is null until the user picks something from the
  // dropdown; until then, selectedDeviceId derives straight from the
  // roster during render - no effect needed, since GET /devices/status
  // returns devices in first-seen order (a plain Python dict preserves
  // insertion order), so "the first device" is already stable across
  // refetches without needing to be locked in separately.
  const [manualSelection, setManualSelection] = useState(null)
  const selectedDeviceId = manualSelection ?? devices[0]?.device_id ?? null

  const { points, current, level } = useReadings(thresholds, selectedDeviceId)

  // THRESHOLD_* events always carry the device_id that triggered them
  // (threshold.py's build_event never omits it), so filtering to the
  // selected device is enough to get that device's own alert state -
  // otherwise a second device's CRITICAL alert could show up while
  // looking at the first device's NORMAL chart.
  const alertState = useMemo(
    () => currentAlertState(events.filter((e) => e.device_id === selectedDeviceId)),
    [events, selectedDeviceId],
  )

  return (
    <div className="page">
      <div className="section-head">
        <div>
          <h1>Real-Time Data</h1>
          <p className="page-subtitle">Live CO₂ readings streamed from the gateway as each one arrives.</p>
        </div>
        <select
          className="device-select"
          value={selectedDeviceId ?? ''}
          disabled={devices.length === 0}
          onChange={(e) => setManualSelection(e.target.value)}
        >
          {devices.length === 0 && <option value="">No devices yet</option>}
          {devices.map((device) => (
            <option key={device.device_id} value={device.device_id}>
              {device.device_id} {device.online ? '●' : '○'}
            </option>
          ))}
        </select>
      </div>

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
