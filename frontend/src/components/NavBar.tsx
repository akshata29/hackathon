import { useEffect, useState } from 'react'
import { useMsal, useIsAuthenticated } from '@azure/msal-react'
import { loginRequest, tokenRequest, backendUrl } from '../authConfig'
import type { DemoMode } from '../App'

type Tab = 'chat' | 'dashboard'

interface NavBarProps {
  activeTab: Tab
  onTabChange: (tab: Tab) => void
  demoMode: DemoMode
  onDemoModeChange: (mode: DemoMode) => void
}

export function NavBar({ activeTab, onTabChange, demoMode, onDemoModeChange }: NavBarProps) {
  const { instance, accounts } = useMsal()
  const isAuthenticated = useIsAuthenticated()
  const user = accounts[0]
  const [githubConnected, setGithubConnected] = useState<boolean | null>(null)

  // Check GitHub connection status when signed in
  useEffect(() => {
    if (!isAuthenticated) { setGithubConnected(null); return }
    // Check for post-OAuth redirect indicator
    const params = new URLSearchParams(window.location.search)
    if (params.get('github_connected') === 'true') {
      setGithubConnected(true)
      window.history.replaceState({}, '', window.location.pathname)
      return
    }
    // Poll status from backend
    const check = async () => {
      try {
        const { instance: msalInstance } = { instance }
        const result = await msalInstance.acquireTokenSilent({ ...tokenRequest, account: accounts[0] })
        const res = await fetch(`${backendUrl}/api/auth/github/status`, {
          headers: { Authorization: `Bearer ${result.accessToken}` },
        })
        if (res.ok) {
          const data = await res.json()
          setGithubConnected(data.connected)
        } else {
          setGithubConnected(false)
        }
      } catch {
        setGithubConnected(false)
      }
    }
    check()
  }, [isAuthenticated])

  const handleGitHubConnect = async () => {
    if (!accounts[0]) return
    try {
      const result = await instance.acquireTokenSilent({ ...tokenRequest, account: accounts[0] }).catch(() =>
        instance.acquireTokenPopup({ ...tokenRequest, account: accounts[0] })
      )
      const res = await fetch(`${backendUrl}/api/auth/github`, {
        headers: { Authorization: `Bearer ${result.accessToken}` },
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (data.auth_url) {
        window.location.href = data.auth_url
      }
    } catch (e) {
      console.error('GitHub connect failed', e)
    }
  }

  const handleGitHubDisconnect = async () => {
    if (!accounts[0]) return
    try {
      const result = await instance.acquireTokenSilent({ ...tokenRequest, account: accounts[0] })
      await fetch(`${backendUrl}/api/auth/github`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${result.accessToken}` },
      })
      setGithubConnected(false)
    } catch (e) {
      console.error('GitHub disconnect failed', e)
    }
  }

  const handleLogin = () => instance.loginPopup(loginRequest).catch(console.error)
  const handleLogout = () => instance.logoutPopup().catch(console.error)

  return (
    <nav className="bg-gray-900/80 backdrop-blur-md border-b border-white/5 shadow-xl shadow-black/30 sticky top-0 z-50">
      <div className="container mx-auto px-4 max-w-7xl flex items-center justify-between h-14">
        <div className="flex items-center gap-6">
          <span className="font-bold bg-gradient-to-r from-indigo-400 to-violet-400 bg-clip-text text-transparent text-lg tracking-tight select-none">
            Portfolio Advisor
          </span>
          <div className="flex gap-1 bg-gray-800/60 rounded-lg p-1">
            {(['chat', 'dashboard'] as Tab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => onTabChange(tab)}
                className={`px-3.5 py-1 rounded-md text-sm font-medium transition-all duration-150 ${
                  activeTab === tab
                    ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-900/50'
                    : 'text-gray-400 hover:bg-gray-700/60 hover:text-gray-200'
                }`}
              >
                {tab === 'chat' ? 'AI Chat' : 'Dashboard'}
              </button>
            ))}
          </div>

          {/* Auth mode demo toggle */}
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold text-gray-600 uppercase tracking-widest select-none">
              Auth Mode
            </span>
            <div className="flex gap-0.5 bg-gray-800/60 rounded-lg p-0.5">
              {([
                { value: 'entra',       label: 'Entra',      title: 'Default: Entra OBO token exchange (production flow)' },
                { value: 'multi-idp',   label: 'Multi-IDP',  title: 'Option B: Backend presents mock Okta JWT directly to MCP (MultiIDPTokenVerifier)' },
                { value: 'okta-proxy',  label: 'Okta Proxy', title: 'Option C: Yahoo Finance calls routed through Okta proxy (token swap)' },
                { value: 'entra-agent', label: 'Agent ID',   title: 'Option D: Backend uses Entra Agent Identity — no client secret, no user OBO (DefaultAzureCredential)' },
              ] as { value: DemoMode; label: string; title: string }[]).map(({ value, label, title }) => (
                <button
                  key={value}
                  onClick={() => onDemoModeChange(value)}
                  title={title}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-all duration-150 ${
                    demoMode === value
                      ? value === 'entra'
                        ? 'bg-sky-700/70 text-sky-200 shadow shadow-sky-900/40'
                        : value === 'entra-agent'
                        ? 'bg-violet-700/70 text-violet-200 shadow shadow-violet-900/40'
                        : 'bg-amber-700/70 text-amber-200 shadow shadow-amber-900/40'
                      : 'text-gray-500 hover:bg-gray-700/60 hover:text-gray-300'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {isAuthenticated ? (
            <>
              {/* GitHub connection indicator (Pattern 2: vendor OAuth) */}
              {githubConnected === false && (
                <button
                  onClick={handleGitHubConnect}
                  title="Connect GitHub for engineering intelligence on tech stocks"
                  className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white border border-gray-700/60 rounded-md px-2.5 py-1 hover:border-gray-500 transition-all"
                >
                  <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
                  </svg>
                  Connect GitHub
                </button>
              )}
              {githubConnected === true && (
                <button
                  onClick={handleGitHubDisconnect}
                  title="GitHub connected - click to disconnect"
                  className="flex items-center gap-1.5 text-xs text-emerald-400 border border-emerald-800/60 rounded-md px-2.5 py-1 hover:text-red-400 hover:border-red-800/60 transition-all"
                >
                  <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
                  </svg>
                  GitHub
                </button>
              )}
              <div className="flex items-center gap-2">
                <span className="w-6 h-6 rounded-full bg-indigo-600 flex items-center justify-center text-[10px] font-bold text-white uppercase">
                  {(user?.name || user?.username || '?')[0]}
                </span>
                <span className="text-sm text-gray-400 truncate max-w-36">
                  {user?.name || user?.username}
                </span>
              </div>
              <button
                onClick={handleLogout}
                className="text-xs text-gray-500 hover:text-gray-200 border border-gray-700/60 rounded-md px-2.5 py-1 hover:border-gray-500 transition-all"
              >
                Sign out
              </button>
            </>
          ) : (
            <button
              onClick={handleLogin}
              className="text-sm bg-indigo-600 text-white rounded-lg px-4 py-1.5 hover:bg-indigo-500 transition-all shadow-lg shadow-indigo-900/40 font-medium"
            >
              Sign in
            </button>
          )}
        </div>
      </div>
    </nav>
  )
}
