/**
 * System Monitor - the operational view of the whole stack, and the page
 * to open first when anything looks wrong elsewhere in the dashboard.
 *
 * Three sections: derived component health, the device roster from
 * GET /devices/status, and the raw live event feed.
 */

import { useEffect, useMemo, useState } from 'react'

import DeviceTable from '../components/DeviceTable.jsx'
import EventFeed from '../components/EventFeed.jsx'
import HealthGrid from '../components/HealthGrid.jsx'
import { useEventStream } from '../context/eventStreamContext.js'
import { deriveHealth } from '../lib/health.js'
import { getDeviceStatus } from '../services/api.js'

const SEVERITIES = ['ALL', 'INFO', 'WARNING', 'CRITICAL']

// Health tiles and "last seen" ages are time-dependent, so the page needs
// to re-render on a clock as well as on new events - otherwise a system
// that goes quiet keeps claiming it saw traffic "just now" indefinitely.
const TICK_MS = 5000

export default function SystemMonitor() {
  const { events, status } = useEventStream()

  const [devices, setDevices] = useState([])
  const [deviceError, setDeviceError] = useState(null)
  const [severityFilter, setSeverityFilter] = useState('ALL')
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), TICK_MS)
    return () => clearInterval(id)
  }, [])

  // Refetch the roster whenever the gateway reports a liveness change, so
  // the table tracks DEVICE_ONLINE/DEVICE_OFFLINE without polling hard.
  const deviceEventCount = useMemo(
    () => events.filter((e) => e.event_type === 'DEVICE_ONLINE' || e.event_type === 'DEVICE_OFFLINE').length,
    [events],
  )

  useEffect(() => {
    let cancelled = false
    getDeviceStatus()
      .then((data) => {
        if (cancelled) return
        setDevices(data)
        setDeviceError(null)
      })
      .catch((err) => {
        if (!cancelled) setDeviceError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [deviceEventCount])

  const health = useMemo(
    () => deriveHealth(events, status, devices, Date.now()),
    // `tick` is intentionally a dependency: it is what makes the
    // time-based states (e.g. "no messages in the last 30s") update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [events, status, devices, tick],
  )

  const visibleEvents = useMemo(
    () => (severityFilter === 'ALL' ? events : events.filter((e) => e.severity === severityFilter)),
    [events, severityFilter],
  )

  return (
    <div className="page">
      <h1>System Monitor</h1>
      <p className="page-subtitle">
        Live health of all four layers, derived from the gateway&apos;s own event stream.
      </p>

      <section className="section">
        <h2>Component health</h2>
        <HealthGrid components={health} />
      </section>

      <section className="section">
        <h2>Devices</h2>
        <div className="card">
          <DeviceTable devices={devices} error={deviceError} />
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Live event feed</h2>
          <div className="filters">
            {SEVERITIES.map((severity) => (
              <button
                key={severity}
                type="button"
                className={severityFilter === severity ? 'chip active' : 'chip'}
                onClick={() => setSeverityFilter(severity)}
              >
                {severity}
              </button>
            ))}
            <span className="dim count">
              {visibleEvents.length} of {events.length}
            </span>
          </div>
        </div>
        <div className="card">
          <EventFeed events={visibleEvents} />
        </div>
      </section>
    </div>
  )
}
