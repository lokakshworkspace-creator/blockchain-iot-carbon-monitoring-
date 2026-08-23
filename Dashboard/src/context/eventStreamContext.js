/**
 * Context object and consumer hook for the shared event stream, kept
 * separate from EventStream.jsx so that file exports only a component.
 * That is what lets React Fast Refresh hot-swap the provider on edit
 * instead of remounting it - which during a live demo would otherwise
 * throw away the accumulated event buffer every time a file is saved.
 */

import { createContext, useContext } from 'react'

export const EventStreamContext = createContext(null)

export function useEventStream() {
  const context = useContext(EventStreamContext)
  if (context === null) {
    throw new Error('useEventStream must be used inside an <EventStreamProvider>')
  }
  return context
}
