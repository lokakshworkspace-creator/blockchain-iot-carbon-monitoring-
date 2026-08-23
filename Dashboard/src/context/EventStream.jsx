/**
 * Shared live-event buffer for the whole dashboard.
 *
 * socket.js already multiplexes one WebSocket to many listeners; this adds
 * the piece React needs on top of it - a single rolling buffer of recent
 * events that every page reads from, so Overview, Real-Time Data and
 * System Monitor all show the same history instead of each starting empty
 * when you navigate to it.
 *
 * The buffer is capped: this is a long-running demo page receiving an
 * event every couple of seconds, and an unbounded array would grow without
 * limit for no benefit - nothing in the UI looks further back than this.
 *
 * The context object and its hook live in eventStreamContext.js; this file
 * exports only the provider component so Fast Refresh can hot-swap it
 * without discarding the buffer.
 */

import { useEffect, useMemo, useRef, useState } from 'react'

import { subscribe, subscribeStatus } from '../services/socket.js'
import { EventStreamContext } from './eventStreamContext.js'

const MAX_EVENTS = 500

export function EventStreamProvider({ children }) {
  // Newest first: that is the order the feed renders in, and it lets
  // "most recent event of type X" lookups stop at the first match.
  const [events, setEvents] = useState([])
  const [status, setStatus] = useState('disconnected')

  // Monotonic id per event. The gateway does not assign one, and
  // timestamps can collide (several events are built within the same
  // millisecond in Pipeline B), so this is what React keys on.
  const nextId = useRef(0)

  useEffect(() => {
    const unsubscribe = subscribe((event) => {
      nextId.current += 1
      const withId = { ...event, _id: nextId.current, _receivedAt: Date.now() }
      setEvents((previous) => [withId, ...previous].slice(0, MAX_EVENTS))
    })
    return unsubscribe
  }, [])

  useEffect(() => subscribeStatus(setStatus), [])

  const value = useMemo(() => ({ events, status }), [events, status])

  return <EventStreamContext.Provider value={value}>{children}</EventStreamContext.Provider>
}
