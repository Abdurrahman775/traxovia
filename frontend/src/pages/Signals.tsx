import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

type BadgeType = 'cyan' | 'red' | 'gold' | 'gray' | 'green'

const BADGE: Record<BadgeType, { bg: string; color: string; border: string }> = {
  cyan:  { bg: 'rgba(0,229,204,0.1)',    color: '#00e5cc', border: '1px solid rgba(0,229,204,0.2)'    },
  red:   { bg: 'rgba(255,61,90,0.1)',    color: '#ff3d5a', border: '1px solid rgba(255,61,90,0.2)'    },
  gold:  { bg: 'rgba(240,180,41,0.1)',   color: '#f0b429', border: '1px solid rgba(240,180,41,0.2)'   },
  green: { bg: 'rgba(0,229,150,0.1)',    color: '#00e596', border: '1px solid rgba(0,229,150,0.2)'    },
  gray:  { bg: 'var(--color-divider)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' },
}

function Badge({ type, children }: { type: BadgeType; children: React.ReactNode }) {
  const s = BADGE[type]
  return (
    <span className="inline-flex items-center font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest whitespace-nowrap"
      style={{ background: s.bg, color: s.color, border: s.border }}>
      {children}
    </span>
  )
}

function ProgBar({ val, max, color = '#00e5cc' }: { val: number; max: number; color?: string }) {
  return (
    <div style={{ height: 5, background: 'var(--color-card-border)', borderRadius: 3, overflow: 'hidden' }}>
      <div style={{
        height: '100%', borderRadius: 3, transition: 'width 0.5s',
        width: `${Math.min(100, (val / (max || 1)) * 100)}%`, background: color,
      }} />
    </div>
  )
}

function regimeBadgeType(regime: string): BadgeType {
  if (regime === 'trending') return 'cyan'
  if (regime === 'ranging')  return 'gold'
  return 'red'
}

function calcRR(s: any): string {
  const entry = Number(s.entry_price)
  const sl    = Number(s.stop_loss)
  const tp    = Number(s.take_profit)
  if (!entry || !sl || !tp) return '—'
  const risk   = Math.abs(entry - sl)
  const reward = Math.abs(tp - entry)
  if (risk === 0) return '—'
  return `1:${(reward / risk).toFixed(1)}R`
}

function fmtPrice(v: number | null | undefined, decimals = 5): string {
  if (v == null) return '—'
  return Number(v).toFixed(decimals)
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

const APPROVE_PLANS = new Set(['trader', 'pro', 'elite'])

export default function Signals() {
  const qc = useQueryClient()

  const { data: raw = [], isFetching: signalsFetching } = useQuery({
    queryKey: ['signals'],
    queryFn: () => api.get('/signals').then(r => Array.isArray(r.data) ? r.data : []),
    retry: false,
    refetchInterval: (q) => q.state.status === 'error' ? false : 15_000,
  })

  const { data: sub } = useQuery({
    queryKey: ['subscription'],
    queryFn: () => api.get('/billing/subscription').then(r => r.data).catch(() => null),
  })

  const update = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.patch(`/signals/${id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['signals'] }),
  })

  const signals   = raw as any[]
  const plan      = sub?.plan ?? 'community'
  const canApprove = APPROVE_PLANS.has(plan)
  const pending   = signals.filter((s: any) => s.status === 'pending').length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

      {/* ── Header bar ── */}
      <div className="flex items-center gap-[10px]" style={{ marginBottom: 4 }}>
        <span className="font-mono text-[11px]" style={{ color: 'var(--color-tx3)' }}>
          {signals.length} SIGNALS · {pending} PENDING
        </span>
        <button
          onClick={() => qc.invalidateQueries({ queryKey: ['signals'] })}
          disabled={signalsFetching}
          className="font-mono text-[10px] font-bold tracking-widest px-3 py-1.5 rounded-lg cursor-pointer transition-all ml-auto"
          style={{ background: 'var(--color-divider)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)', opacity: signalsFetching ? 0.5 : 1 }}
          onMouseEnter={e => { if (!signalsFetching) (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.09)' }}
          onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'var(--color-divider)' }}>
          {signalsFetching ? '↻ REFRESHING…' : '↻ REFRESH'}
        </button>
        {!canApprove && (
          <div className="font-mono text-[10px]"
            style={{ padding: '6px 12px', background: 'rgba(240,180,41,0.1)', border: '1px solid rgba(240,180,41,0.2)', borderRadius: 8, color: '#f0b429' }}>
            ⚡ Upgrade to TRADER to approve via Telegram
          </div>
        )}
      </div>

      {/* ── Signal cards grid ── */}
      {signals.length === 0 ? (
        <div className="font-mono text-xs text-center py-16" style={{ color: 'var(--color-tx3)' }}>No signals yet</div>
      ) : (
        <div className="rg2">
          {signals.map((s: any) => {
            const conf    = s.ai_probability != null ? Math.round(s.ai_probability * 100) : null
            const isPending = s.status === 'pending'
            const isRanging = s.regime === 'ranging'

            return (
              <div key={s.id} style={{
                background: 'var(--color-s2)',
                border: `1px solid ${isPending ? 'rgba(240,180,41,0.2)' : 'var(--color-card-border)'}`,
                borderRadius: 14, padding: 18, cursor: 'pointer', transition: 'all .15s',
              }}
                onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.borderColor = isPending ? 'rgba(240,180,41,0.4)' : 'var(--color-input-border)' }}
                onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.borderColor = isPending ? 'rgba(240,180,41,0.2)' : 'var(--color-card-border)' }}>

                {/* Header */}
                <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
                  <div className="flex items-center gap-2">
                    <span className="font-head font-bold" style={{ fontSize: 16 }}>{s.pair}</span>
                    <Badge type={s.direction === 'buy' ? 'cyan' : 'red'}>
                      {s.direction?.toUpperCase() ?? '—'}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Badge type={s.status === 'pending' ? 'gold' : s.status === 'approved' ? 'cyan' : 'gray'}>
                      {s.status?.toUpperCase() ?? '—'}
                    </Badge>
                    <span className="font-mono text-[10px]" style={{ color: 'var(--color-tx3)' }}>
                      {fmtTime(s.created_at)}
                    </span>
                  </div>
                </div>

                {/* Stats 3-col */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 12 }}>
                  {([
                    ['ENTRY', fmtPrice(s.entry_price), 'var(--color-tx)'],
                    ['SL',    fmtPrice(s.stop_loss, 4), '#ff3d5a'],
                    ['R:R',   calcRR(s),                '#00e5cc'],
                  ] as [string, string, string][]).map(([l, v, c]) => (
                    <div key={l} style={{ background: 'var(--color-s3)', borderRadius: 8, padding: '8px 10px' }}>
                      <div className="font-mono" style={{ fontSize: 9, color: 'var(--color-tx3)', marginBottom: 3 }}>{l}</div>
                      <div className="font-mono" style={{ fontSize: 12, color: c }}>{v}</div>
                    </div>
                  ))}
                </div>

                {/* AI Confidence */}
                {conf != null && (
                  <>
                    <div className="flex justify-between" style={{ marginBottom: 6 }}>
                      <span style={{ fontSize: 11, color: 'var(--color-tx3)' }}>AI Confidence</span>
                      <span className="font-mono" style={{ fontSize: 11, color: conf > 75 ? '#00e5cc' : '#f0b429' }}>
                        {conf}%
                      </span>
                    </div>
                    <ProgBar val={conf} max={100} color={conf > 75 ? '#00e5cc' : '#f0b429'} />
                  </>
                )}

                {/* Tags row */}
                <div className="flex flex-wrap items-center gap-2" style={{ marginTop: 10 }}>
                  {s.regime && (
                    <Badge type={regimeBadgeType(s.regime)}>
                      {s.regime.toUpperCase()}
                      {s.regime_adx > 0 ? ` · ADX ${s.regime_adx}` : ''}
                    </Badge>
                  )}
                  {isRanging && (
                    <span className="font-mono text-[9px]" style={{ color: '#f0b429' }}>⊘ BLOCKED</span>
                  )}
                  {s.reasoning && (
                    <span className="font-mono text-[9px] truncate" style={{ color: 'var(--color-tx3)', maxWidth: 160 }}>
                      {s.reasoning.slice(0, 48)}{s.reasoning.length > 48 ? '…' : ''}
                    </span>
                  )}
                </div>

                {/* Action buttons */}
                {isPending && (
                  <div className="flex gap-2" style={{ marginTop: 12 }}
                    onClick={e => e.stopPropagation()}>
                    <button
                      onClick={() => update.mutate({ id: s.id, status: 'approved' })}
                      disabled={update.isPending}
                      className="font-mono text-[10px] font-bold tracking-widest py-[7px] rounded-lg cursor-pointer transition-all flex-1 flex justify-center"
                      style={canApprove
                        ? { background: '#00e5cc', color: '#000', border: 'none' }
                        : { background: 'var(--color-divider)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}>
                      ✓ APPROVE
                    </button>
                    <button
                      onClick={() => update.mutate({ id: s.id, status: 'rejected' })}
                      disabled={update.isPending}
                      className="font-mono text-[10px] font-bold tracking-widest py-[7px] rounded-lg cursor-pointer transition-all flex-1 flex justify-center"
                      style={{ background: 'var(--color-divider)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}
                      onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.09)' }}
                      onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'var(--color-divider)' }}>
                      ✗ REJECT
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

    </div>
  )
}
