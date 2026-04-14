import { useState, useRef, useCallback, useEffect } from 'react'
import { useIsAuthenticated } from '@azure/msal-react'
import { useMsal } from '@azure/msal-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { loginRequest, tokenRequest, backendUrl } from '../authConfig'
import { ChatMessage, StreamEvent, HandoffTrace, SessionSummary, Session } from '../types'
import { AgentBadge } from './AgentBadge'
import { AuthFlowPanel } from './AuthFlowPanel'
import type { DemoMode } from '../App'

function generateId() {
  return Math.random().toString(36).slice(2)
}

const PROMPT_GROUPS = [
  {
    label: 'Economic Data',
    badge: 'Alpha Vantage MCP',
    color: 'text-emerald-400',
    border: 'border-emerald-900/60',
    requiresAuth: false,
    prompts: [
      'What is the current Fed funds rate and 10-year treasury yield?',
      'Show CPI and inflation trend over the last 12 months',
      'What does the yield curve shape signal for recession risk?',
    ],
  },
  {
    label: 'Market Intelligence',
    badge: 'Bing grounding',
    color: 'text-sky-400',
    border: 'border-sky-900/60',
    requiresAuth: false,
    prompts: [
      'What are the latest analyst upgrades or downgrades for NVDA?',
      'Summarize today\'s market-moving news for the tech sector',
      'What geopolitical risks are currently affecting energy stocks?',
    ],
  },
  {
    label: 'Portfolio Data',
    badge: 'Portfolio MCP (auth)',
    color: 'text-violet-400',
    border: 'border-violet-900/60',
    requiresAuth: true,
    prompts: [
      'Show my current holdings, sector weights, and cash position',
      'What is my portfolio Sharpe ratio and max drawdown this year?',
      'Which positions have the highest concentration risk?',
    ],
  },
  {
    label: 'Real-time Quotes',
    badge: 'Yahoo Finance MCP',
    color: 'text-orange-400',
    border: 'border-orange-900/60',
    requiresAuth: false,
    prompts: [
      'Get AAPL current P/E and EV/EBITDA vs sector median',
      'Show MSFT analyst price targets and recommendation breakdown',
      'What are the 52-week range and moving averages for TSLA?',
    ],
  },
  {
    label: 'GitHub Intelligence',
    badge: 'GitHub MCP (connect)',
    color: 'text-teal-400',
    border: 'border-teal-900/60',
    requiresAuth: true,
    prompts: [
      'How active is Microsoft\'s engineering on GitHub? Analyze MSFT commit velocity',
      'Compare open-source health of Meta vs Google — which shows stronger dev momentum?',
      'What is the release cadence and issue backlog for NVIDIA\'s CUDA repos?',
    ],
  },
  {
    label: 'Handoff Routing',
    badge: 'triage -> specialist',
    color: 'text-yellow-400',
    border: 'border-yellow-900/60',
    requiresAuth: false,
    prompts: [
      'What does the latest non-farm payroll mean for rate expectations?',
      'Are bank stocks attractive given the current rate environment?',
      'How is dollar strength affecting emerging market equities?',
    ],
  },
  {
    label: 'ESG Advisor',
    badge: 'A2A / LangChain agent',
    color: 'text-lime-400',
    border: 'border-lime-900/60',
    requiresAuth: false,
    prompts: [
      'What is the ESG risk score for Microsoft and how does it compare to its tech peers?',
      'Are there any ESG controversies or governance flags I should know about for Tesla?',
      'Benchmark the ESG performance of MSFT, AAPL, and GOOGL against their sector peers',
    ],
  },
  {
    label: 'Concurrent Analysis',
    badge: 'all agents in parallel',
    color: 'text-rose-400',
    border: 'border-rose-900/60',
    requiresAuth: true,
    prompts: [
      'Give me a full portfolio review with macro context and current valuations',
      'Should I rebalance given current Fed policy and my positions?',
      'Analyze my risk exposure across macro, sector, and position levels',
      'Run a comprehensive sustainability review of my portfolio including ESG scores, macro risks, and position-level exposure',
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

  // Session history state
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)
  const [sessionLoadingId, setSessionLoadingId] = useState<string | null>(null)
  const [expandedFlows, setExpandedFlows] = useState<Set<string>>(new Set())

  const bottomRef = useRef<HTMLDivElement>(null)
  const isAuthenticated = useIsAuthenticated()
  const { instance, accounts } = useMsal()
  const activeAccountRef = useRef<string | undefined>(undefined)

  // Clear chat whenever the signed-in account changes (logout / switch user)
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
      return r.accessToken || null
    } catch {
      return null
    }
  }, [instance, accounts])

  // ---- Session management helpers ----

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

  // Load sessions once on mount and whenever auth state changes
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
        if (session.demo_mode && onDemoModeChange) {
          onDemoModeChange(session.demo_mode as DemoMode)
        }
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

    // Add a placeholder assistant message that we'll stream into
    const assistantId = generateId()
    const traces: HandoffTrace[] = []
    let lastAgent: string | undefined
    setMessages((prev) => [
      ...prev,
      {
        id: assistantId,
        role: 'assistant',
        content: '',
        traces,
        timestamp: new Date(),
      },
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
        body: JSON.stringify({
          message: userText,
          session_id: sessionId,
          mode: 'handoff',
          demo_mode: demoMode,
        }),
      })

      if (!res.ok || !res.body) {
        throw new Error(`HTTP ${res.status}`)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let streamDone = false

      while (!streamDone) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (data === '[DONE]') { streamDone = true; break }
          try {
            const event: StreamEvent = JSON.parse(data)
            if (event.type === 'agent_response' && event.content) {
              lastAgent = event.agent
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: m.content + event.content, agent: event.agent }
                    : m,
                ),
              )
            } else if (event.type === 'handoff') {
              traces.push({
                from_agent: event.from_agent!,
                to_agent: event.to_agent!,
              })
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId ? { ...m, traces: [...traces] } : m,
                ),
              )
            } else if (event.type === 'error' && event.content) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: m.content + `\n\n_Error: ${event.content}_` }
                    : m,
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
      // Refresh session list so new/updated session appears
      loadSessions()
    }
  }

  const sendMessage = () => handleSend(input)

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="flex h-[calc(100vh-5rem)] bg-gray-900/60 rounded-2xl shadow-2xl border border-white/5 overflow-hidden ring-1 ring-inset ring-white/5">

      {/* Left sidebar — always visible */}
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
              {locked && (
                <svg className="w-3 h-3 text-gray-600 ml-auto flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75M3.75 21.75h16.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H3.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
                </svg>
              )}
            </div>
            {locked ? (
              <p className="text-[10px] text-gray-600 leading-relaxed px-0.5 pb-0.5">
                Sign in to use these prompts
              </p>
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

        {/* Chat header */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-white/5 bg-gray-950/30">
          <div className="flex items-center gap-3">
            <span className="text-[11px] text-gray-600 font-medium tracking-wide uppercase">
              {messages.length === 0 ? 'New session' : `${messages.filter(m => m.role === 'user').length} message${messages.filter(m => m.role === 'user').length !== 1 ? 's' : ''}`}
            </span>
            <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
              demoMode === 'entra'
                ? 'bg-sky-950/40 border-sky-700/50 text-sky-300'
                : demoMode === 'entra-agent'
                ? 'bg-violet-950/40 border-violet-700/50 text-violet-300'
                : 'bg-amber-950/40 border-amber-700/50 text-amber-300'
            }`}>
              <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15M14.25 3.104c.251.023.501.05.75.082M19.8 15l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23-.607L5 14.5m14.8.5-1.57.393" />
              </svg>
              {demoMode === 'entra' ? 'Entra' : demoMode === 'okta-proxy' ? 'Okta Proxy' : demoMode === 'entra-agent' ? 'Agent ID' : 'Multi-IDP'} demo
            </span>
          </div>
          <button
            onClick={clearChat}
            disabled={loading}
            className="inline-flex items-center gap-1.5 text-[11px] text-gray-500 hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed bg-gray-800/60 hover:bg-gray-700/70 border border-transparent hover:border-gray-600/50 rounded-lg px-2.5 py-1.5 transition-all duration-150"
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            New chat
          </button>
        </div>
        {/* Message list */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center select-none">
              <div className="w-12 h-12 rounded-2xl bg-indigo-600/20 ring-1 ring-indigo-500/30 flex items-center justify-center mb-4">
                <svg className="w-6 h-6 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 0 1 .865-.501 48.172 48.172 0 0 0 3.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z" />
                </svg>
              </div>
              <p className="text-xl font-semibold text-gray-200 mb-1.5">Portfolio Advisor</p>
              <p className="text-sm text-gray-500">Pick a prompt from the panel, or type your own question below.</p>
            </div>
          )}
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`msg-in flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              {msg.role === 'user' ? (
                /* ── User bubble ── */
                <div className="max-w-[70%] rounded-2xl rounded-br-md px-4 py-2.5 text-sm leading-relaxed bg-indigo-600 text-white shadow-xl shadow-indigo-950/60">
                  {msg.content}
                </div>
              ) : (
                /* ── Assistant: full-width document layout ── */
                <div className="w-full">
                  {/* Agent + trace header */}
                  {(msg.agent || (msg.traces && msg.traces.length > 0)) && (
                    <div className="flex flex-wrap gap-1.5 mb-2 items-center">
                      {msg.agent && <AgentBadge agent={msg.agent} />}
                      {msg.traces && msg.traces.length > 0 && (
                        <span className="trace-pill">
                          {msg.traces.map((t) => t.to_agent).join(' \u2192 ')}
                        </span>
                      )}
                    </div>
                  )}
                  {/* Content */}
                  {msg.content ? (
                    <div className="prose-chat">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                  ) : loading ? (
                    <span className="inline-flex gap-1.5 py-0.5">
                      <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:0ms]" />
                      <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:150ms]" />
                      <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:300ms]" />
                    </span>
                  ) : null}
                  {/* Security Trace toggle */}
                  {msg.agent && (
                    <div className="mt-3">
                      <button
                        onClick={() => setExpandedFlows((prev) => {
                          const next = new Set(prev)
                          if (next.has(msg.id)) next.delete(msg.id)
                          else next.add(msg.id)
                          return next
                        })}
                        className={`inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide px-2.5 py-1 rounded-lg border transition-all duration-150 ${
                          expandedFlows.has(msg.id)
                            ? 'bg-indigo-950 text-indigo-300 border-indigo-700/60 ring-1 ring-indigo-500/30'
                            : 'text-gray-600 border-gray-700/40 hover:text-indigo-300 hover:border-indigo-700/50 hover:bg-indigo-950/40'
                        }`}
                      >
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />
                        </svg>
                        Security Trace
                      </button>
                      <AuthFlowPanel
                        agent={msg.agent}
                        open={expandedFlows.has(msg.id)}
                        onClose={() => setExpandedFlows((prev) => { const next = new Set(prev); next.delete(msg.id); return next })}
                        demoMode={demoMode}
                      />
                    </div>
                  )}
                  {/* Divider between assistant turns */}
                  <div className="mt-4 border-b border-white/5" />
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input area */}
        <div className="border-t border-white/5 bg-gray-950/50 p-3">
          <div className="flex gap-2 items-end">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKey}
              rows={1}
              placeholder="Ask about your portfolio or the market..."
              className="flex-1 resize-none rounded-xl border border-gray-700/60 bg-gray-800/80 text-gray-100 placeholder-gray-600 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/60 focus:border-indigo-500/40 transition-all"
            />
            <button
              onClick={sendMessage}
              disabled={loading || !input.trim()}
              className="bg-indigo-600 disabled:opacity-30 text-white rounded-xl px-4 py-2.5 text-sm font-medium hover:bg-indigo-500 active:scale-95 transition-all shadow-lg shadow-indigo-950/50"
            >
              Send
            </button>
          </div>
          {!isAuthenticated && (
            <p className="text-[11px] text-amber-500/80 mt-1.5 ml-1">
              Sign in to access your personalized portfolio data.
            </p>
          )}
        </div>
      </div>

      {/* Right sidebar — session history */}
      <div className="w-52 flex-shrink-0 border-l border-white/5 flex flex-col bg-gray-950/60">
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-white/5">
          <span className="text-[10px] font-semibold text-gray-600 uppercase tracking-[0.12em]">
            History
          </span>
          <button
            onClick={loadSessions}
            disabled={sessionsLoading}
            title="Refresh history"
            className="text-gray-600 hover:text-gray-300 disabled:opacity-30 transition-colors p-0.5 rounded"
          >
            <svg
              className={`w-3.5 h-3.5 ${sessionsLoading ? 'animate-spin' : ''}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
          </button>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessionsLoading && sessions.length === 0 && (
            <div className="flex items-center justify-center py-8">
              <span className="text-[11px] text-gray-600">Loading...</span>
            </div>
          )}

          {!sessionsLoading && sessions.length === 0 && (
            <div className="flex flex-col items-center justify-center py-8 px-2 text-center">
              <svg className="w-6 h-6 text-gray-700 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
              </svg>
              <p className="text-[11px] text-gray-600 leading-snug">
                Your conversations will appear here after you send your first message.
              </p>
            </div>
          )}

          {sessions.map((s) => {
            const isActive = s.id === sessionId
            const isLoading = sessionLoadingId === s.id
            return (
              <div
                key={s.id}
                onClick={() => openSession(s.id)}
                className={`group relative rounded-lg px-2.5 py-2 cursor-pointer transition-all duration-150 ${
                  isActive
                    ? 'bg-indigo-900/30 border border-indigo-700/40'
                    : 'bg-gray-800/40 border border-transparent hover:bg-gray-700/50 hover:border-gray-600/40'
                }`}
              >
                {isLoading && (
                  <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-gray-900/60">
                    <span className="inline-flex gap-1">
                      <span className="w-1 h-1 bg-indigo-400 rounded-full animate-bounce [animation-delay:0ms]" />
                      <span className="w-1 h-1 bg-indigo-400 rounded-full animate-bounce [animation-delay:100ms]" />
                      <span className="w-1 h-1 bg-indigo-400 rounded-full animate-bounce [animation-delay:200ms]" />
                    </span>
                  </div>
                )}
                <p className={`text-[11px] font-medium leading-snug line-clamp-2 pr-5 ${isActive ? 'text-indigo-200' : 'text-gray-300'}`}>
                  {s.title}
                </p>
                <div className="flex items-center gap-1.5 mt-1">
                  <span className="text-[10px] text-gray-600">
                    {formatSessionDate(s.updated_at)}
                  </span>
                  {s.message_count > 0 && (
                    <span className="text-[10px] text-gray-700">
                      &middot; {Math.floor(s.message_count / 2)} msg{Math.floor(s.message_count / 2) !== 1 ? 's' : ''}
                    </span>
                  )}
                </div>
                {/* Delete button — visible on hover */}
                <button
                  onClick={(e) => deleteSession(e, s.id)}
                  title="Delete session"
                  className="absolute top-1.5 right-1.5 opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 transition-all p-0.5 rounded"
                >
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                  </svg>
                </button>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
