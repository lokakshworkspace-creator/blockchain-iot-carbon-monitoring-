/**
 * Shared "All / Anchored only / Pending only" toggle for the record lists
 * on Blockchain Logs and Verification. The matching filter helper lives in
 * lib/records.js (filterByAnchor). Reuses the existing .filters / .chip
 * styling from the System Monitor page.
 */

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'anchored', label: 'Anchored only' },
  { key: 'pending', label: 'Pending only' },
]

export default function RecordAnchorFilter({ value, onChange, visibleCount, totalCount }) {
  return (
    <div className="filters">
      {FILTERS.map(({ key, label }) => (
        <button
          key={key}
          type="button"
          className={value === key ? 'chip active' : 'chip'}
          onClick={() => onChange(key)}
        >
          {label}
        </button>
      ))}
      <span className="dim count">
        {visibleCount} of {totalCount}
      </span>
    </div>
  )
}
