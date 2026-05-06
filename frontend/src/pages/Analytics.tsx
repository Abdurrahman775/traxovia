import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

export default function Analytics() {
  const { data: summary } = useQuery({ queryKey: ['analytics-summary'], queryFn: () => api.get('/analytics/summary').then(r => r.data).catch(() => null) })
  const { data: byPair = [] } = useQuery({ queryKey: ['analytics-pair'], queryFn: () => api.get('/analytics/by-pair').then(r => r.data).catch(() => []) })
  const { data: byRegime = [] } = useQuery({ queryKey: ['analytics-regime'], queryFn: () => api.get('/analytics/by-regime').then(r => r.data).catch(() => []) })

  const regimeColor = (r: string) => r === 'trending' ? 'text-cyan-400' : r === 'volatile' ? 'text-red-400' : 'text-yellow-400'

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        {[
          { l: 'Win Rate',     v: summary ? `${summary.win_rate}%` : '—' },
          { l: 'Net P&L',      v: summary ? `${summary.net_pnl_r >= 0 ? '+' : ''}${summary.net_pnl_r}R` : '—' },
          { l: 'Total Trades', v: summary?.total_trades ?? '—' },
        ].map(m => (
          <div key={m.l} className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
            <div className="text-xs text-gray-500 font-mono mb-2">{m.l.toUpperCase()}</div>
            <div className="text-2xl font-bold text-cyan-400">{m.v}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-3">BY PAIR</div>
          {byPair.length === 0 ? <div className="text-sm text-gray-500">No data yet.</div> : byPair.map((p: any) => (
            <div key={p.pair} className="py-2.5 border-b border-slate-700/50 last:border-0">
              <div className="flex justify-between mb-1.5">
                <span className="font-mono text-sm">{p.pair}</span>
                <div className="flex gap-4">
                  <span className={`font-mono text-xs ${p.net_r >= 0 ? 'text-cyan-400' : 'text-red-400'}`}>
                    {p.net_r >= 0 ? '+' : ''}{p.net_r}R
                  </span>
                  <span className="font-mono text-xs text-gray-400">{p.win_rate}%</span>
                </div>
              </div>
              <div className="h-1 bg-slate-700 rounded">
                <div className={`h-full rounded ${p.net_r >= 0 ? 'bg-cyan-400' : 'bg-red-400'}`} style={{ width: `${p.win_rate}%` }} />
              </div>
            </div>
          ))}
        </div>

        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-3">BY REGIME</div>
          {byRegime.length === 0 ? <div className="text-sm text-gray-500">No data yet.</div> : byRegime.map((r: any) => (
            <div key={r.regime} className="py-3 border-b border-slate-700/50 last:border-0">
              <div className="flex justify-between mb-1">
                <span className={`px-2 py-0.5 rounded-full text-xs font-mono border ${r.regime === 'trending' ? 'text-cyan-400 bg-cyan-400/10 border-cyan-400/20' : r.regime === 'volatile' ? 'text-red-400 bg-red-400/10 border-red-400/20' : 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20'}`}>
                  {r.regime?.toUpperCase()}
                </span>
                <div className="flex gap-4">
                  <span className={`font-mono text-xs ${regimeColor(r.regime)}`}>{r.win_rate}% WR</span>
                  <span className={`font-mono text-xs ${r.net_r >= 0 ? 'text-cyan-400' : 'text-red-400'}`}>{r.net_r >= 0 ? '+' : ''}{r.net_r}R</span>
                </div>
              </div>
              <div className="text-xs text-gray-500 mt-1">
                {r.regime === 'ranging' ? 'Regime filter blocks most ranging signals' : 'Normal signal generation applied'}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
