import { useMsal } from '@azure/msal-react'
import { loginRequest, backendUrl } from '../authConfig'

export function useApiToken() {
  const { instance, accounts } = useMsal()

  const getToken = async (): Promise<string | null> => {
    if (!accounts.length) return null
    try {
      const result = await instance.acquireTokenSilent({
        ...loginRequest,
        account: accounts[0],
      })
      return result.accessToken
    } catch {
      return null
    }
  }

  return { getToken }
}

export async function fetchPortfolio(endpoint: string, token: string | null) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${backendUrl}/api/portfolio/${endpoint}`, { headers })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
