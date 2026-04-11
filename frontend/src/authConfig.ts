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

// Scopes for sign-in.
// 'openid profile email' gives us the ID token and basic user info.
// The backend API scope (Chat.Read) scopes the access token so the backend can
// validate it as audience=ENTRA_BACKEND_CLIENT_ID and perform the OBO exchange
// for downstream MCP servers.  Falls back gracefully when VITE_ENTRA_BACKEND_CLIENT_ID
// is not set (local dev without Entra configured).
export const loginRequest = {
  scopes: [
    'openid',
    'profile',
    'email',
    ...(import.meta.env.VITE_ENTRA_BACKEND_CLIENT_ID
      ? [`api://${import.meta.env.VITE_ENTRA_BACKEND_CLIENT_ID}/Chat.Read`]
      : []),
  ],
}

export const backendUrl =
  import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'
