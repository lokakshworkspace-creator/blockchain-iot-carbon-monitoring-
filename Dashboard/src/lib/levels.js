/**
 * Client-side mirror of threshold.py's _classify(): the instantaneous
 * level of a single CO2 reading.
 *
 * Important distinction, and the reason these are kept separate in the UI:
 * this is NOT the alert state. threshold.py applies cooldown and
 * hysteresis on top of this classification, so a reading can classify as
 * WARNING while no new alert fires (an alert is already active), or read
 * NORMAL while a CRITICAL alert is still open (not enough consecutive
 * normal readings to resolve it yet). The gauge shows this instantaneous
 * level; the alert badge shows what the gateway's state machine actually
 * decided. Re-deriving alert state in the browser would eventually
 * disagree with the gateway, so we never do.
 *
 * The threshold values themselves come from GET /health, not from
 * constants here - they live in the gateway's .env.
 */

export const LEVEL_COLOR = {
  NORMAL: '#35d07f',
  WARNING: '#f5b23a',
  CRITICAL: '#ff5f6d',
}

/** Same rule as threshold.py: >= critical is CRITICAL, >= warning is WARNING. */
export function classify(co2, thresholds) {
  if (thresholds === null || !Number.isFinite(co2)) return 'UNKNOWN'
  if (co2 >= thresholds.critical) return 'CRITICAL'
  if (co2 >= thresholds.warning) return 'WARNING'
  return 'NORMAL'
}
