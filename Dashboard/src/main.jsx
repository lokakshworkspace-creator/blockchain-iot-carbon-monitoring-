import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App.jsx'
import { AuthProvider } from './context/AuthProvider.jsx'
import { EventStreamProvider } from './context/EventStream.jsx'
import './styles.css'

// EventStreamProvider sits above the router so the event buffer survives
// navigation between pages - switching to another page and back must not
// reset the live feed. AuthProvider doesn't use any router hooks itself,
// but sits above BrowserRouter anyway so a redirect-on-401 always has a
// session to redirect away from, regardless of route.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <EventStreamProvider>
      <AuthProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AuthProvider>
    </EventStreamProvider>
  </StrictMode>,
)
