import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

function fmt(n: number | null | undefined, d = 2) {
  if (n == null) return '—'
  return Number(n).toFixed(d)
}

function ProgBar({ val, max, color = '#00e5cc' }: { val: number; max: number; color?: string }) {
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
  if (regime === 'trending')  return { bg: 'rgba(0,229,204,0.08)',   color: '#00e5cc', border: '1px solid rgba(0,229,204,0.2)' }
  if (regime === 'ranging')   return { bg: 'rgba(240,180,41,0.08)',  color: '#f0b429', border: '1px solid rgba(240,180,41,0.2)' }
  return                             { bg: 'rgba(255,61,90,0.08)',   color: '#ff3d5a', border: '1px solid rgba(255,61,90,0.2)'  }
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

  const topStats = [
    { l: 'Win Rate',      v: summary?.win_rate  != null ? `${summary.win_rate}%`                          : '—', c: '#00e5cc' },
    { l: 'Net P&L',       v: netPnl             != null ? `${netPnl >= 0 ? '+' : ''}${fmt(netPnl)}R`     : '—', c: netPnl != null ? (netPnl >= 0 ? '#00e5cc' : '#ff3d5a') : 'var(--color-tx)' },
    { l: 'Total Trades',  v: summary?.total_trades != null ? String(summary.total_trades)                 : '—', c: 'var(--color-tx)' },
    { l: 'Profit Factor', v: '—', c: '#00e5cc' },
    { l: 'Avg Duration',  v: '—', c: 'var(--color-tx)' },
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
                  <span className="font-mono" style={{ fontSize: 11, color: p.net_r >= 0 ? '#00e5cc' : '#ff3d5a' }}>
                    {p.net_r >= 0 ? '+' : ''}{fmt(p.net_r)}R
                  </span>
                  <span className="font-mono" style={{ fontSize: 11, color: 'var(--color-tx3)' }}>
                    {p.win_rate}%
                  </span>
                </div>
              </div>
              <ProgBar val={p.win_rate} max={100} color={p.net_r >= 0 ? '#00e5cc' : '#ff3d5a'} />
            </div>
          ))}
        </div>

        {/* By Regime */}
        <div className="rounded-[14px] p-5" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
            By Regime
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
                    <span className="font-mono" style={{ fontSize: 11, color: r.net_r >= 0 ? '#00e5cc' : '#ff3d5a' }}>
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
                <ProgBar val={r.win_rate} max={100} color={r.net_r >= 0 ? '#00e5cc' : '#ff3d5a'} />
              </div>
            )
          })}
        </div>

      </div>
    </div>
  )
}
