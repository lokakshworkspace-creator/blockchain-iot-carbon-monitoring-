/**
 * Turns the shared event buffer's SENSOR_READING events into chart-ready
 * points and the current reading.
 *
 * Extracted because Real-Time Data and Overview both need "what is the
 * latest reading and what level is it" - and because the filtering has a
 * detail worth stating once rather than twice: the buffer is newest-first,
 * so it must be reversed for the chart, and only events carrying a `data`
 * payload count (older event types have no `data` key at all).
 */

import { useMemo } from 'react'

import { useEventStream } from '../context/eventStreamContext.js'
import { classify } from '../lib/levels.js'

// Enough history to show a full demo sequence without the x-axis turning
// into an unreadable smear.
const MAX_POINTS = 60

export function useReadings(thresholds) {
  const { events } = useEventStream()

  const points = useMemo(() => {
    const readings = events.filter((event) => event.event_type === 'SENSOR_READING' && event.data)
    return readings
      .slice(0, MAX_POINTS)
      .reverse()
      .map((event) => ({
        time: new Date(event.timestamp).toLocaleTimeString([], { hour12: false }),
        co2: event.data.co2,
        level: classify(event.data.co2, thresholds),
      }))
  }, [events, thresholds])

  const current = points.length > 0 ? points[points.length - 1] : null

  return { points, current, level: current ? current.level : 'UNKNOWN' }
}
