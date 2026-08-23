import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App.jsx'
import { EventStreamProvider } from './context/EventStream.jsx'
import './styles.css'

// EventStreamProvider sits above the router so the event buffer survives
// navigation between pages - switching to another page and back must not
// reset the live feed.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <EventStreamProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </EventStreamProvider>
  </StrictMode>,
)
