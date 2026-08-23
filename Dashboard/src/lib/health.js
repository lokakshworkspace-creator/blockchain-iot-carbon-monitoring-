/**
 * Derives component health for the System Monitor from data we can
 * actually observe - the WebSocket connection state, the event stream, and
 * GET /devices/status.
 *
 * The gateway exposes no per-component health check (there is no
 * /health/mongodb, and adding fake ones would be worse than useless in a
 * project whose whole point is trustworthy data). So every indicator here
 * is inferred from real evidence, and anything not yet evidenced is
 * reported as 'unknown' rather than being guessed at as healthy. A quiet
 * system must never render as a broken one, and a broken one must never
 * render as healthy.
 *
 * States: 'ok' | 'warn' | 'error' | 'unknown'
 */

// How long after the last observed message a traffic-based indicator stops
// counting as active. Matches the gateway's DEVICE_TIMEOUT_SECONDS (30s)
// so the MQTT and device indicators agree rather than contradicting.
const ACTIVITY_WINDOW_MS = 30_000

const MQTT_TRAFFIC_EVENTS = new Set([
  'DEVICE_ONLINE',
  'DEVICE_OFFLINE',
  'HASH_GENERATED',
  'THRESHOLD_WARNING',
  'THRESHOLD_CRITICAL',
  'THRESHOLD_RESOLVED',
])

/** Newest-first array assumed, so the first match is the most recent. */
function latest(events, predicate) {
  return events.find(predicate)
}

function isRecent(event, now) {
  return event !== undefined && now - event._receivedAt < ACTIVITY_WINDOW_MS
}

/**
 * @param {object[]} events    newest-first event buffer
 * @param {string}   socketStatus  'connected' | 'connecting' | 'disconnected'
 * @param {object[]} devices   GET /devices/status snapshot
 * @param {number}   now       Date.now(), passed in so this stays pure/testable
 */
export function deriveHealth(events, socketStatus, devices, now = Date.now()) {
  return [
    gateway(socketStatus),
    mqtt(events, now),
    esp32(devices, events),
    mongodb(events),
    ethereum(events),
  ]
}

function gateway(socketStatus) {
  // The only directly-observed component: if the WebSocket is open, the
  // FastAPI process is up and its event loop is running, by definition.
  if (socketStatus === 'connected') {
    return { name: 'FastAPI Gateway', state: 'ok', detail: 'WebSocket connected' }
  }
  if (socketStatus === 'connecting') {
    return { name: 'FastAPI Gateway', state: 'warn', detail: 'Connecting…' }
  }
  return { name: 'FastAPI Gateway', state: 'error', detail: 'No WebSocket connection' }
}

function mqtt(events, now) {
  // No direct broker health available. What we can prove is delivery: any
  // event that only exists because an MQTT message arrived is evidence the
  // broker -> bridge -> gateway path works.
  const traffic = latest(events, (e) => MQTT_TRAFFIC_EVENTS.has(e.event_type))

  if (traffic === undefined) {
    return { name: 'MQTT Broker', state: 'unknown', detail: 'No messages observed yet' }
  }
  if (isRecent(traffic, now)) {
    return { name: 'MQTT Broker', state: 'ok', detail: 'Delivering messages' }
  }
  return { name: 'MQTT Broker', state: 'warn', detail: 'No messages in the last 30s' }
}

function esp32(devices, events) {
  // Device liveness is the gateway's own judgement (device_status.py), so
  // this reflects GET /devices/status rather than re-deriving a timeout.
  if (devices.length === 0) {
    return { name: 'ESP32 Sensor', state: 'unknown', detail: 'No device has reported yet' }
  }

  const online = devices.filter((d) => d.online)
  if (online.length === devices.length) {
    const names = devices.map((d) => d.device_id).join(', ')
    return { name: 'ESP32 Sensor', state: 'ok', detail: `Online: ${names}` }
  }
  if (online.length === 0) {
    const offlineEvent = latest(events, (e) => e.event_type === 'DEVICE_OFFLINE')
    return {
      name: 'ESP32 Sensor',
      state: 'error',
      detail: offlineEvent?.message ?? 'All devices offline',
    }
  }
  return {
    name: 'ESP32 Sensor',
    state: 'warn',
    detail: `${online.length}/${devices.length} devices online`,
  }
}

function mongodb(events) {
  // Pipeline B reports its own storage outcome per reading, so the newest
  // of these two events is the current truth.
  const newest = latest(events, (e) => e.event_type === 'DATABASE_STORED' || e.event_type === 'DATABASE_ERROR')

  if (newest === undefined) {
    return { name: 'MongoDB', state: 'unknown', detail: 'No writes observed yet' }
  }
  if (newest.event_type === 'DATABASE_ERROR') {
    return { name: 'MongoDB', state: 'error', detail: newest.message }
  }
  return { name: 'MongoDB', state: 'ok', detail: 'Last write succeeded' }
}

function ethereum(events) {
  const newest = latest(
    events,
    (e) =>
      e.event_type === 'BLOCKCHAIN_CONFIRMED' ||
      e.event_type === 'BLOCKCHAIN_FAILED' ||
      e.event_type === 'BLOCKCHAIN_SUBMITTED',
  )

  if (newest === undefined) {
    return { name: 'Ethereum (Sepolia)', state: 'unknown', detail: 'No anchoring observed yet' }
  }
  if (newest.event_type === 'BLOCKCHAIN_FAILED') {
    return { name: 'Ethereum (Sepolia)', state: 'error', detail: newest.message }
  }
  if (newest.event_type === 'BLOCKCHAIN_SUBMITTED') {
    // Sepolia confirmations routinely take a couple of minutes, so this is
    // the normal in-flight state, not a problem.
    return { name: 'Ethereum (Sepolia)', state: 'warn', detail: 'Transaction pending confirmation' }
  }
  return { name: 'Ethereum (Sepolia)', state: 'ok', detail: 'Last hash anchored on-chain' }
}
