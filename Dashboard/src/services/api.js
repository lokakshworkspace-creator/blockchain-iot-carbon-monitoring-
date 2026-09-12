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

// Phase 7 replaces the Phase 3 manual devtools-console workaround with a
// real login page, but keeps the same storage location and key - a token
// set the old way during this transition still works, and nothing else
// that already reads getStoredToken() (notificationSocket.js) needs to
// change. localStorage over in-memory-only storage is a deliberate
// choice: it survives a page reload/tab reopen without forcing a
// re-login every time, which is what an in-memory-only token would do
// the moment the SPA remounts. The standard tradeoff (a token in
// localStorage is readable by any script that runs on this origin, i.e.
// an XSS vector) is accepted here the same way the rest of this
// project's security posture is scoped - CLAUDE.md frames this whole
// thing as a demonstrable capstone prototype, not a hardened production
// system, and nothing else in this codebase introduces an XSS vector for
// a stolen token to matter through.
const TOKEN_STORAGE_KEY = 'carbon_monitor_token'

/** Read the stored token - exported so notificationSocket.js (Phase 6)
 * can attach it to the WebSocket URL as a query param (a browser
 * WebSocket has no way to set a header), and so AuthContext can restore
 * a session from a page reload. */
export function getStoredToken() {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

/** Called by AuthContext.login() on a successful POST /api/auth/login. */
export function setStoredToken(token) {
  try {
    localStorage.setItem(TOKEN_STORAGE_KEY, token)
  } catch {
    // Same defensive stance as getStoredToken(): a locked-down browser
    // context must not crash the login flow, just fail to persist it
    // across a reload.
  }
}

/** Called by AuthContext.logout() and by the 401 handler below. */
export function clearStoredToken() {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {
    // ignore, see getStoredToken()
  }
}

function _authHeaders() {
  const token = getStoredToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Fired on any 401 from _request() below. AuthContext listens for this
// (rather than this module importing react-router or the context
// directly, which would tangle a plain service module into React) and
// clears its user state, which is what makes every RequireAuth-wrapped
// route redirect to /login - see components/RequireAuth.jsx.
const UNAUTHORIZED_EVENT = 'carbon-monitor:unauthorized'

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

  if (response.status === 401) {
    clearStoredToken()
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
  }

  if (!response.ok) {
    throw new Error(`${options.method ?? 'GET'} ${path} failed: ${response.status} ${response.statusText}`)
  }

  return response.json()
}

/**
 * Subscribe to "the gateway just rejected our token" - AuthContext's own
 * hook, not meant to be called from page components directly.
 * @param {() => void} listener
 * @returns {() => void} unsubscribe
 */
export function onUnauthorized(listener) {
  window.addEventListener(UNAUTHORIZED_EVENT, listener)
  return () => window.removeEventListener(UNAUTHORIZED_EVENT, listener)
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

/**
 * GET /api/notifications?unseen=&limit= ->
 * [{ id, region_id, factory_id, device_id, co2_value, severity, message,
 *    created_at, delivered_realtime, seen_at, acknowledged }, ...]
 * newest first. Region-scoped server-side (same auth as getReadings());
 * unseen=false lists recent notifications generally, not just unseen
 * ones - see Gateway/routers/notifications.py.
 */
export function getNotifications({ unseen = true, limit = 50 } = {}) {
  const params = new URLSearchParams({ unseen: String(unseen), limit: String(limit) })
  return _request(`/api/notifications?${params}`)
}

/** POST /api/notifications/{id}/seen -> the updated notification. */
export function markNotificationSeen(notificationId) {
  return _request(`/api/notifications/${encodeURIComponent(notificationId)}/seen`, { method: 'POST' })
}

/** POST /api/notifications/{id}/acknowledge -> the updated notification. */
export function acknowledgeNotification(notificationId) {
  return _request(`/api/notifications/${encodeURIComponent(notificationId)}/acknowledge`, { method: 'POST' })
}

// --- Phase 7: auth + admin/regional-dashboard CRUD ---

/**
 * POST /api/auth/login -> { access_token, token_type, expires_in_hours,
 * role, region_id }. Does not itself store the token - AuthContext.login()
 * calls setStoredToken() with the result, so this stays a pure API call
 * like everything else here.
 */
export function login(username, password) {
  return _request('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
}

/** GET /api/regions/me -> a single region (regional_head) or every
 * region (admin) - see Gateway/routers/regions.py. Callers must check
 * Array.isArray() to tell which shape they got. */
export function getMyRegion() {
  return _request('/api/regions/me')
}

/** GET /api/factories -> every factory for an admin, only the caller's
 * own region's for a regional_head - filtered server-side. */
export function getMyFactories() {
  return _request('/api/factories')
}

/** GET /api/factories/{factoryId}/devices -> that factory's devices, or
 * 404 if it's outside the caller's region. */
export function getFactoryDevices(factoryId) {
  return _request(`/api/factories/${encodeURIComponent(factoryId)}/devices`)
}

/** GET /api/admin/regions -> every region (admin only). */
export function adminListRegions() {
  return _request('/api/admin/regions')
}

/** POST /api/admin/regions -> the created region. */
export function adminCreateRegion({ name, description = '' }) {
  return _request('/api/admin/regions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  })
}

/** GET /api/admin/factories -> every factory, any region (admin only). */
export function adminListFactories() {
  return _request('/api/admin/factories')
}

/** POST /api/admin/factories -> the created factory. regionId is
 * required server-side (Gateway/routers/admin_factories.py). */
export function adminCreateFactory({ name, regionId, isSimulated = false, location = '' }) {
  return _request('/api/admin/factories', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, region_id: regionId, is_simulated: isSimulated, location }),
  })
}

/** GET /api/admin/devices -> the whole device registry (admin only). */
export function adminListDevices() {
  return _request('/api/admin/devices')
}

/** POST /api/admin/devices -> the created device. factoryId is required
 * server-side; deviceId is the MQTT string identity, not a Mongo id. */
export function adminCreateDevice({ deviceId, factoryId, isHardware = false }) {
  return _request('/api/admin/devices', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId, factory_id: factoryId, is_hardware: isHardware }),
  })
}

/** GET /api/admin/users -> every user account (admin only). */
export function adminListUsers() {
  return _request('/api/admin/users')
}

/**
 * POST /api/admin/users -> the created user. role="admin" is rejected by
 * the gateway unless confirmAdminCreation is explicitly true
 * (Gateway/routers/admin_users.py) - this form never sets it, since the
 * admin panel (per this phase's scope) only creates Regional Head
 * accounts.
 */
export function adminCreateUser({ username, email, password, role, regionId = null }) {
  return _request('/api/admin/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password, role, region_id: regionId }),
  })
}

/** PATCH /api/admin/users/{id} -> the updated user. Only region_id and
 * is_active are patchable server-side (role changes aren't, by design -
 * see admin_users.py). Pass only the fields being changed. */
export function adminUpdateUser(userId, { regionId, isActive } = {}) {
  const body = {}
  if (regionId !== undefined) body.region_id = regionId
  if (isActive !== undefined) body.is_active = isActive
  return _request(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
