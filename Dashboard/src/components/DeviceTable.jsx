/**
 * Device roster from GET /devices/status. The gateway owns the
 * online/offline decision (device_status.py's timeout logic), so this
 * renders its snapshot rather than re-deriving liveness from timestamps
 * in the browser - two independent definitions of "offline" would
 * eventually disagree and undermine the whole page.
 */

function formatLastSeen(isoTimestamp) {
  const date = new Date(isoTimestamp)
  if (Number.isNaN(date.getTime())) return isoTimestamp

  const secondsAgo = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000))
  const clock = date.toLocaleTimeString([], { hour12: false })
  if (secondsAgo < 60) return `${clock} (${secondsAgo}s ago)`
  return `${clock} (${Math.floor(secondsAgo / 60)}m ago)`
}

export default function DeviceTable({ devices, error }) {
  if (error) {
    return <div className="empty error-text">{error}</div>
  }
  if (devices.length === 0) {
    return <div className="empty">No devices have reported to the gateway yet.</div>
  }

  return (
    <table className="table">
      <thead>
        <tr>
          <th>Device ID</th>
          <th>Status</th>
          <th>Last seen</th>
        </tr>
      </thead>
      <tbody>
        {devices.map((device) => (
          <tr key={device.device_id}>
            <td className="mono">{device.device_id}</td>
            <td>
              <span className={`badge ${device.online ? 'badge-online' : 'badge-offline'}`}>
                {device.online ? 'ONLINE' : 'OFFLINE'}
              </span>
            </td>
            <td className="dim">{formatLastSeen(device.last_seen)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
