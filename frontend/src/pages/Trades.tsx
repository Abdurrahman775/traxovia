import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

function fmt(n: number | null | undefined, d = 2) {
  if (n == null) return '—'
  return Number(n).toFixed(d)
}

type BadgeType = 'cyan' | 'red' | 'gray' | 'gold' | 'green'

const BADGE: Record<BadgeType, { bg: string; color: string; border: string }> = {
  cyan:  { bg: 'rgba(0,229,204,0.1)',   color: '#00e5cc', border: '1px solid rgba(0,229,204,0.2)'   },
  red:   { bg: 'rgba(255,61,90,0.1)',   color: '#ff3d5a', border: '1px solid rgba(255,61,90,0.2)'   },
  gold:  { bg: 'rgba(240,180,41,0.1)',  color: '#f0b429', border: '1px solid rgba(240,180,41,0.2)'  },
  green: { bg: 'rgba(0,229,150,0.1)',   color: '#00e596', border: '1px solid rgba(0,229,150,0.2)'   },
  gray:  { bg: 'var(--color-divider)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' },
}

function Badge({ type, children }: { type: BadgeType; children: React.ReactNode }) {
  const s = BADGE[type]
  return (
    <span
      className="inline-flex items-center font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest whitespace-nowrap"
      style={{ background: s.bg, color: s.color, border: s.border }}
    >
      {children}
    </span>
  )
}

function result(pnl_r: number | null, status: string): { label: string; type: BadgeType } {
  if (status === 'open') return { label: 'OPEN', type: 'cyan' }
  if (pnl_r == null)     return { label: 'BE',   type: 'gray' }
  if (pnl_r > 0)         return { label: 'WIN',  type: 'cyan' }
  if (pnl_r < 0)         return { label: 'LOSS', type: 'red'  }
  return                        { label: 'BE',   type: 'gray' }
}

export default function Trades() {
  const { data: raw = [] } = useQuery({
    queryKey: ['trades-all'],
    queryFn: () => api.get('/trades').then(r => Array.isArray(r.data) ? r.data : []),
    retry: false,
    refetchInterval: (q) => q.state.status === 'error' ? false : 30_000,
  })

  const trades = raw as any[]
  const closed = trades.filter((t: any) => t.status === 'closed')
  const wins   = closed.filter((t: any) => t.pnl_r > 0).length
  const netR   = closed.reduce((s: number, t: any) => s + (t.pnl_r || 0), 0)
  const wr     = closed.length > 0 ? Math.round(wins / closed.length * 100) : 0
  const open   = trades.filter((t: any) => t.status === 'open').length

  const statCards = [
    { t: 'Total Trades', v: closed.length,                                          c: '#00e5cc' },
    { t: 'Win Rate',     v: `${wr}%`,                                               c: '#00e5cc' },
    { t: 'Net P&L',      v: `${netR >= 0 ? '+' : ''}${netR.toFixed(1)}R`,           c: netR >= 0 ? '#00e5cc' : '#ff3d5a' },
    { t: 'Open Trades',  v: open,                                                    c: '#f0b429' },
  ]

  const TH_COLS = ['Pair', 'Dir', 'Result', 'P&L (R)', 'Pips', 'Slippage', 'Duration', 'Date']

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

      {/* ── 4 stat cards ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12 }}>
        {statCards.map(m => (
          <div key={m.t} className="rounded-[10px] p-4" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
            <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
              {m.t}
            </div>
            <div className="font-head font-bold" style={{ fontSize: 26, color: m.c }}>
              {m.v}
            </div>
          </div>
        ))}
      </div>

      {/* ── Trade History ── */}
      <div className="rounded-[14px] p-5" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
        <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
          Trade History
        </div>

        {trades.length === 0 ? (
          <div className="font-mono text-xs text-center py-10" style={{ color: 'var(--color-tx3)' }}>No trades yet</div>
        ) : (
          <table className="w-full border-collapse">
            <thead>
              <tr>
                {TH_COLS.map(h => (
                  <th key={h}
                    className="font-mono text-[9px] tracking-widest text-left py-[10px] px-3 uppercase"
                    style={{ color: 'var(--color-tx3)', borderBottom: '1px solid var(--color-card-border)' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {trades.map((t: any) => {
                const res = result(t.pnl_r, t.status)
                const pnl = t.pnl_r as number | null
                const pips = t.pips as number | null
                return (
                  <tr key={t.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}
                    onMouseEnter={e => (e.currentTarget as HTMLTableRowElement).style.background = 'rgba(255,255,255,0.02)'}
                    onMouseLeave={e => (e.currentTarget as HTMLTableRowElement).style.background = ''}>

                    {/* Pair */}
                    <td className="font-mono py-[11px] px-3 font-bold" style={{ fontSize: 12, color: 'var(--color-tx)' }}>
                      {t.pair}
                    </td>

                    {/* Dir */}
                    <td className="py-[11px] px-3">
                      <Badge type={t.direction === 'buy' ? 'cyan' : 'red'}>
                        {t.direction?.toUpperCase() ?? '—'}
                      </Badge>
                    </td>

                    {/* Result */}
                    <td className="py-[11px] px-3">
                      <Badge type={res.type}>{res.label}</Badge>
                    </td>

                    {/* P&L (R) */}
                    <td className="font-mono py-[11px] px-3" style={{
                      fontSize: 12,
                      color: pnl == null ? 'var(--color-tx3)' : pnl > 0 ? '#00e5cc' : pnl < 0 ? '#ff3d5a' : 'var(--color-tx2)',
                    }}>
                      {pnl != null ? `${pnl > 0 ? '+' : ''}${fmt(pnl)}R` : '—'}
                    </td>

                    {/* Pips */}
                    <td className="font-mono py-[11px] px-3" style={{
                      fontSize: 12,
                      color: pips == null ? 'var(--color-tx3)' : pips > 0 ? '#00e5cc' : '#ff3d5a',
                    }}>
                      {pips != null ? `${pips > 0 ? '+' : ''}${fmt(pips, 1)}` : '—'}
                    </td>

                    {/* Slippage — no field in API */}
                    <td className="font-mono py-[11px] px-3" style={{ fontSize: 12, color: 'var(--color-tx3)' }}>—</td>

                    {/* Duration */}
                    <td className="font-mono py-[11px] px-3" style={{ fontSize: 12, color: 'var(--color-tx2)' }}>
                      {t.duration_hours != null ? `${Number(t.duration_hours).toFixed(0)}h` : '—'}
                    </td>

                    {/* Date */}
                    <td className="font-mono py-[11px] px-3" style={{ fontSize: 12, color: 'var(--color-tx3)' }}>
                      {t.entry_time ? new Date(t.entry_time).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

    </div>
  )
}
