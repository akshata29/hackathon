// ============================================================
// AuthFlowPanel — TEMPLATE STUB
//
// This is a placeholder for the security visualisation panel that shows
// end-to-end token flows for each auth pattern supported by the app.
//
// Reference implementation:
//   frontend/src/components/AuthFlowPanel.tsx
//
// When to build this:
//   - For demo or workshop sessions where you want to visualise auth flows
//   - For InfoSec / architecture review of your multi-agent auth design
//
// What the full implementation shows:
//   - Which auth pattern (Entra OBO / Multi-IDP / Okta Proxy) was used
//   - Live JWT claims from the MSAL session
//   - Each hop in the token chain: Browser -> Backend -> OBO -> MCP
//   - Security properties at each hop (audience, issuer, scope)
//   - Row-level security enforcement at the MCP layer
//
// To add to ChatPanel:
//   1. Import this component: import { AuthFlowPanel } from './AuthFlowPanel'
//   2. Render it after each assistant message:
//      <AuthFlowPanel agentName={msg.agent} demoMode={demoMode} />
//
// Coding prompt: See template/docs/coding-prompts/README.md > Step 7
// Reference: frontend/src/components/AuthFlowPanel.tsx
// ============================================================

import type { DemoMode } from '../App'

interface AuthFlowPanelProps {
  agentName?: string
  demoMode?: DemoMode
}

export function AuthFlowPanel({ agentName, demoMode = 'entra' }: AuthFlowPanelProps) {
  // TODO: replace this stub with a real auth flow visualisation.
  // See the reference implementation in frontend/src/components/AuthFlowPanel.tsx
  return (
    <div className="mt-1 px-3 py-2 rounded-md bg-gray-900/50 border border-gray-800/60 text-[11px] text-gray-500">
      <span className="font-medium text-gray-400">Auth flow:</span>{' '}
      {demoMode === 'entra' && 'Entra OBO (production)'}
      {demoMode === 'multi-idp' && 'Multi-IDP (Option B)'}
      {demoMode === 'okta-proxy' && 'Identity Proxy (Option C)'}
      {agentName && <span className="ml-2 text-gray-600">agent: {agentName}</span>}
    </div>
  )
}
