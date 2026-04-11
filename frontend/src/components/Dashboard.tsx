import { useEffect, useState } from 'react'
import { useIsAuthenticated } from '@azure/msal-react'
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend,
} from 'recharts'
import { useApiToken, fetchPortfolio } from '../hooks/useApi'

interface Holding {
  symbol: string
  name: string
  sector: string
  shares: number
  current_price: number
  market_value: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  weight_pct: number
}

interface SectorAllocation {
  sector: string
  weight: number
}

interface Performance {
  total_value: number
  ytd_return: number
  one_year_return: number
  three_year_annualized: number
  sharpe_ratio: number
  alpha: number
  beta: number
  max_drawdown: number
  volatility: number
}

const SECTOR_COLORS = [
  '#6366f1', '#3b82f6', '#10b981', '#f59e0b',
  '#ef4444', '#8b5cf6', '#14b8a6', '#f97316',
]

function formatCurrency(v: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v)
}

function pnlClass(v: number) {
  return v >= 0 ? 'text-emerald-400' : 'text-red-400'
}

export function Dashboard() {
  const { getToken } = useApiToken()
  const isAuthenticated = useIsAuthenticated()
  const [holdings, setHoldings] = useState<Holding[]>([])
  const [allocation, setAllocation] = useState<SectorAllocation[]>([])
  const [performance, setPerformance] = useState<Performance | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const token = await getToken()
        const [hRes, aRes, pRes] = await Promise.all([
          fetchPortfolio('holdings', token),
          fetchPortfolio('sector-allocation', token),
          fetchPortfolio('performance', token),
        ])
        setHoldings(hRes.holdings || [])
        setAllocation(aRes.allocations || [])
        setPerformance(pRes.performance || null)
      } catch (e) {
        setError('Failed to load portfolio data.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [isAuthenticated])

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <span className="inline-flex gap-2 text-gray-500 text-sm items-center">
        <svg className="w-4 h-4 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
        </svg>
        Loading portfolio...
      </span>
    </div>
  )

  if (!isAuthenticated) return (
    <div className="flex flex-col items-center justify-center h-[calc(100vh-10rem)] text-center select-none">
      <div className="w-16 h-16 rounded-2xl bg-indigo-600/20 ring-1 ring-indigo-500/30 flex items-center justify-center mb-6">
        <svg className="w-8 h-8 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
        </svg>
      </div>
      <h2 className="text-xl font-semibold text-gray-200 mb-2">Sign in to view your portfolio</h2>
      <p className="text-sm text-gray-500 max-w-sm mb-6 leading-relaxed">
        Your personal holdings, performance metrics, and sector allocation are protected by Entra ID.
        Sign in to see data scoped to your account.
      </p>
      <div className="flex flex-col items-center gap-3 text-xs text-gray-600">
        <div className="flex items-center gap-6">
          {[
            { icon: 'M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z', label: 'Row-level security' },
            { icon: 'M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z', label: 'Per-user identity' },
            { icon: 'M13.5 10.5V6.75a4.5 4.5 0 1 1 9 0v3.75M3.75 21.75h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H3.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z', label: 'Zero cross-tenant leakage' },
          ].map(({ icon, label }) => (
            <div key={label} className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d={icon} />
              </svg>
              <span>{label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )

  if (error) return <div className="text-center py-20 text-red-400">{error}</div>

  const topHoldings = [...holdings].sort((a, b) => b.market_value - a.market_value).slice(0, 5)

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      {performance && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Value', value: formatCurrency(performance.total_value) },
            { label: 'YTD Return', value: `${performance.ytd_return > 0 ? '+' : ''}${performance.ytd_return}%`, cls: pnlClass(performance.ytd_return) },
            { label: 'Sharpe Ratio', value: performance.sharpe_ratio.toFixed(2) },
            { label: 'Alpha', value: `${performance.alpha > 0 ? '+' : ''}${performance.alpha.toFixed(1)}%`, cls: pnlClass(performance.alpha) },
          ].map(({ label, value, cls }) => (
            <div key={label} className="bg-gray-900 rounded-xl border border-gray-800 p-4 shadow-lg">
              <p className="text-xs text-gray-500 mb-1 uppercase tracking-wide">{label}</p>
              <p className={`text-xl font-semibold ${cls ?? 'text-gray-100'}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Charts row */}
      <div className="grid md:grid-cols-2 gap-6">
        {/* Sector pie */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 shadow-lg">
          <h3 className="font-semibold text-sm text-gray-300 mb-3">Sector Allocation</h3>
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie
                data={allocation}
                dataKey="weight"
                nameKey="sector"
                cx="50%"
                cy="50%"
                outerRadius={90}
                label={({ sector, weight }) => `${sector} ${weight}%`}
                labelLine={false}
              >
                {allocation.map((_, i) => (
                  <Cell key={i} fill={SECTOR_COLORS[i % SECTOR_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip formatter={(v: number) => `${v}%`} contentStyle={{ backgroundColor: '#111827', border: '1px solid #1f2937', borderRadius: '8px', color: '#f3f4f6' }} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Top holdings bar */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 shadow-lg">
          <h3 className="font-semibold text-sm text-gray-300 mb-3">Top Holdings by Value</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={topHoldings} layout="vertical" margin={{ left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis type="number" tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} tick={{ fill: '#6b7280' }} />
              <YAxis type="category" dataKey="symbol" width={50} tick={{ fill: '#9ca3af' }} />
              <Tooltip formatter={(v: number) => formatCurrency(v)} contentStyle={{ backgroundColor: '#111827', border: '1px solid #1f2937', borderRadius: '8px', color: '#f3f4f6' }} />
              <Bar dataKey="market_value" fill="#6366f1" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Holdings table */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 shadow-lg overflow-hidden">
        <h3 className="font-semibold text-sm text-gray-300 px-4 py-3 border-b border-gray-800">
          All Holdings
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-800/60 text-xs text-gray-500 uppercase">
              <tr>
                {['Symbol', 'Name', 'Sector', 'Shares', 'Price', 'Value', 'P&L', 'Weight'].map((h) => (
                  <th key={h} className="px-4 py-2 text-left font-medium tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {holdings.map((h) => (
                <tr key={h.symbol} className="hover:bg-gray-800/40 transition-colors">
                  <td className="px-4 py-2 font-semibold text-indigo-400">{h.symbol}</td>
                  <td className="px-4 py-2 text-gray-300 truncate max-w-32">{h.name}</td>
                  <td className="px-4 py-2 text-gray-500">{h.sector}</td>
                  <td className="px-4 py-2 tabular-nums">{h.shares}</td>
                  <td className="px-4 py-2 tabular-nums">{formatCurrency(h.current_price || (h as any).value / h.shares)}</td>
                  <td className="px-4 py-2 tabular-nums">{formatCurrency(h.market_value || (h as any).value)}</td>
                  <td className={`px-4 py-2 tabular-nums ${pnlClass(h.unrealized_pnl_pct || (h as any).pnl_pct)}`}>
                    {(h.unrealized_pnl_pct ?? (h as any).pnl_pct ?? 0) > 0 ? '+' : ''}{(h.unrealized_pnl_pct ?? (h as any).pnl_pct ?? 0).toFixed(1)}%
                  </td>
                  <td className="px-4 py-2 tabular-nums">{(h.weight_pct ?? (h as any).weight ?? 0).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
