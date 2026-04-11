import { AgentName } from '../types'

// TODO: Add an entry per agent in your workflow.
// Keys are the agent name strings returned by the backend.
// Values are Tailwind CSS class names defined in index.css (e.g. agent-badge-*).
// Example:
//   triage: 'agent-badge-triage',
//   your_agent: 'agent-badge-your-agent',
const BADGE_CLASSES: Record<string, string> = {}

// TODO: Add a human-readable label for each agent.
// Example:
//   triage: 'Triage',
//   your_agent: 'Your Agent',
const AGENT_LABELS: Record<string, string> = {}

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
