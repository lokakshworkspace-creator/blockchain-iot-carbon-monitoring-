/**
 * "Last 7 Days" panel: GET /api/analytics/{deviceId}'s per-day stats as a
 * bar chart (one bar per day, average CO2) plus a summary row aggregated
 * across the fetched window. A deliberately separate section (its own
 * tab in Real-Time Data/Factory Detail) from the live line chart
 * (Co2Chart), not an overlay on it - a bar-per-day view and a
 * per-reading line share no meaningful x-axis, so combining them into
 * one chart would misrepresent both. The styling direction's "muted
 * grey comparison line, shared legend" is honored at the color/legend
 * level instead: this chart's bars are drawn in a muted grey rather than
 * the live chart's teal accent (the two tabs stay visually
 * distinguishable at a glance), and both charts carry a Legend in the
 * same position/style, without merging their data into one view.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { LEVEL_COLOR } from '../lib/levels.js'

// Matches Co2Chart.jsx's constants exactly, plus a muted grey reserved
// for this "comparison" view specifically - the live chart's line stays
// the only thing drawn in the teal accent, so glancing at either chart
// tells you which one you're looking at even without reading the tab
// label.
const GRID_COLOR = '#232c2e'
const AXIS_COLOR = '#8fa39c'
const TOOLTIP_BG = '#12181a'
const COMPARISON_BAR_COLOR = '#7a8b86'

export default function WeeklyAnalytics({ days, thresholds, error }) {
  if (error) {
    return <div className="empty error-text">{error}</div>
  }
  // Doubles as the loading state (see useAnalytics' docstring) and the
  // genuinely-no-data state - both render the same "nothing to show yet".
  if (days.length === 0) {
    return <div className="empty">No readings in this window yet.</div>
  }

  // Aggregated from the server's own per-day numbers (count-weighted
  // average, not a naive mean of daily averages) - never refetched or
  // recomputed from raw readings client-side.
  const totalCount = days.reduce((sum, d) => sum + d.count, 0)
  const overallAvg = totalCount > 0 ? days.reduce((sum, d) => sum + d.avg * d.count, 0) / totalCount : 0
  const overallMin = Math.min(...days.map((d) => d.min))
  const overallMax = Math.max(...days.map((d) => d.max))
  const totalViolations = days.reduce((sum, d) => sum + d.threshold_violations, 0)

  const yMax = Math.max(thresholds?.critical ?? 0, overallMax) * 1.15

  return (
    <>
      <div className="stat-row">
        <div className="card stat-card">
          <div className="stat-label">Average</div>
          <div className="stat-value">
            {overallAvg.toFixed(1)}
            <span className="stat-unit">ppm</span>
          </div>
          <div className="stat-sub">across {totalCount} readings</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Min</div>
          <div className="stat-value">
            {overallMin}
            <span className="stat-unit">ppm</span>
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Max</div>
          <div className="stat-value">
            {overallMax}
            <span className="stat-unit">ppm</span>
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Threshold violations</div>
          <div className="stat-value" style={{ color: totalViolations > 0 ? LEVEL_COLOR.WARNING : undefined }}>
            {totalViolations}
          </div>
          <div className="stat-sub">of {totalCount} readings</div>
        </div>
      </div>

      <div className="chart">
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={days} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" stroke={AXIS_COLOR} tick={{ fontSize: 11 }} />
            <YAxis stroke={AXIS_COLOR} tick={{ fontSize: 11 }} width={46} domain={[0, Math.round(yMax)]} />
            <Tooltip
              contentStyle={{
                background: TOOLTIP_BG,
                border: `1px solid ${GRID_COLOR}`,
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: AXIS_COLOR }}
              formatter={(value) => [`${Number(value).toFixed(1)} ppm`, 'Average']}
            />
            <Legend wrapperStyle={{ fontSize: 12, color: AXIS_COLOR }} />
            {thresholds !== null && (
              <ReferenceLine
                y={thresholds.warning}
                stroke={LEVEL_COLOR.WARNING}
                strokeDasharray="5 4"
                label={{
                  value: `warning ${thresholds.warning}`,
                  fill: LEVEL_COLOR.WARNING,
                  fontSize: 10,
                  position: 'insideTopRight',
                }}
              />
            )}
            <Bar dataKey="avg" name="7-day average (ppm)" fill={COMPARISON_BAR_COLOR} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  )
}
