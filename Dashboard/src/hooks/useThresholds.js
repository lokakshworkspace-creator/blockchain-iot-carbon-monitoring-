/**
 * Fetches the gateway's configured CO2 thresholds from GET /health.
 *
 * Shared by Real-Time Data and Overview so neither hardcodes the values -
 * they live in the gateway's .env, and a second copy in JavaScript would
 * silently drift the day someone retunes the thresholds.
 */

import { useEffect, useState } from 'react'

import { getHealth } from '../services/api.js'

export function useThresholds() {
  const [thresholds, setThresholds] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    getHealth()
      .then((health) => {
        if (cancelled) return
        setThresholds({
          warning: health.co2_warning_threshold,
          critical: health.co2_critical_threshold,
        })
        setError(null)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { thresholds, error }
}
