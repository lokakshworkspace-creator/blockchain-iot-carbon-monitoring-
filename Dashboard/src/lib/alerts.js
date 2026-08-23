/**
 * Alert-related views over the shared event buffer.
 *
 * Both the Overview and Real-Time Data pages show "what is the gateway
 * currently alerting on", so the derivation lives here once. Crucially it
 * only ever *reads* the gateway's own THRESHOLD_* events - it never
 * re-implements threshold.py's cooldown/hysteresis rules to decide for
 * itself whether an alert should be open. threshold.py owns that state
 * machine; a second copy in the browser would drift from it.
 */

const ALERT_EVENT_TYPES = new Set([
  'THRESHOLD_WARNING',
  'THRESHOLD_CRITICAL',
  'THRESHOLD_RESOLVED',
  'TAMPERING_DETECTED',
])

// An alert lifecycle ends at THRESHOLD_RESOLVED. Tampering deliberately
// has no resolved state (per the project's rules, a tampered record stays
// flagged permanently), so it is never treated as closable here.
const OPEN_ALERT_TYPES = new Set(['THRESHOLD_WARNING', 'THRESHOLD_CRITICAL'])

/** Newest-first array assumed, matching the EventStream buffer. */
export function recentAlerts(events, limit = 6) {
  return events.filter((event) => ALERT_EVENT_TYPES.has(event.event_type)).slice(0, limit)
}

/**
 * Devices whose most recent threshold event left an alert open, plus any
 * tampering detected. Returns { openDevices, tamperCount, total }.
 */
export function activeAlerts(events) {
  const latestByDevice = new Map()
  let tamperCount = 0

  // Newest-first, so the first event seen for a device is its current state.
  for (const event of events) {
    if (event.event_type === 'TAMPERING_DETECTED') {
      tamperCount += 1
      continue
    }
    if (!OPEN_ALERT_TYPES.has(event.event_type) && event.event_type !== 'THRESHOLD_RESOLVED') continue

    const key = event.device_id ?? '(unknown)'
    if (!latestByDevice.has(key)) latestByDevice.set(key, event.event_type)
  }

  const openDevices = [...latestByDevice.entries()]
    .filter(([, eventType]) => OPEN_ALERT_TYPES.has(eventType))
    .map(([deviceId, eventType]) => ({ deviceId, eventType }))

  return { openDevices, tamperCount, total: openDevices.length + tamperCount }
}

/** Human label for the single most recent threshold event, for the alert-state card. */
const ALERT_LABEL = {
  THRESHOLD_WARNING: 'WARNING alert active',
  THRESHOLD_CRITICAL: 'CRITICAL alert active',
  THRESHOLD_RESOLVED: 'No active alert',
}

export function currentAlertState(events) {
  const event = events.find((e) => e.event_type?.startsWith('THRESHOLD_'))
  if (event === undefined) return 'No alerts yet'
  return ALERT_LABEL[event.event_type] ?? event.event_type
}
