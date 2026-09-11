/**
 * GET /api/analytics/{deviceId}?days=N for the "Last 7 Days" panel.
 * Independent of the live event buffer and of useReadings' historical
 * seed - this is pre-aggregated server-side (Mongo's own $group), not
 * derived from a client-side readings array, so a long window stays cheap
 * regardless of how many raw readings back it.
 *
 * No separate loading flag, matching useDevices()/useThresholds() - this
 * codebase's convention is that the caller's own empty state doubles as
 * "still loading" (WeeklyAnalytics' `days.length === 0` branch), rather
 * than every fetch hook carrying its own loading boolean.
 */

import { useEffect, useState } from 'react'

import { getAnalytics } from '../services/api.js'

const EMPTY_DAYS = []

export function useAnalytics(deviceId, days = 7) {
  const [data, setData] = useState(EMPTY_DAYS)
  const [error, setError] = useState(null)

  useEffect(() => {
    // No synchronous setState for the "nothing selected" case - the
    // return statement below derives empty output for it at render time
    // instead of writing that here as a side effect.
    if (deviceId === null) return
    let cancelled = false
    getAnalytics(deviceId, days)
      .then((rows) => {
        if (cancelled) return
        setData(rows)
        setError(null)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [deviceId, days])

  if (deviceId === null) {
    return { data: EMPTY_DAYS, error: null }
  }
  return { data, error }
}
