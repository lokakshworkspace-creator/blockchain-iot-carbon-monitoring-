/**
 * Client-side record-list helpers shared by the Blockchain Logs and
 * Verification pages. Kept out of RecordAnchorFilter.jsx so that file
 * only exports a component (fast-refresh requirement), mirroring the
 * EventStream.jsx / eventStreamContext.js split elsewhere in this app.
 */

/**
 * Narrow a records array by on-chain anchor state, using the
 * blockchain_record_id GET /records already returns. Purely a view
 * filter - no request, no backend involvement.
 *
 * @param {Array} records - rows from GET /records
 * @param {'all'|'anchored'|'pending'} filter
 */
export function filterByAnchor(records, filter) {
  if (filter === 'anchored') return records.filter((r) => r.blockchain_record_id !== null)
  if (filter === 'pending') return records.filter((r) => r.blockchain_record_id === null)
  return records
}
