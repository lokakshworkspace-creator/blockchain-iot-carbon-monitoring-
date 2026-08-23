/**
 * Scrolling live feed of every event on the WebSocket stream, colour-coded
 * by severity. Doubles as the debugging view for the rest of the
 * dashboard: if something looks wrong on another page, this shows exactly
 * what the gateway actually sent.
 */

function formatTime(isoTimestamp) {
  const date = new Date(isoTimestamp)
  if (Number.isNaN(date.getTime())) return isoTimestamp
  // Local wall-clock time with milliseconds - Pipeline B emits several
  // events within the same second, and the ordering matters when reading
  // the feed during a demo.
  return date.toLocaleTimeString([], { hour12: false }) + '.' + String(date.getMilliseconds()).padStart(3, '0')
}

export default function EventFeed({ events }) {
  if (events.length === 0) {
    return (
      <div className="empty">
        Waiting for events… Publish a reading with{' '}
        <code>python tests/mqtt_test_publisher.py --scenario normal</code>
      </div>
    )
  }

  return (
    <div className="feed">
      {events.map((event) => (
        <div key={event._id} className={`feed-row sev-${event.severity}`}>
          <span className="feed-time">{formatTime(event.timestamp)}</span>
          <span className={`badge badge-${event.severity}`}>{event.severity}</span>
          <span className="feed-type">{event.event_type}</span>
          <span className="feed-message">{event.message}</span>
        </div>
      ))}
    </div>
  )
}
