// Types for agent event stream messages

// TODO: Replace `string` with a union of your agent names, e.g.:
// export type AgentName = 'triage' | 'your_agent_1' | 'your_agent_2' | 'synthesis'
export type AgentName = string

export interface StreamEvent {
  type: 'session' | 'agent_response' | 'handoff' | 'status' | 'error' | 'done'
  session_id?: string
  agent?: AgentName
  content?: string
  from_agent?: AgentName
  to_agent?: AgentName
  message?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  agent?: AgentName
  traces?: HandoffTrace[]
  timestamp: Date
}

export interface HandoffTrace {
  from_agent: AgentName
  to_agent: AgentName
}

// Session management

export interface SessionSummary {
  id: string
  user_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface StoredMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  agent?: AgentName
  traces?: HandoffTrace[]
  timestamp: string
}

export interface Session extends SessionSummary {
  messages: StoredMessage[]
}
