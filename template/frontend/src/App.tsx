import { useState } from 'react'
import { useIsAuthenticated } from '@azure/msal-react'
import { ChatPanel } from './components/ChatPanel'
import { NavBar } from './components/NavBar'

// TODO: Create your domain dashboard component and import it here.
// import { Dashboard } from './components/Dashboard'

type Tab = 'chat' | 'dashboard'

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

  return (
    <div className="min-h-screen flex flex-col">
      <NavBar activeTab={activeTab} onTabChange={setActiveTab} />
      <main className="flex-1 flex flex-col px-3 py-3">
        {activeTab === 'chat' ? (
          <ChatPanel />
        ) : (
          // TODO: Replace DashboardPlaceholder with <Dashboard /> once built.
          <DashboardPlaceholder />
        )}
      </main>
    </div>
  )
}
