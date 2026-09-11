/**
 * Turns the shared event buffer's SENSOR_READING events into chart-ready
 * points and the current reading - seeded with each device's recent
 * history from GET /api/readings so the chart isn't empty on
 * mount/reconnect/device-switch until the next live reading happens to
 * arrive.
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
 * explicit deviceId to filter to a single selected device - and history
 * is only fetched when a specific device is selected, for the same
 * reason: there is no single device to seed Overview's merged view from.
 */

import { useEffect, useMemo, useState } from 'react'

import { useEventStream } from '../context/eventStreamContext.js'
import { classify } from '../lib/levels.js'
import { getReadings } from '../services/api.js'

// Enough history to show a full demo sequence without the x-axis turning
// into an unreadable smear.
const MAX_LIVE_POINTS = 60
const HISTORY_LIMIT = 200

// A stable shared reference (not a fresh [] literal per render) so the
// "no device selected" case doesn't defeat the points useMemo below -
// every new array reference would otherwise count as "changed" on every
// render, even though the value never does.
const EMPTY_POINTS = []

export function useReadings(thresholds, deviceId = null) {
  const { events } = useEventStream()

  // The historical seed, fetched once per selected device - NOT replaced
  // by live points arriving afterward, only appended to (see `points`
  // below). Stored without `level`: classify() is applied at merge time
  // against whatever `thresholds` currently is, so a seed fetched before
  // useThresholds() resolves doesn't get stuck showing UNKNOWN forever.
  const [historicalPoints, setHistoricalPoints] = useState([])

  useEffect(() => {
    // No synchronous setState for the "nothing selected" case - see
    // `seededHistoricalPoints` below, which derives [] for that case
    // during render instead of writing it here as a side effect.
    if (deviceId === null) return
    let cancelled = false
    getReadings(deviceId, HISTORY_LIMIT)
      .then((rows) => {
        if (cancelled) return
        setHistoricalPoints(
          rows.map((row) => ({
            time: new Date(row.sensor_timestamp).toLocaleTimeString([], { hour12: false }),
            co2: row.co2,
          })),
        )
      })
      .catch(() => {
        // History is a nice-to-have hydration, not a requirement - the
        // live buffer alone still renders correctly, so this fails
        // silently rather than adding a second error UI next to
        // useThresholds'/useDevices' own.
        if (!cancelled) setHistoricalPoints([])
      })
    return () => {
      cancelled = true
    }
  }, [deviceId])

  // Masks a stale seed from a previously-selected device the instant
  // deviceId goes back to null, without needing a matching effect run to
  // clear it first.
  const seededHistoricalPoints = deviceId === null ? EMPTY_POINTS : historicalPoints

  const livePoints = useMemo(() => {
    const readings = events.filter(
      (event) =>
        event.event_type === 'SENSOR_READING' &&
        event.data &&
        (deviceId === null || event.device_id === deviceId),
    )
    return readings
      .slice(0, MAX_LIVE_POINTS)
      .reverse()
      .map((event) => ({
        time: new Date(event.timestamp).toLocaleTimeString([], { hour12: false }),
        co2: event.data.co2,
      }))
  }, [events, deviceId])

  // historicalPoints are all strictly older than anything livePoints can
  // hold (the fetch above runs once, at mount/device-switch, before any
  // live point for this device exists) - so this concatenation is already
  // in chronological order with no sort needed. The seed is appended to,
  // never replaced or dropped, by whatever arrives live afterward.
  const points = useMemo(
    () => [...seededHistoricalPoints, ...livePoints].map((p) => ({ ...p, level: classify(p.co2, thresholds) })),
    [seededHistoricalPoints, livePoints, thresholds],
  )

  const current = points.length > 0 ? points[points.length - 1] : null

  return { points, current, level: current ? current.level : 'UNKNOWN' }
}
