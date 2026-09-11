/**
 * Backs the notification bell: the unseen list (seeded once via
 * GET /api/notifications?unseen=true, per the "picked up as a normal
 * notification on next login" half of the spec), extended live by
 * whatever notificationSocket.js pushes for this user's room (the
 * "pushed immediately if connected" half) - the same seed-then-append
 * shape as useReadings.js's historical/live split, for the same reason:
 * a live push should never have to wait for the next poll, and a login
 * after being offline should never show empty just because nothing
 * arrived while this tab was open.
 *
 * The state held here IS the unseen list - markSeen() removes an item
 * from it rather than just flagging it, so unseenCount is simply its
 * length, not a second thing to keep in sync.
 */

import { useEffect, useState } from 'react'

import { acknowledgeNotification, getNotifications, markNotificationSeen } from '../services/api.js'
import { subscribeNotifications } from '../services/notificationSocket.js'

// How long a toast stays on screen before auto-dismissing.
const TOAST_DURATION_MS = 6000

export function useNotifications() {
  const [notifications, setNotifications] = useState([])
  const [toasts, setToasts] = useState([])

  useEffect(() => {
    let cancelled = false
    getNotifications({ unseen: true })
      .then((rows) => {
        if (!cancelled) setNotifications(rows)
      })
      .catch(() => {
        // No token set yet, or the gateway is unreachable - the bell
        // just shows zero until a token is set / the connection recovers,
        // rather than surfacing a second error UI for an opt-in feature.
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    return subscribeNotifications((notification) => {
      setNotifications((previous) => {
        if (previous.some((n) => n.id === notification.id)) return previous // already have it
        return [notification, ...previous]
      })

      const toastKey = `${notification.id}-${Date.now()}`
      setToasts((previous) => [...previous, { key: toastKey, notification }])
      setTimeout(() => {
        setToasts((previous) => previous.filter((t) => t.key !== toastKey))
      }, TOAST_DURATION_MS)
    })
  }, [])

  function markSeen(notificationId) {
    // Optimistic: the whole point of "seen" is removing it from the
    // unseen list the user is looking at right now.
    setNotifications((previous) => previous.filter((n) => n.id !== notificationId))
    markNotificationSeen(notificationId).catch((err) => {
      console.warn('[useNotifications] markSeen failed:', err)
    })
  }

  function acknowledge(notificationId) {
    setNotifications((previous) =>
      previous.map((n) => (n.id === notificationId ? { ...n, acknowledged: true } : n)),
    )
    acknowledgeNotification(notificationId).catch((err) => {
      console.warn('[useNotifications] acknowledge failed:', err)
    })
  }

  function dismissToast(key) {
    setToasts((previous) => previous.filter((t) => t.key !== key))
  }

  return {
    notifications,
    unseenCount: notifications.length,
    toasts,
    markSeen,
    acknowledge,
    dismissToast,
  }
}
