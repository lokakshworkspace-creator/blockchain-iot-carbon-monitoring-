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
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { LEVEL_COLOR } from '../lib/levels.js'

function LevelDot({ cx, cy, payload }) {
  if (cx === undefined || cy === undefined) return null
  return <circle cx={cx} cy={cy} r={3} fill={LEVEL_COLOR[payload.level] ?? '#4f9dff'} />
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
          <CartesianGrid stroke="#2a3348" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="time" stroke="#93a0bb" tick={{ fontSize: 11 }} minTickGap={28} />
          {/* No rotated axis label: at this chart's left margin it clips.
              The unit is stated in the section heading instead. */}
          <YAxis stroke="#93a0bb" tick={{ fontSize: 11 }} width={46} domain={[0, Math.round(yMax)]} />
          <Tooltip
            contentStyle={{
              background: '#171d2c',
              border: '1px solid #2a3348',
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: '#93a0bb' }}
            formatter={(value, _name, item) => [`${value} ppm (${item.payload.level})`, 'CO₂']}
          />

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
            stroke="#4f9dff"
            strokeWidth={2}
            dot={<LevelDot />}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
