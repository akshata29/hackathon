import { AgentName } from '../types'

const BADGE_CLASSES: Record<string, string> = {
  triage: 'agent-badge-triage',
  market_intel: 'agent-badge-market',
  portfolio: 'agent-badge-portfolio',
  economic: 'agent-badge-economic',
  private_data: 'agent-badge-private',
  synthesis: 'agent-badge-synthesis',
}

const AGENT_LABELS: Record<string, string> = {
  triage: 'Triage',
  market_intel: 'Market Intel',
  portfolio: 'Portfolio',
  economic: 'Economic',
  private_data: 'Market Data',
  synthesis: 'Synthesis',
}

interface AgentBadgeProps {
  agent: AgentName
}

export function AgentBadge({ agent }: AgentBadgeProps) {
  const cls = BADGE_CLASSES[agent] || 'bg-gray-100 text-gray-700'
  const label = AGENT_LABELS[agent] || agent
  return (
    <span className={`agent-badge ${cls}`}>
      {label}
    </span>
  )
}
