/**
 * Renders POST /verify/{id}'s result with a distinct visual treatment per
 * status, rather than one generic "status: X" line. Tampered gets the
 * most visual weight deliberately - it is the project's core demo moment,
 * the whole point of anchoring a hash on an immutable ledger in the first
 * place.
 *
 * All three hashes are shown whenever present, mirroring the Phase 2
 * mongosh/curl live-proof output through the UI: the verdict alone
 * ("Tampered") is a claim, but stored/onchain/recomputed side by side is
 * the evidence for it.
 */

const STATUS_META = {
  Verified: {
    label: 'Verified',
    className: 'verdict-verified',
    icon: '✓',
    description: 'The data currently in MongoDB matches the hash anchored on Sepolia. Nothing has changed since it was recorded.',
  },
  Tampered: {
    label: 'Tampered',
    className: 'verdict-tampered',
    icon: '⚠',
    description: 'The data in MongoDB no longer matches the immutable on-chain hash. This record has been altered since it was anchored.',
  },
  NotAnchored: {
    label: 'Not yet anchored',
    className: 'verdict-pending',
    icon: '…',
    description: 'This record has not been confirmed on Sepolia yet. Wait for BLOCKCHAIN_CONFIRMED, then verify again.',
  },
  NotFound: {
    label: 'Not found',
    className: 'verdict-unknown',
    icon: '?',
    description: 'No record exists with this id - it may have been deleted.',
  },
  Error: {
    label: 'Verification error',
    className: 'verdict-error',
    icon: '!',
    description: 'The check itself could not complete (a MongoDB or RPC problem), not a tampering finding. Check System Monitor.',
  },
}

function HashRow({ label, value, highlight }) {
  return (
    <div className={`hash-row ${highlight ? 'hash-row-highlight' : ''}`}>
      <span className="hash-label">{label}</span>
      <span className="hash-value mono">{value ?? '—'}</span>
    </div>
  )
}

export default function VerificationResult({ result, pending }) {
  if (pending) {
    return (
      <div className="verdict verdict-pending">
        <div className="verdict-icon">…</div>
        <div>
          <div className="verdict-label">Verifying…</div>
          <div className="verdict-description">Waiting for the gateway to compare hashes.</div>
        </div>
      </div>
    )
  }

  if (result === null) {
    return <div className="empty">Select a record above, then click Verify.</div>
  }

  const meta = STATUS_META[result.status] ?? STATUS_META.Error
  const mismatch = result.status === 'Tampered'

  return (
    <div>
      <div className={`verdict ${meta.className}`}>
        <div className="verdict-icon">{meta.icon}</div>
        <div>
          <div className="verdict-label">{meta.label}</div>
          <div className="verdict-description">{meta.description}</div>
        </div>
      </div>

      {(result.stored_hash || result.onchain_hash || result.recomputed_hash) && (
        <div className="hash-panel">
          <HashRow label="Stored hash (MongoDB)" value={result.stored_hash} />
          <HashRow label="On-chain hash (Sepolia)" value={result.onchain_hash} highlight={mismatch} />
          <HashRow label="Recomputed hash (from current data)" value={result.recomputed_hash} highlight={mismatch} />
          {mismatch && (
            <div className="hash-note">
              The on-chain hash is immutable; the recomputed hash reflects whatever is in MongoDB right
              now. They differ, so the underlying reading was changed after it was anchored.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
