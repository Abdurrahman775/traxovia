import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

// ── Strategy benchmark data (from backtests 2024-01-01 → 2026-05-25) ─────────
const BENCHMARK: {
  pair: string; trades: number; wr: number; netR: number; avgR: number; maxDD: number
  sessions: string
}[] = [
  { pair: 'XAUUSD', trades: 43,  wr: 60.5, netR: 16.00, avgR: 0.372, maxDD: 3.0,
    sessions: '07–17h UTC' },
  { pair: 'EURUSD', trades: 59,  wr: 61.0, netR: 12.98, avgR: 0.220, maxDD: 8.0,
    sessions: '04–05h · 07–11h · 12–14h · 16–17h' },
  { pair: 'AUDUSD', trades: 55,  wr: 56.4, netR: 14.99, avgR: 0.273, maxDD: 5.0,
    sessions: '01–02h · 08–10h · 12–15h · 16–18h' },
  { pair: 'GBPUSD', trades: 52,  wr: 55.8, netR: 10.00, avgR: 0.192, maxDD: 8.0,
    sessions: '00–01h · 04–06h · 09–10h · 13–15h' },
  { pair: 'USDJPY', trades: 54,  wr: 55.6, netR:  8.99, avgR: 0.167, maxDD: 11.0,
    sessions: '00–01h · 03–04h · 05–07h · 08–09h' },
]

function fmt(n: number | null | undefined, d = 2) {
  if (n == null) return '—'
  return Number(n).toFixed(d)
}

function ProgBar({ val, max, color = '#d4a853' }: { val: number; max: number; color?: string }) {
  return (
    <div style={{ height: 5, background: 'var(--color-card-border)', borderRadius: 3, overflow: 'hidden' }}>
      <div style={{
        height: '100%', borderRadius: 3, transition: 'width 0.5s',
        width: `${Math.min(100, (val / (max || 1)) * 100)}%`,
        background: color,
      }} />
    </div>
  )
}

function regimeBadge(regime: string) {
  if (regime === 'trending')  return { bg: 'rgba(212,168,83,0.08)',   color: '#d4a853', border: '1px solid rgba(212,168,83,0.2)' }
  if (regime === 'ranging')   return { bg: 'rgba(240,180,41,0.08)',  color: '#f0b429', border: '1px solid rgba(240,180,41,0.2)' }
  return                             { bg: 'rgba(232,84,79,0.08)',   color: '#e8544f', border: '1px solid rgba(232,84,79,0.2)'  }
}

export default function Analytics() {
  const { data: summary } = useQuery({
    queryKey: ['analytics-summary'],
    queryFn: () => api.get('/analytics/summary').then(r => r.data),
    retry: false,
    refetchInterval: (q) => q.state.status === 'error' ? false : 30_000,
  })

  const { data: byPair = [] } = useQuery({
    queryKey: ['analytics-pair'],
    queryFn: () => api.get('/analytics/by-pair').then(r => Array.isArray(r.data) ? r.data : []),
    retry: false,
    refetchInterval: (q) => q.state.status === 'error' ? false : 60_000,
  })

  const { data: byRegime = [] } = useQuery({
    queryKey: ['analytics-regime'],
    queryFn: () => api.get('/analytics/by-regime').then(r => Array.isArray(r.data) ? r.data : []),
    retry: false,
    refetchInterval: (q) => q.state.status === 'error' ? false : 60_000,
  })

  const pairList  = byPair  as any[]
  const regList   = byRegime as any[]

  const bestPair = pairList.length > 0 ? pairList[0].pair : '—'
  const netPnl   = summary?.net_pnl_r ?? null

  const pf   = summary?.profit_factor
  const avgD = summary?.avg_duration_hours
  const topStats = [
    { l: 'Win Rate',      v: summary?.win_rate  != null ? `${summary.win_rate}%`                          : '—', c: '#d4a853' },
    { l: 'Net P&L',       v: netPnl             != null ? `${netPnl >= 0 ? '+' : ''}${fmt(netPnl)}R`     : '—', c: netPnl != null ? (netPnl >= 0 ? '#d4a853' : '#e8544f') : 'var(--color-tx)' },
    { l: 'Total Trades',  v: summary?.total_trades != null ? String(summary.total_trades)                 : '—', c: 'var(--color-tx)' },
    { l: 'Profit Factor', v: pf != null ? fmt(pf, 2) : '—', c: pf != null ? (pf >= 1 ? '#d4a853' : '#e8544f') : '#d4a853' },
    { l: 'Avg Duration',  v: avgD != null ? `${avgD}h` : '—', c: 'var(--color-tx)' },
    { l: 'Best Pair',     v: bestPair,                                                                         c: '#4f8ef7' },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

      {/* ── 6 stat cards ── */}
      <div className="rg3">
        {topStats.map(m => (
          <div key={m.l}
            className="rounded-[10px] p-4"
            style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
            <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
              {m.l}
            </div>
            <div className="font-head font-bold" style={{ fontSize: 22, color: m.c }}>
              {m.v}
            </div>
          </div>
        ))}
      </div>

      {/* ── By Pair + By Regime ── */}
      <div className="rg2">

        {/* By Pair */}
        <div className="rounded-[14px] p-5" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
            By Pair
          </div>
          {pairList.length === 0 ? (
            <div className="font-mono text-xs text-center py-8" style={{ color: 'var(--color-tx3)' }}>No closed trades yet</div>
          ) : pairList.map((p: any) => (
            <div key={p.pair} style={{ padding: '10px 0', borderBottom: '1px solid var(--color-card-border)' }}>
              <div className="flex justify-between mb-[5px]">
                <span className="font-mono" style={{ fontSize: 12 }}>{p.pair}</span>
                <div className="flex gap-3">
                  <span className="font-mono" style={{ fontSize: 11, color: p.net_r >= 0 ? '#d4a853' : '#e8544f' }}>
                    {p.net_r >= 0 ? '+' : ''}{fmt(p.net_r)}R
                  </span>
                  <span className="font-mono" style={{ fontSize: 11, color: 'var(--color-tx3)' }}>
                    {p.win_rate}%
                  </span>
                </div>
              </div>
              <ProgBar val={p.win_rate} max={100} color={p.net_r >= 0 ? '#d4a853' : '#e8544f'} />
            </div>
          ))}
        </div>

        {/* By D1 Structure */}
        <div className="rounded-[14px] p-5" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
            By D1 Structure
          </div>
          {regList.length === 0 ? (
            <div className="font-mono text-xs text-center py-8" style={{ color: 'var(--color-tx3)' }}>No closed trades yet</div>
          ) : regList.map((r: any) => {
            const badge = regimeBadge(r.regime)
            return (
              <div key={r.regime} style={{ padding: '12px 0', borderBottom: '1px solid var(--color-card-border)' }}>
                <div className="flex justify-between mb-[5px]">
                  <span className="inline-flex items-center gap-1 font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest"
                    style={{ background: badge.bg, color: badge.color, border: badge.border }}>
                    {(r.regime ?? '—').toUpperCase()}
                  </span>
                  <div className="flex gap-[10px]">
                    <span className="font-mono" style={{ fontSize: 11, color: r.net_r >= 0 ? '#d4a853' : '#e8544f' }}>
                      {r.net_r >= 0 ? '+' : ''}{fmt(r.net_r)}R
                    </span>
                    <span className="font-mono" style={{ fontSize: 11, color: 'var(--color-tx3)' }}>
                      {r.win_rate}%
                    </span>
                    <span className="font-mono" style={{ fontSize: 11, color: 'var(--color-tx3)' }}>
                      {r.total}tr
                    </span>
                  </div>
                </div>
                <ProgBar val={r.win_rate} max={100} color={r.net_r >= 0 ? '#d4a853' : '#e8544f'} />
              </div>
            )
          })}
        </div>

      </div>

      {/* ── Strategy Benchmark ── */}
      <div className="rounded-[14px] p-5" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
        <div className="flex items-center justify-between" style={{ marginBottom: 14 }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase" style={{ color: 'var(--color-tx3)' }}>
            Strategy Benchmark — All 5 Pairs
          </div>
          <span className="font-mono text-[9px] px-2 py-0.5 rounded tracking-widest"
            style={{ background: 'rgba(212,168,83,0.08)', color: '#d4a853', border: '1px solid rgba(212,168,83,0.2)' }}>
            2024-01-01 → 2026-05-25
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                {['Pair','Trades','Win Rate','Net R','Avg R','Max DD','ICT Sessions (UTC)','Gates'].map(h => (
                  <th key={h} className="font-mono text-[9px] tracking-widest text-left py-2 px-3 uppercase"
                    style={{ color: 'var(--color-tx3)', borderBottom: '1px solid var(--color-card-border)', whiteSpace: 'nowrap' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {BENCHMARK.map(b => (
                <tr key={b.pair} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}
                  onMouseEnter={e => (e.currentTarget as HTMLTableRowElement).style.background = 'rgba(255,255,255,0.02)'}
                  onMouseLeave={e => (e.currentTarget as HTMLTableRowElement).style.background = ''}>
                  <td className="font-mono font-bold py-3 px-3" style={{ fontSize: 12, color: 'var(--color-tx)' }}>{b.pair}</td>
                  <td className="font-mono py-3 px-3" style={{ fontSize: 11, color: 'var(--color-tx2)' }}>{b.trades}</td>
                  <td className="font-mono py-3 px-3" style={{ fontSize: 11, color: '#d4a853' }}>{b.wr}%</td>
                  <td className="font-mono py-3 px-3" style={{ fontSize: 11, color: b.netR >= 0 ? '#d4a853' : '#e8544f' }}>
                    {b.netR >= 0 ? '+' : ''}{b.netR.toFixed(2)}R
                  </td>
                  <td className="font-mono py-3 px-3" style={{ fontSize: 11, color: b.avgR >= 0.15 ? '#d4a853' : '#f0b429' }}>
                    {b.avgR >= 0 ? '+' : ''}{b.avgR.toFixed(3)}R
                  </td>
                  <td className="font-mono py-3 px-3" style={{ fontSize: 11, color: b.maxDD <= 10 ? '#c9953a' : b.maxDD <= 20 ? '#f0b429' : '#e8544f' }}>
                    {b.maxDD.toFixed(1)}%
                  </td>
                  <td className="font-mono py-3 px-3" style={{ fontSize: 10, color: 'var(--color-tx3)', whiteSpace: 'nowrap' }}>
                    {b.sessions}
                  </td>
                  <td className="py-3 px-3">
                    <span className="font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest"
                      style={{ background: 'rgba(0,229,150,0.1)', color: '#c9953a', border: '1px solid rgba(0,229,150,0.25)' }}>
                      ✓ PASS
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr style={{ borderTop: '1px solid var(--color-card-border)' }}>
                <td className="font-mono font-bold py-3 px-3" style={{ fontSize: 11, color: 'var(--color-tx3)' }}>TOTAL</td>
                <td className="font-mono py-3 px-3" style={{ fontSize: 11, color: 'var(--color-tx2)' }}>
                  {BENCHMARK.reduce((s, b) => s + b.trades, 0)}
                </td>
                <td className="font-mono py-3 px-3" style={{ fontSize: 11, color: '#d4a853' }}>
                  {(BENCHMARK.reduce((s, b) => s + b.wr, 0) / BENCHMARK.length).toFixed(1)}%
                </td>
                <td className="font-mono py-3 px-3" style={{ fontSize: 11, color: '#d4a853' }}>
                  +{BENCHMARK.reduce((s, b) => s + b.netR, 0).toFixed(2)}R
                </td>
                <td className="font-mono py-3 px-3" style={{ fontSize: 11, color: '#d4a853' }}>
                  +{(BENCHMARK.reduce((s, b) => s + b.avgR, 0) / BENCHMARK.length).toFixed(3)}R
                </td>
                <td colSpan={3} />
              </tr>
            </tfoot>
          </table>
        </div>

        <div className="font-mono text-[9px] mt-3" style={{ color: 'var(--color-tx3)' }}>
          ⚡ ICT strategy: D1 structure → H4 bias → Order Block + FVG → CHOCH entry · 3R target · SL→BE at 1R · Session filters applied per pair
        </div>
      </div>

    </div>
  )
}
