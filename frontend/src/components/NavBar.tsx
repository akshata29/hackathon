import { useMsal, useIsAuthenticated } from '@azure/msal-react'
import { loginRequest } from '../authConfig'

type Tab = 'chat' | 'dashboard'

interface NavBarProps {
  activeTab: Tab
  onTabChange: (tab: Tab) => void
}

export function NavBar({ activeTab, onTabChange }: NavBarProps) {
  const { instance, accounts } = useMsal()
  const isAuthenticated = useIsAuthenticated()
  const user = accounts[0]

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
        </div>
        <div className="flex items-center gap-3">
          {isAuthenticated ? (
            <>
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
