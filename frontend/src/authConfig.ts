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

// Scopes for sign-in — Chat.Read is the delegated permission on the backend API.
// Including it here means MSAL acquires the backend-scoped access token at login,
// so acquireTokenSilent(tokenRequest) always hits cache on subsequent calls.
// openid/profile/email are OIDC scopes that produce the ID token (for accounts[0].name/username).
// NOTE: User.Read (Graph resource) is intentionally omitted — mixing resources in one
// loginRequest is rejected by MSAL. User display info comes from the ID token instead.
export const loginRequest = {
  scopes: ['openid', 'profile', 'email', `api://${import.meta.env.VITE_ENTRA_CLIENT_ID || 'fb3c0e70-f3bb-46a1-9f0b-2587b49a3d0c'}/Chat.Read`],
}

// Scopes for backend API calls — same resource as loginRequest so the token is
// always available from MSAL cache without an extra network round-trip.
// Token issued with aud=api://<clientId>, usable as an OBO assertion.
export const tokenRequest = {
  scopes: [`api://${import.meta.env.VITE_ENTRA_CLIENT_ID || 'fb3c0e70-f3bb-46a1-9f0b-2587b49a3d0c'}/Chat.Read`],
}

export const backendUrl =
  import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'
