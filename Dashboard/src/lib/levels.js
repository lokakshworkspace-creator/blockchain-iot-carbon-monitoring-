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

// Matches styles.css's --ok/--warning/--critical exactly (recharts/inline
// styles need real color values, not var(), in every context this is
// used) - keep these two in sync if the palette ever changes.
export const LEVEL_COLOR = {
  NORMAL: '#2fbf8f',
  WARNING: '#f5a623',
  CRITICAL: '#e5484d',
}

/** Same rule as threshold.py: >= critical is CRITICAL, >= warning is WARNING. */
export function classify(co2, thresholds) {
  if (thresholds === null || !Number.isFinite(co2)) return 'UNKNOWN'
  if (co2 >= thresholds.critical) return 'CRITICAL'
  if (co2 >= thresholds.warning) return 'WARNING'
  return 'NORMAL'
}
