/**
 * Thin wrapper around fetch() for the gateway's REST endpoints.
 *
 * Every call goes through _request() so error handling is uniform: a
 * non-2xx response or an unreachable gateway both surface as a thrown
 * Error with a readable message, which is what the pages render in their
 * error states. Components never touch fetch() or URLs directly.
 */

// Vite inlines import.meta.env at build time; the fallback keeps the app
// working with no .env file at all, which is the common case for a local
// demo run (gateway on :8000, dashboard dev server on :5173).
//
// The `?.` matters beyond defensiveness: it lets this module (and socket.js,
// which imports GATEWAY_URL from here) be imported directly by plain Node,
// where import.meta.env does not exist - which is how the WebSocket client
// is smoke-tested against a running gateway outside the browser.
export const GATEWAY_URL = (import.meta.env?.VITE_GATEWAY_URL ?? 'http://localhost:8000').replace(/\/$/, '')

// Stopgap until there's a real login page: every other endpoint this app
// calls predates the gateway's JWT auth (Phase 1/2) and needs no token,
// but GET /api/readings/{id} and GET /api/analytics/{id} (Phase 3) do.
// For now, set a token once per browser via the devtools console:
//   localStorage.setItem('carbon_monitor_token', '<paste a JWT from POST /api/auth/login>')
// and every request attaches it. Harmless to send on the unauthenticated
// endpoints too - they simply ignore any Authorization header.
const TOKEN_STORAGE_KEY = 'carbon_monitor_token'

function _authHeaders() {
  let token = null
  try {
    token = localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    // Some contexts (private browsing, a locked-down browser) throw on
    // localStorage access - degrade to "no token" rather than crash.
  }
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function _request(path, options = {}) {
  let response
  try {
    response = await fetch(`${GATEWAY_URL}${path}`, {
      ...options,
      headers: { ..._authHeaders(), ...options.headers },
    })
  } catch (cause) {
    // fetch() only rejects on a network-level failure (gateway not running,
    // DNS, CORS preflight refused) - never on an HTTP error status.
    throw new Error(`Cannot reach the gateway at ${GATEWAY_URL} - is it running?`, { cause })
  }

  if (!response.ok) {
    throw new Error(`${options.method ?? 'GET'} ${path} failed: ${response.status} ${response.statusText}`)
  }

  return response.json()
}

/** GET /health -> { status, mqtt_broker, mqtt_topic, ... } */
export function getHealth() {
  return _request('/health')
}

/** GET /devices/status -> [{ device_id, online, last_seen }, ...] */
export function getDeviceStatus() {
  return _request('/devices/status')
}

/** GET /records?limit=N -> [{ id, device_id, co2, sensor_timestamp, ... }, ...] newest first */
export function getRecords(limit = 20) {
  return _request(`/records?limit=${encodeURIComponent(limit)}`)
}

/** GET /records/stats -> { total, anchored } */
export function getRecordStats() {
  return _request('/records/stats')
}

/**
 * POST /verify/{id} -> { status, stored_hash, onchain_hash, recomputed_hash, ... }
 * status is one of Verified | Tampered | NotAnchored | NotFound | Error.
 */
export function verifyRecord(recordId) {
  return _request(`/verify/${encodeURIComponent(recordId)}`, { method: 'POST' })
}

/**
 * GET /api/readings/{deviceId}?limit=N -> [{ device_id, co2, sensor_timestamp }, ...]
 * oldest first (chart order) - see database.get_readings(). Requires auth
 * (see TOKEN_STORAGE_KEY above); region-scoped server-side for a
 * regional_head.
 */
export function getReadings(deviceId, limit = 500) {
  return _request(`/api/readings/${encodeURIComponent(deviceId)}?limit=${encodeURIComponent(limit)}`)
}

/**
 * GET /api/analytics/{deviceId}?days=N ->
 * [{ date, avg, min, max, count, threshold_violations }, ...] oldest day
 * first - see database.get_daily_analytics(). Same auth/region-scoping
 * as getReadings().
 */
export function getAnalytics(deviceId, days = 7) {
  return _request(`/api/analytics/${encodeURIComponent(deviceId)}?days=${encodeURIComponent(days)}`)
}
