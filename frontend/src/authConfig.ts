// MSAL browser configuration for Entra ID (Azure AD) authentication
// Values are injected via Vite environment variables at build time

import { Configuration, LogLevel } from '@azure/msal-browser'

export const msalConfig: Configuration = {
  auth: {
    clientId: import.meta.env.VITE_ENTRA_CLIENT_ID || 'dev-client-id',
    authority: `https://login.microsoftonline.com/${import.meta.env.VITE_ENTRA_TENANT_ID || 'common'}`,
    redirectUri: window.location.origin,
    postLogoutRedirectUri: window.location.origin,
  },
  cache: {
    cacheLocation: 'sessionStorage',
    storeAuthStateInCookie: false,
  },
  system: {
    loggerOptions: {
      loggerCallback: (level, message, containsPii) => {
        if (containsPii) return
        if (level === LogLevel.Error) console.error(message)
        else if (level === LogLevel.Warning) console.warn(message)
      },
    },
  },
}

// Scopes for sign-in (openid profile gives us the ID token / user info)
// Chat.Read scope requires the API to be explicitly exposed in the app registration;
// omit it here for local dev — the backend skips JWT validation when ENTRA_TENANT_ID is blank
export const loginRequest = {
  scopes: ['openid', 'profile', 'email'],
}

export const backendUrl =
  import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'
