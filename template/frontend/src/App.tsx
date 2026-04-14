import { useState } from 'react'
import { useIsAuthenticated } from '@azure/msal-react'
import { ChatPanel } from './components/ChatPanel'
import { NavBar } from './components/NavBar'

// TODO: Create your domain dashboard component and import it here.
// import { Dashboard } from './components/Dashboard'

type Tab = 'chat' | 'dashboard'
// demo_mode is passed to the backend with each chat request to select the MCP auth path.
// 'entra'       = production OBO flow (default)
// 'multi-idp'   = Option B demo: MultiIDPTokenVerifier accepts a non-Entra JWT on the MCP server
// 'okta-proxy'  = Option C demo: calls routed through an identity proxy (token swap)
// 'entra-agent' = Option D demo: backend uses Entra Agent Identity (DefaultAzureCredential, no OBO)
export type DemoMode = 'entra' | 'multi-idp' | 'okta-proxy' | 'entra-agent'

// Placeholder dashboard rendered until you build your domain Dashboard component.
function DashboardPlaceholder() {
  return (
    <div className="flex-1 flex items-center justify-center text-gray-500">
      <p>Dashboard coming soon. Replace this with your domain Dashboard component.</p>
    </div>
  )
}

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
          // TODO: Replace DashboardPlaceholder with <Dashboard /> once built.
          <DashboardPlaceholder />
        )}
      </main>
    </div>
  )
}
