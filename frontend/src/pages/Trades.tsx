import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

export default function Trades() {
  const { data: trades = [], isLoading } = useQuery({
    queryKey: ['trades'],
    queryFn: () => api.get('/trades').then(r => r.data),
  })

  if (isLoading) return <div className="text-gray-400">Loading...</div>

  const closed = trades.filter((t: any) => t.status === 'closed')
  const wins = closed.filter((t: any) => t.pnl_r > 0).length
  const netR = closed.reduce((s: number, t: any) => s + (t.pnl_r || 0), 0)
  const wr = closed.length > 0 ? Math.round(wins / closed.length * 100) : 0

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-3">
        {[
          { l: 'Total Trades', v: closed.length },
          { l: 'Win Rate',     v: `${wr}%` },
          { l: 'Net P&L',      v: `${netR >= 0 ? '+' : ''}${netR.toFixed(1)}R` },
          { l: 'Open Trades',  v: trades.filter((t: any) => t.status === 'open').length },
        ].map(m => (
          <div key={m.l} className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
            <div className="text-xs text-gray-500 font-mono mb-2">{m.l.toUpperCase()}</div>
            <div className="text-2xl font-bold text-cyan-400">{m.v}</div>
          </div>
        ))}
      </div>

      <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
        <div className="text-xs text-gray-500 font-mono mb-4">TRADE HISTORY</div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-gray-500 font-mono border-b border-slate-700">
              {['Pair', 'Dir', 'P&L', 'Pips', 'Regime', 'Duration', 'Date'].map(h => (
                <th key={h} className="text-left py-2 px-3">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map((t: any) => (
              <tr key={t.id} className="border-b border-slate-700/30 hover:bg-slate-700/20">
                <td className="py-2.5 px-3 font-mono font-bold">{t.pair}</td>
                <td className="py-2.5 px-3">
                  <span className={`px-2 py-0.5 rounded text-xs font-mono ${t.direction === 'buy' ? 'bg-cyan-400/10 text-cyan-400' : 'bg-red-400/10 text-red-400'}`}>
                    {t.direction?.toUpperCase()}
                  </span>
                </td>
                <td className={`py-2.5 px-3 font-mono ${t.pnl_r > 0 ? 'text-cyan-400' : t.pnl_r < 0 ? 'text-red-400' : 'text-gray-400'}`}>
                  {t.pnl_r != null ? `${t.pnl_r > 0 ? '+' : ''}${Number(t.pnl_r).toFixed(2)}R` : '—'}
                </td>
                <td className={`py-2.5 px-3 font-mono text-xs ${t.pips > 0 ? 'text-cyan-400' : 'text-red-400'}`}>
                  {t.pips != null ? `${t.pips > 0 ? '+' : ''}${t.pips}` : '—'}
                </td>
                <td className="py-2.5 px-3">
                  {t.regime && (
                    <span className={`px-2 py-0.5 rounded-full text-xs font-mono border ${t.regime === 'trending' ? 'text-cyan-400 bg-cyan-400/10 border-cyan-400/20' : t.regime === 'volatile' ? 'text-red-400 bg-red-400/10 border-red-400/20' : 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20'}`}>
                      {t.regime.toUpperCase()}
                    </span>
                  )}
                </td>
                <td className="py-2.5 px-3 font-mono text-xs text-gray-400">
                  {t.duration_hours != null ? `${Number(t.duration_hours).toFixed(0)}h` : '—'}
                </td>
                <td className="py-2.5 px-3 font-mono text-xs text-gray-500">
                  {t.entry_time ? new Date(t.entry_time).toLocaleDateString() : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
