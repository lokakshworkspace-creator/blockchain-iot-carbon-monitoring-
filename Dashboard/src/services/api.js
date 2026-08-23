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

async function _request(path, options = {}) {
  let response
  try {
    response = await fetch(`${GATEWAY_URL}${path}`, options)
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

/**
 * POST /verify/{id} -> { status, stored_hash, onchain_hash, recomputed_hash, ... }
 * status is one of Verified | Tampered | NotAnchored | NotFound | Error.
 */
export function verifyRecord(recordId) {
  return _request(`/verify/${encodeURIComponent(recordId)}`, { method: 'POST' })
}
