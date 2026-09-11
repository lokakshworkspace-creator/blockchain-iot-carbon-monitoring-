/**
 * WebSocket client for the gateway's authenticated, region-scoped
 * /ws/notifications (Phase 6) - a deliberately separate connection from
 * socket.js's /ws (see Gateway/routers/notifications.py's module
 * docstring for why). Same module-level-singleton, same exponential
 * backoff shape as socket.js, for the same reasons - this file exists
 * instead of extending socket.js only because the two sockets need
 * different URLs (one carries a token, one doesn't) and different retry
 * behavior (see below).
 *
 * Requires a token (see api.js's TOKEN_STORAGE_KEY - the temporary
 * manual-token unblock, not a real login flow yet). Without one, the
 * gateway rejects the handshake with a 403 before any WebSocket frame
 * exchange happens at all - connect() still retries with the same
 * backoff as any other disconnect, so setting a token later (via the
 * devtools console) is picked up on the next automatic retry with no
 * page reload needed.
 */

import { getStoredToken, GATEWAY_URL } from './api.js'

const WS_URL_BASE = `${GATEWAY_URL.replace(/^http/, 'ws')}/ws/notifications`

const INITIAL_RECONNECT_DELAY_MS = 1000
const MAX_RECONNECT_DELAY_MS = 15000

/** @type {WebSocket | null} */
let socket = null
let reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS
let reconnectTimer = null

const notificationListeners = new Set()
const statusListeners = new Set()

/** 'connecting' | 'connected' | 'disconnected' */
let status = 'disconnected'

function setStatus(next) {
  if (status === next) return
  status = next
  for (const listener of statusListeners) {
    listener(status)
  }
}

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return
  }

  const token = getStoredToken()
  if (!token) {
    // Nothing to authenticate with yet - don't even attempt the
    // handshake (it would just 403). scheduleReconnect() keeps checking
    // periodically so setting a token later still connects automatically.
    setStatus('disconnected')
    scheduleReconnect()
    return
  }

  setStatus('connecting')
  socket = new WebSocket(`${WS_URL_BASE}?token=${encodeURIComponent(token)}`)

  socket.onopen = () => {
    reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS
    setStatus('connected')
  }

  socket.onmessage = (raw) => {
    let notification
    try {
      notification = JSON.parse(raw.data)
    } catch {
      console.warn('[notificationSocket] ignoring unparseable frame:', raw.data)
      return
    }
    for (const listener of notificationListeners) {
      try {
        listener(notification)
      } catch (err) {
        console.error('[notificationSocket] listener threw:', err)
      }
    }
  }

  socket.onerror = () => {
    console.warn('[notificationSocket] connection error')
  }

  socket.onclose = () => {
    setStatus('disconnected')
    socket = null
    scheduleReconnect()
  }
}

function scheduleReconnect() {
  if (reconnectTimer !== null) return

  const delay = reconnectDelayMs
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connect()
  }, delay)

  reconnectDelayMs = Math.min(reconnectDelayMs * 2, MAX_RECONNECT_DELAY_MS)
}

/**
 * Subscribe to every notification pushed live for this user's room
 * (their region, or every region for an admin - decided server-side).
 * @param {(notification: object) => void} listener
 * @returns {() => void} unsubscribe
 */
export function subscribeNotifications(listener) {
  notificationListeners.add(listener)
  connect()
  return () => notificationListeners.delete(listener)
}

/**
 * @param {(status: string) => void} listener
 * @returns {() => void} unsubscribe
 */
export function subscribeNotificationStatus(listener) {
  statusListeners.add(listener)
  listener(status)
  connect()
  return () => statusListeners.delete(listener)
}
