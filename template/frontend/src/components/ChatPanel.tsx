// ============================================================
// ChatPanel — TEMPLATE VERSION
//
// WHAT TO CUSTOMIZE:
//   1. PROMPT_GROUPS below — replace with your use-case prompts
//      See: template/docs/coding-prompts/README.md > Step 7
//   2. The empty-state heading ("My App Assistant") — line ~200
//   3. The empty-state subtitle — one sentence describing your app
//
// WHAT NOT TO TOUCH:
//   - Authentication logic (getToken, authHeaders) — core infrastructure
//   - Session management (loadSessions, openSession, deleteSession) — core
//   - SSE streaming (handleSend, event_stream reading) — core
//   - WebSocket and reconnection logic — core
// ============================================================

import { useState, useRef, useCallback, useEffect } from 'react'
import { useIsAuthenticated } from '@azure/msal-react'
import { useMsal } from '@azure/msal-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { tokenRequest, backendUrl } from '../authConfig'
import { ChatMessage, StreamEvent, HandoffTrace, SessionSummary, Session } from '../types'
import { AgentBadge } from './AgentBadge'
import { AuthFlowPanel } from './AuthFlowPanel'
import type { DemoMode } from '../App'

function generateId() {
  return Math.random().toString(36).slice(2)
}

// ============================================================
// DOMAIN-SPECIFIC: replace these prompt groups with your use-case
//
// Each group maps to one agent or capability area.
// - label:       section heading shown in the sidebar
// - badge:       small tag describing the data source or mechanism
// - color:       Tailwind text color class for the label
// - border:      Tailwind border color class
// - requiresAuth: true = only show prompts when the user is signed in
//                 (use this for prompts that require confidential data)
// - prompts:     3 example questions for this capability area
//
// COLOR PALETTE: text-emerald-400, text-sky-400, text-violet-400,
//                text-orange-400, text-yellow-400, text-rose-400,
//                text-pink-400, text-cyan-400
// ============================================================
const PROMPT_GROUPS = [
  {
    // TODO: rename to your first agent / capability area
    label: 'Agent A',
    badge: 'your data source',       // e.g. "Yahoo Finance MCP", "Bing Grounding"
    color: 'text-emerald-400',
    border: 'border-emerald-900/60',
    requiresAuth: false,
    prompts: [
      // TODO: add 3 representative prompts for this area
      'Example question 1 for Agent A',
      'Example question 2 for Agent A',
      'Example question 3 for Agent A',
    ],
  },
  {
    // TODO: rename to your second agent / capability area
    label: 'Agent B',
    badge: 'your data source',
    color: 'text-sky-400',
    border: 'border-sky-900/60',
    requiresAuth: false,
    prompts: [
      'Example question 1 for Agent B',
      'Example question 2 for Agent B',
      'Example question 3 for Agent B',
    ],
  },
  {
    // TODO: confidential data agent — requiresAuth: true means the user must sign in
    label: 'My Private Data',
    badge: 'private MCP (auth)',
    color: 'text-violet-400',
    border: 'border-violet-900/60',
    requiresAuth: true,            // requires Entra sign-in
    prompts: [
      'Example confidential question 1',
      'Example confidential question 2',
      'Example confidential question 3',
    ],
  },
  {
    // TODO: this group shows the handoff routing pattern
    label: 'Handoff Routing',
    badge: 'triage -> specialist',
    color: 'text-yellow-400',
    border: 'border-yellow-900/60',
    requiresAuth: false,
    prompts: [
      'Cross-domain question that triggers triage routing',
      'Another multi-intent question',
      'A third question that routes to different specialists',
    ],
  },
  {
    // TODO: this group shows the concurrent (comprehensive) analysis pattern
    label: 'Full Analysis',
    badge: 'all agents in parallel',
    color: 'text-rose-400',
    border: 'border-rose-900/60',
    requiresAuth: true,            // typically requires auth for comprehensive data
    prompts: [
      'Give me a complete analysis requiring all agents',
      'Run a comprehensive review of my data',
      'Synthesize insights from all available data sources',
    ],
  },
]

function formatSessionDate(isoString: string): string {
  const date = new Date(isoString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60_000)
  if (diffMin < 1) return 'Just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return `${diffH}h ago`
  const diffD = Math.floor(diffH / 24)
  if (diffD === 1) return 'Yesterday'
  if (diffD < 7) return `${diffD}d ago`
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function ChatPanel({ demoMode = 'entra', onDemoModeChange }: { demoMode?: DemoMode; onDemoModeChange?: (m: DemoMode) => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState(() => generateId())
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)
  const [sessionLoadingId, setSessionLoadingId] = useState<string | null>(null)

  const bottomRef = useRef<HTMLDivElement>(null)
  const isAuthenticated = useIsAuthenticated()
  const { instance, accounts } = useMsal()
  const activeAccountRef = useRef<string | undefined>(undefined)

  useEffect(() => {
    const currentId = accounts[0]?.homeAccountId
    if (activeAccountRef.current !== undefined && activeAccountRef.current !== currentId) {
      setMessages([])
      setInput('')
      setSessionId(generateId())
    }
    activeAccountRef.current = currentId
  }, [accounts])

  const getToken = useCallback(async (): Promise<string | null> => {
    if (!accounts.length) return null
    try {
      const r = await instance.acquireTokenSilent({ ...tokenRequest, account: accounts[0] })
      return r.accessToken
    } catch {
      return null
    }
  }, [instance, accounts])

  const authHeaders = useCallback(async (): Promise<Record<string, string>> => {
    const token = await getToken()
    return token ? { Authorization: `Bearer ${token}` } : {}
  }, [getToken])

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true)
    try {
      const headers = await authHeaders()
      const res = await fetch(`${backendUrl}/api/sessions`, { headers })
      if (res.ok) {
        const data = await res.json()
        setSessions(data.sessions ?? [])
      }
    } catch {
      // non-blocking
    } finally {
      setSessionsLoading(false)
    }
  }, [authHeaders])

  useEffect(() => {
    loadSessions()
  }, [isAuthenticated]) // eslint-disable-line react-hooks/exhaustive-deps

  const openSession = async (sid: string) => {
    if (sid === sessionId || loading) return
    setSessionLoadingId(sid)
    try {
      const headers = await authHeaders()
      const res = await fetch(`${backendUrl}/api/sessions/${sid}`, { headers })
      if (res.ok) {
        const session: Session = await res.json()
        setSessionId(session.id)
        setMessages(
          session.messages.map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            agent: m.agent,
            traces: m.traces,
            timestamp: new Date(m.timestamp),
          })),
        )
      }
    } catch {
      // non-blocking
    } finally {
      setSessionLoadingId(null)
    }
  }

  const deleteSession = async (e: React.MouseEvent, sid: string) => {
    e.stopPropagation()
    try {
      const headers = await authHeaders()
      await fetch(`${backendUrl}/api/sessions/${sid}`, {
        method: 'DELETE',
        headers,
      })
      setSessions((prev) => prev.filter((s) => s.id !== sid))
      if (sid === sessionId) {
        setMessages([])
        setInput('')
        setSessionId(generateId())
      }
    } catch {
      // non-blocking
    }
  }

  const clearChat = () => {
    setMessages([])
    setInput('')
    setSessionId(generateId())
  }

  const handleSend = async (text: string) => {
    if (!text.trim() || loading) return
    const userText = text.trim()
    setInput('')

    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: userText,
      timestamp: new Date(),
    }
    setMessages((prev) => [...prev, userMsg])
    setLoading(true)

    const assistantId = generateId()
    const traces: HandoffTrace[] = []
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: 'assistant', content: '', traces, timestamp: new Date() },
    ])

    try {
      const token = await getToken()
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      }
      if (token) headers['Authorization'] = `Bearer ${token}`

      const res = await fetch(`${backendUrl}/api/chat/message`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ message: userText, session_id: sessionId, mode: 'handoff', demo_mode: demoMode }),
      })

      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (data === '[DONE]') break
          try {
            const event: StreamEvent = JSON.parse(data)
            if (event.type === 'agent_response' && event.content) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: m.content + event.content, agent: event.agent }
                    : m,
                ),
              )
            } else if (event.type === 'handoff') {
              traces.push({ from_agent: event.from_agent!, to_agent: event.to_agent! })
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId ? { ...m, traces: [...traces] } : m,
                ),
              )
            }
          } catch {
            // Ignore malformed events
          }
        }
      }
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: `Error: ${(err as Error).message}` }
            : m,
        ),
      )
    } finally {
      setLoading(false)
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
      loadSessions()
    }
  }

  const sendMessage = () => handleSend(input)
  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  return (
    <div className="flex h-[calc(100vh-5rem)] bg-gray-900/60 rounded-2xl shadow-2xl border border-white/5 overflow-hidden ring-1 ring-inset ring-white/5">

      {/* Left sidebar — prompt groups */}
      <div className="w-64 flex-shrink-0 border-r border-white/5 overflow-y-auto bg-gray-950/60 p-3 space-y-2.5">
        <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-[0.12em] px-1 pt-1.5 pb-0.5">
          Example Prompts
        </p>
        {PROMPT_GROUPS.map((group) => {
          const locked = group.requiresAuth && !isAuthenticated
          return (
            <div key={group.label} className={`rounded-xl border ${locked ? 'border-gray-800/60 opacity-60' : group.border} bg-gray-900/70 p-2.5 space-y-1.5 relative`}>
              <div className="flex items-center gap-2 mb-2">
                <span className={`text-[11px] font-bold leading-none ${locked ? 'text-gray-600' : group.color}`}>{group.label}</span>
                <span className={`text-[9px] font-medium border rounded-full px-1.5 py-0.5 leading-none opacity-60 ${locked ? 'border-gray-700 text-gray-600' : `${group.border} ${group.color}`}`}>{group.badge}</span>
              </div>
              {locked ? (
                <p className="text-[10px] text-gray-600 leading-relaxed px-0.5 pb-0.5">Sign in to use these prompts</p>
              ) : (
                group.prompts.map((p) => (
                  <button
                    key={p}
                    onClick={() => handleSend(p)}
                    disabled={loading}
                    className="w-full text-left text-[11px] text-gray-400 hover:text-gray-100 disabled:opacity-30 bg-gray-800/50 hover:bg-gray-700/70 border border-transparent hover:border-gray-600/50 rounded-lg px-2.5 py-2 transition-all duration-150 leading-relaxed cursor-pointer"
                  >
                    {p}
                  </button>
                ))
              )}
            </div>
          )
        })}
      </div>

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0 bg-gray-900/40">
        <div className="flex items-center justify-between px-4 py-2 border-b border-white/5 bg-gray-950/30">
          <span className="text-[11px] text-gray-600 font-medium tracking-wide uppercase">
            {messages.length === 0 ? 'New session' : `${messages.filter(m => m.role === 'user').length} message${messages.filter(m => m.role === 'user').length !== 1 ? 's' : ''}`}
          </span>
          <button onClick={clearChat} disabled={loading} className="inline-flex items-center gap-1.5 text-[11px] text-gray-500 hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed bg-gray-800/60 hover:bg-gray-700/70 border border-transparent hover:border-gray-600/50 rounded-lg px-2.5 py-1.5 transition-all duration-150">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
            New chat
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center select-none">
              <div className="w-12 h-12 rounded-2xl bg-indigo-600/20 ring-1 ring-indigo-500/30 flex items-center justify-center mb-4">
                <svg className="w-6 h-6 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 0 1 .865-.501 48.172 48.172 0 0 0 3.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z" />
                </svg>
              </div>
              {/* TODO: update the heading and subtitle for your use-case */}
              <p className="text-xl font-semibold text-gray-200 mb-1.5">My App Assistant</p>
              <p className="text-sm text-gray-500">Pick a prompt from the panel, or type your question below.</p>
            </div>
          )}
          {messages.map((msg) => (
            <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {msg.role === 'user' ? (
                <div className="max-w-[70%] rounded-2xl rounded-br-md px-4 py-2.5 text-sm leading-relaxed bg-indigo-600 text-white shadow-xl shadow-indigo-950/60">
                  {msg.content}
                </div>
              ) : (
                <div className="w-full">
                  {(msg.agent || (msg.traces && msg.traces.length > 0)) && (
                    <div className="flex flex-wrap gap-1.5 mb-2 items-center">
                      {msg.agent && <AgentBadge agent={msg.agent} />}
                      {msg.traces && msg.traces.length > 0 && (
                        <span className="text-[10px] text-gray-500 font-mono">
                          {msg.traces.map((t) => t.to_agent).join(' \u2192 ')}
                        </span>
                      )}
                    </div>
                  )}
                  {msg.content ? (
                    <div className="prose prose-invert prose-sm max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                    </div>
                  ) : loading ? (
                    <span className="inline-flex gap-1.5 py-0.5">
                      <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:0ms]" />
                      <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:150ms]" />
                      <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:300ms]" />
                    </span>
                  ) : null}
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        <div className="px-6 py-4 border-t border-white/5 bg-gray-950/30">
          <div className="flex gap-3 items-end">
            <textarea
              className="flex-1 resize-none rounded-xl bg-gray-800/80 border border-gray-700/60 focus:border-indigo-500/60 focus:ring-1 focus:ring-indigo-500/30 text-sm text-gray-100 placeholder-gray-600 px-4 py-3 outline-none transition-all duration-200 min-h-[52px] max-h-40"
              placeholder="Ask a question..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKey}
              disabled={loading}
              rows={1}
            />
            <button
              onClick={sendMessage}
              disabled={loading || !input.trim()}
              className="flex-shrink-0 w-11 h-11 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-800 disabled:text-gray-600 text-white flex items-center justify-center transition-all duration-200 shadow-lg shadow-indigo-950/50 disabled:shadow-none"
            >
              {loading ? (
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" /></svg>
              ) : (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 12 3.269 3.125A59.769 59.769 0 0 1 21.485 12 59.768 59.768 0 0 1 3.27 20.875L5.999 12Zm0 0h7.5" /></svg>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Right sidebar — session history (core, do not modify) */}
      {isAuthenticated && (
        <div className="w-52 flex-shrink-0 border-l border-white/5 overflow-y-auto bg-gray-950/60 p-3 space-y-1.5">
          <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-[0.12em] px-1 pt-1.5 pb-0.5">
            {sessionsLoading ? 'Loading...' : 'History'}
          </p>
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => openSession(s.id)}
              disabled={loading || sessionLoadingId !== null}
              className={`w-full text-left rounded-lg px-2.5 py-2 transition-all duration-150 group relative ${s.id === sessionId ? 'bg-indigo-600/20 border border-indigo-500/30' : 'hover:bg-gray-800/60 border border-transparent hover:border-gray-700/50'}`}
            >
              <p className="text-[11px] font-medium text-gray-300 truncate leading-snug">{s.title}</p>
              <p className="text-[10px] text-gray-600 mt-0.5">{formatSessionDate(s.updated_at)}</p>
              <button
                onClick={(e) => deleteSession(e, s.id)}
                className="absolute right-1.5 top-1.5 opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 transition-all"
                title="Delete session"
              >
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" /></svg>
              </button>
            </button>
          ))}
          {sessions.length === 0 && !sessionsLoading && (
            <p className="text-[10px] text-gray-700 px-1">No sessions yet</p>
          )}
        </div>
      )}
    </div>
  )
}
