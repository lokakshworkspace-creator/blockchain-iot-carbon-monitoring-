/**
 * Horizontal gauge placing the current reading on a scale marked with the
 * gateway's configured warning and critical thresholds, so "how close are
 * we to a problem" is readable at a glance rather than requiring the
 * viewer to compare two numbers mentally.
 */

import { LEVEL_COLOR } from '../lib/levels.js'

export default function Co2Gauge({ co2, level, thresholds }) {
  if (thresholds === null) {
    return <div className="empty">Loading thresholds…</div>
  }

  // Headroom above the critical threshold so a critical reading still
  // lands inside the track rather than pinned at the very end.
  const max = thresholds.critical * 1.5
  const position = Number.isFinite(co2) ? Math.min(100, Math.max(0, (co2 / max) * 100)) : 0
  const warningAt = (thresholds.warning / max) * 100
  const criticalAt = (thresholds.critical / max) * 100

  return (
    <div className="gauge">
      <div className="gauge-track">
        {/* Zones, drawn as absolutely-positioned bands under the marker. */}
        <div className="gauge-zone" style={{ left: 0, width: `${warningAt}%`, background: LEVEL_COLOR.NORMAL }} />
        <div
          className="gauge-zone"
          style={{ left: `${warningAt}%`, width: `${criticalAt - warningAt}%`, background: LEVEL_COLOR.WARNING }}
        />
        <div
          className="gauge-zone"
          style={{ left: `${criticalAt}%`, width: `${100 - criticalAt}%`, background: LEVEL_COLOR.CRITICAL }}
        />

        {Number.isFinite(co2) && (
          <div className="gauge-marker" style={{ left: `${position}%`, borderColor: LEVEL_COLOR[level] }} />
        )}
      </div>

      <div className="gauge-scale">
        <span>0</span>
        <span style={{ left: `${warningAt}%` }} className="gauge-tick">
          {thresholds.warning}
        </span>
        <span style={{ left: `${criticalAt}%` }} className="gauge-tick">
          {thresholds.critical}
        </span>
        <span className="gauge-max">{Math.round(max)} ppm</span>
      </div>
    </div>
  )
}
