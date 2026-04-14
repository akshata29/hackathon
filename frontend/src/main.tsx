import React from 'react'
import ReactDOM from 'react-dom/client'
import { MsalProvider } from '@azure/msal-react'
import { PublicClientApplication } from '@azure/msal-browser'
import { msalConfig } from './authConfig'
import App from './App'
import './index.css'

const msalInstance = new PublicClientApplication(msalConfig)

msalInstance.initialize().then(() => {
  // Clear any stale MSAL interaction lock left by a previous failed popup.
  // Without this, a page refresh mid-popup leaves 'interaction_in_progress'
  // locked in sessionStorage and every subsequent loginPopup call throws.
  sessionStorage.removeItem('msal.interaction.status')

  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <MsalProvider instance={msalInstance}>
        <App />
      </MsalProvider>
    </React.StrictMode>,
  )
})
