import { useState } from 'react'
import { useIsAuthenticated } from '@azure/msal-react'
import { ChatPanel } from './components/ChatPanel'
import { Dashboard } from './components/Dashboard'
import { NavBar } from './components/NavBar'

type Tab = 'chat' | 'dashboard'
export type DemoMode = 'entra' | 'multi-idp' | 'okta-proxy' | 'entra-agent'

export default function App() {
  const isAuthenticated = useIsAuthenticated()
  const [activeTab, setActiveTab] = useState<Tab>('chat')
  const [demoMode, setDemoMode] = useState<DemoMode>('entra')

  return (
    <div className="min-h-screen flex flex-col">
      <NavBar activeTab={activeTab} onTabChange={setActiveTab} demoMode={demoMode} onDemoModeChange={setDemoMode} />
      <main className="flex-1 flex flex-col px-3 py-3">
        {activeTab === 'chat' ? (
          <ChatPanel demoMode={demoMode} onDemoModeChange={setDemoMode} />
        ) : (
          <Dashboard />
        )}
      </main>
    </div>
  )
}
