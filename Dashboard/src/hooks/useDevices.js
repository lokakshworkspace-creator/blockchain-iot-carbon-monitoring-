/**
 * Device roster from GET /devices/status, refetched whenever the gateway
 * reports a liveness change rather than polled on a timer.
 *
 * Shared by System Monitor and Overview specifically so both pages feed
 * deriveHealth() the same device data. If each page fetched on its own
 * schedule they could briefly render different answers to "is the sensor
 * online", which is exactly the kind of disagreement that makes a
 * dashboard untrustworthy.
 */

import { useEffect, useMemo, useState } from 'react'

import { useEventStream } from '../context/eventStreamContext.js'
import { getDeviceStatus } from '../services/api.js'

export function useDevices() {
  const { events } = useEventStream()
  const [devices, setDevices] = useState([])
  const [error, setError] = useState(null)

  const deviceEventCount = useMemo(
    () =>
      events.filter((e) => e.event_type === 'DEVICE_ONLINE' || e.event_type === 'DEVICE_OFFLINE').length,
    [events],
  )

  useEffect(() => {
    let cancelled = false
    getDeviceStatus()
      .then((data) => {
        if (cancelled) return
        setDevices(data)
        setError(null)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [deviceEventCount])

  return { devices, error }
}
