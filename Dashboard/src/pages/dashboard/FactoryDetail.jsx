/**
 * One factory's devices, with the same Live / Last 7 Days tabs
 * Real-Time Data (Phase 3) uses - reusing Co2Chart/WeeklyAnalytics/
 * useReadings/useAnalytics directly rather than duplicating that logic,
 * scoped to this factory's own device list (GET /api/factories/{id}/devices)
 * instead of every device the gateway has ever seen. A regional_head
 * hitting another region's factoryId gets the same 404
 * getFactoryDevices() already surfaces server-side - shown here as the
 * page's own error state, not a silent redirect.
 */

import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

import Co2Chart from '../../components/Co2Chart.jsx'
import Co2Gauge from '../../components/Co2Gauge.jsx'
import WeeklyAnalytics from '../../components/WeeklyAnalytics.jsx'
import { useAnalytics } from '../../hooks/useAnalytics.js'
import { useReadings } from '../../hooks/useReadings.js'
import { useThresholds } from '../../hooks/useThresholds.js'
import { getFactoryDevices } from '../../services/api.js'
import { LEVEL_COLOR } from '../../lib/levels.js'

const ANALYTICS_DAYS = 7
const CHART_TABS = [
  { key: 'live', label: 'Live' },
  { key: 'weekly', label: 'Last 7 Days' },
]

const EMPTY_DEVICES = []

export default function FactoryDetail() {
  const { factoryId } = useParams()
  const { thresholds } = useThresholds()

  const [devices, setDevices] = useState(EMPTY_DEVICES)
  // Which factoryId `devices` was actually fetched for - lets the render
  // below tell "still showing the previous factory's devices while this
  // one loads" apart from "this factory's devices, fetched" without a
  // synchronous reset in the effect (see useReadings.js's
  // seededHistoricalPoints for the same pattern).
  const [devicesFactoryId, setDevicesFactoryId] = useState(null)
  const [error, setError] = useState(null)
  // {factoryId, deviceId} rather than a bare deviceId, so switching
  // factories can't leak the previous factory's manual selection into
  // this one's device list purely by deriving it away at render time.
  const [manualSelection, setManualSelection] = useState(null)
  const [chartTab, setChartTab] = useState('live')

  useEffect(() => {
    let cancelled = false
    getFactoryDevices(factoryId)
      .then((rows) => {
        if (cancelled) return
        setDevices(rows)
        setDevicesFactoryId(factoryId)
        setError(null)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err.message)
        setDevicesFactoryId(factoryId)
      })
    return () => {
      cancelled = true
    }
  }, [factoryId])

  const effectiveDevices = devicesFactoryId === factoryId ? devices : EMPTY_DEVICES
  const manualDeviceId = manualSelection?.factoryId === factoryId ? manualSelection.deviceId : null
  const selectedDeviceId = manualDeviceId ?? effectiveDevices[0]?.device_id ?? null
  const { points, current, level } = useReadings(thresholds, selectedDeviceId)
  const { data: weeklyData, error: weeklyError } = useAnalytics(selectedDeviceId, ANALYTICS_DAYS)

  return (
    <div className="page">
      <div className="section-head">
        <h1>Factory devices</h1>
        {effectiveDevices.length > 0 && (
          <select
            className="device-select"
            value={selectedDeviceId ?? ''}
            onChange={(event) => setManualSelection({ factoryId, deviceId: event.target.value })}
          >
            {effectiveDevices.map((device) => (
              <option key={device.id} value={device.device_id}>
                {device.device_id} {device.is_hardware ? '(hardware)' : '(simulated)'}
              </option>
            ))}
          </select>
        )}
      </div>

      {error && <div className="empty error-text">{error}</div>}
      {!error && effectiveDevices.length === 0 && (
        <div className="empty">No devices registered to this factory yet.</div>
      )}

      {effectiveDevices.length > 0 && (
        <>
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
              <h2>{chartTab === 'live' ? 'Recent readings (ppm)' : `Last ${ANALYTICS_DAYS} days (ppm)`}</h2>
              <div className="filters">
                {CHART_TABS.map(({ key, label }) => (
                  <button
                    key={key}
                    type="button"
                    className={chartTab === key ? 'chip active' : 'chip'}
                    onClick={() => setChartTab(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <div className="card card-pad">
              {chartTab === 'live' ? (
                <Co2Chart points={points} thresholds={thresholds} />
              ) : (
                <WeeklyAnalytics days={weeklyData} thresholds={thresholds} error={weeklyError} />
              )}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
