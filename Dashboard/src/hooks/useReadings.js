/**
 * Turns the shared event buffer's SENSOR_READING events into chart-ready
 * points and the current reading.
 *
 * Extracted because Real-Time Data and Overview both need "what is the
 * latest reading and what level is it" - and because the filtering has a
 * detail worth stating once rather than twice: the buffer is newest-first,
 * so it must be reversed for the chart, and only events carrying a `data`
 * payload count (older event types have no `data` key at all).
 *
 * deviceId is optional and defaults to no filtering - every reading from
 * every device is merged into one series, which is Overview's existing
 * "latest reading, whoever sent it" glance behavior and stays unchanged
 * on purpose (Overview shows a single most-recent value, not a chart
 * line, so merging devices there is not the misleading-line-series
 * problem a multi-device chart would have). Real-Time Data's chart is
 * the one place multiple devices' readings genuinely must not be merged
 * silently into what looks like one device's line, so it passes an
 * explicit deviceId to filter to a single selected device.
 */

import { useMemo } from 'react'

import { useEventStream } from '../context/eventStreamContext.js'
import { classify } from '../lib/levels.js'

// Enough history to show a full demo sequence without the x-axis turning
// into an unreadable smear.
const MAX_POINTS = 60

export function useReadings(thresholds, deviceId = null) {
  const { events } = useEventStream()

  const points = useMemo(() => {
    const readings = events.filter(
      (event) =>
        event.event_type === 'SENSOR_READING' &&
        event.data &&
        (deviceId === null || event.device_id === deviceId),
    )
    return readings
      .slice(0, MAX_POINTS)
      .reverse()
      .map((event) => ({
        time: new Date(event.timestamp).toLocaleTimeString([], { hour12: false }),
        co2: event.data.co2,
        level: classify(event.data.co2, thresholds),
      }))
  }, [events, thresholds, deviceId])

  const current = points.length > 0 ? points[points.length - 1] : null

  return { points, current, level: current ? current.level : 'UNKNOWN' }
}
