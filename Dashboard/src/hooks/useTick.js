/**
 * Re-renders on an interval.
 *
 * health.js's derivations are time-dependent ("no messages in the last
 * 30s"), so a page showing them needs a clock as well as an event
 * subscription - otherwise a system that goes quiet keeps claiming it saw
 * traffic just now, indefinitely. Both System Monitor and Overview use
 * this at the same interval so their health states change over at the
 * same moment.
 */

import { useEffect, useState } from 'react'

export const HEALTH_TICK_MS = 5000

export function useTick(intervalMs = HEALTH_TICK_MS) {
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setTick((value) => value + 1), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])

  return tick
}
