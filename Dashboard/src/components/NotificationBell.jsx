/**
 * Bell icon + unseen-count badge (useNotifications.js), opening a
 * dropdown panel of recent alerts, plus transient toasts for ones that
 * arrive live while the dashboard is open. Lives in the sidebar's top
 * area - this app's layout has no horizontal top bar (App.jsx), so the
 * sidebar header is the closest equivalent, and it's always visible
 * regardless of which page is open, same as ConnectionStatus.
 *
 * Reuses the existing .badge-WARNING/.badge-CRITICAL classes (Severity
 * enum values) for notification.severity, which is lowercase
 * ("warning"/"critical") - hence the .toUpperCase() below rather than a
 * third set of badge color rules.
 */

import { useState } from 'react'

import { useNotifications } from '../hooks/useNotifications.js'

const SEVERITY_LABEL = { warning: 'WARNING', critical: 'CRITICAL' }

function formatTime(isoTimestamp) {
  const date = new Date(isoTimestamp)
  return Number.isNaN(date.getTime()) ? isoTimestamp : date.toLocaleTimeString([], { hour12: false })
}

function SeverityBadge({ severity }) {
  return <span className={`badge badge-${severity.toUpperCase()}`}>{SEVERITY_LABEL[severity] ?? severity}</span>
}

function NotificationRow({ notification, onMarkSeen, onAcknowledge }) {
  return (
    <div className={`notif-row sev-${notification.severity}`}>
      <div className="notif-row-top">
        <SeverityBadge severity={notification.severity} />
        <span className="notif-row-time dim">{formatTime(notification.created_at)}</span>
      </div>
      <div className="notif-row-message">{notification.message}</div>
      <div className="notif-row-meta dim">
        <span className="mono">{notification.device_id}</span>
        <span>{notification.co2_value} ppm</span>
      </div>
      <div className="notif-row-actions">
        <button type="button" className="chip" onClick={() => onMarkSeen(notification.id)}>
          Mark seen
        </button>
        <button
          type="button"
          className={notification.acknowledged ? 'chip active' : 'chip'}
          disabled={notification.acknowledged}
          onClick={() => onAcknowledge(notification.id)}
        >
          {notification.acknowledged ? 'Acknowledged' : 'Acknowledge'}
        </button>
      </div>
    </div>
  )
}

export default function NotificationBell() {
  const { notifications, unseenCount, toasts, markSeen, acknowledge, dismissToast } = useNotifications()
  const [open, setOpen] = useState(false)

  return (
    <div className="notif-bell-wrap">
      <button
        type="button"
        className="notif-bell"
        onClick={() => setOpen((o) => !o)}
        aria-label={`Notifications${unseenCount > 0 ? ` (${unseenCount} unseen)` : ''}`}
      >
        <span className="notif-bell-icon" aria-hidden="true">
          🔔
        </span>
        {unseenCount > 0 && <span className="notif-badge">{unseenCount > 99 ? '99+' : unseenCount}</span>}
      </button>

      {open && (
        <div className="notif-panel">
          <div className="notif-panel-head">
            <span>Notifications</span>
            <span className="dim count">{notifications.length} unseen</span>
          </div>
          {notifications.length === 0 ? (
            <div className="empty">No unseen alerts.</div>
          ) : (
            <div className="notif-list">
              {notifications.map((notification) => (
                <NotificationRow
                  key={notification.id}
                  notification={notification}
                  onMarkSeen={markSeen}
                  onAcknowledge={acknowledge}
                />
              ))}
            </div>
          )}
        </div>
      )}

      <div className="notif-toast-stack">
        {toasts.map(({ key, notification }) => (
          <div key={key} className={`notif-toast sev-${notification.severity}`}>
            <div className="notif-toast-head">
              <SeverityBadge severity={notification.severity} />
              <button
                type="button"
                className="notif-toast-close"
                aria-label="Dismiss"
                onClick={() => dismissToast(key)}
              >
                ×
              </button>
            </div>
            <div className="notif-toast-message">{notification.message}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
