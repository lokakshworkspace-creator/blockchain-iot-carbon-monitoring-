/**
 * Live CO2 line chart fed by SENSOR_READING events.
 *
 * The two reference lines are what make a threshold crossing legible: the
 * NORMAL -> WARNING -> CRITICAL transitions read as the line moving across
 * marked boundaries, rather than as an unlabelled squiggle. Points are
 * coloured by their own instantaneous level so a single excursion is
 * visible even when the line between points crosses a boundary.
 */

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { LEVEL_COLOR } from '../lib/levels.js'

// Matches styles.css's --border/--text-dim/--bg-panel/--accent exactly -
// recharts needs real color values (not var()) for SVG stroke/fill props
// in every context used here, so these are kept in sync by hand rather
// than read from the stylesheet.
const GRID_COLOR = '#232c2e'
const AXIS_COLOR = '#8fa39c'
const TOOLTIP_BG = '#12181a'
const LIVE_LINE_COLOR = '#2fbf8f'

function LevelDot({ cx, cy, payload }) {
  if (cx === undefined || cy === undefined) return null
  return <circle cx={cx} cy={cy} r={3} fill={LEVEL_COLOR[payload.level] ?? LIVE_LINE_COLOR} />
}

export default function Co2Chart({ points, thresholds }) {
  if (points.length === 0) {
    return (
      <div className="empty">
        Waiting for readings… Publish with{' '}
        <code>python tests/mqtt_test_publisher.py --co2-sequence &quot;650,1250,2400,700&quot;</code>
      </div>
    )
  }

  // A fixed floor of 0 with headroom above the critical line keeps the
  // y-axis stable as readings arrive - an auto-scaled axis would make a
  // flat normal series look as dramatic as a real spike.
  const maxReading = Math.max(...points.map((p) => p.co2))
  const yMax = Math.max(thresholds?.critical ?? 0, maxReading) * 1.15

  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={points} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="time" stroke={AXIS_COLOR} tick={{ fontSize: 11 }} minTickGap={28} />
          {/* No rotated axis label: at this chart's left margin it clips.
              The unit is stated in the section heading instead. */}
          <YAxis stroke={AXIS_COLOR} tick={{ fontSize: 11 }} width={46} domain={[0, Math.round(yMax)]} />
          <Tooltip
            contentStyle={{
              background: TOOLTIP_BG,
              border: `1px solid ${GRID_COLOR}`,
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: AXIS_COLOR }}
            formatter={(value, _name, item) => [`${value} ppm (${item.payload.level})`, 'CO₂']}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: AXIS_COLOR }} />

          {thresholds !== null && (
            <ReferenceLine
              y={thresholds.warning}
              stroke={LEVEL_COLOR.WARNING}
              strokeDasharray="5 4"
              label={{ value: `warning ${thresholds.warning}`, fill: LEVEL_COLOR.WARNING, fontSize: 10, position: 'insideTopRight' }}
            />
          )}
          {thresholds !== null && (
            <ReferenceLine
              y={thresholds.critical}
              stroke={LEVEL_COLOR.CRITICAL}
              strokeDasharray="5 4"
              label={{ value: `critical ${thresholds.critical}`, fill: LEVEL_COLOR.CRITICAL, fontSize: 10, position: 'insideTopRight' }}
            />
          )}

          <Line
            type="monotone"
            dataKey="co2"
            name="Live CO₂ (ppm)"
            stroke={LIVE_LINE_COLOR}
            strokeWidth={2}
            dot={<LevelDot />}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
