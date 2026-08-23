/**
 * Live gateway-connection pill. Reflects socket.js's own connection state
 * rather than guessing from event traffic, so a quiet-but-healthy stream
 * is never mistaken for a dropped one.
 */

import { useEffect, useState } from 'react'

import { subscribeStatus } from '../services/socket.js'

const LABELS = {
  connected: 'Gateway connected',
  connecting: 'Connecting…',
  disconnected: 'Gateway offline',
}

export default function ConnectionStatus() {
  const [status, setStatus] = useState('disconnected')

  useEffect(() => subscribeStatus(setStatus), [])

  return (
    <div className={`conn conn-${status}`}>
      <span className="conn-dot" />
      <span>{LABELS[status]}</span>
    </div>
  )
}
