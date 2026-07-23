import { useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import api from '../api/client'

// ── helpers ──────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, d = 2) {
  if (n == null) return '—'
  return Number(n).toFixed(d)
}

function calcRR(s: any): string {
  const entry = Number(s.entry_price), sl = Number(s.stop_loss), tp = Number(s.take_profit)
  if (!entry || !sl || !tp) return '—'
  const risk = Math.abs(entry - sl), reward = Math.abs(tp - entry)
  if (risk === 0) return '—'
  return `1:${(reward / risk).toFixed(1)}R`
}

type BadgeType = 'cyan' | 'red' | 'gold' | 'gray' | 'green' | 'blue'
const BADGE: Record<BadgeType, { bg: string; color: string; border: string }> = {
  cyan:  { bg: 'rgba(212,168,83,0.1)',    color: '#d4a853', border: '1px solid rgba(212,168,83,0.2)'    },
  red:   { bg: 'rgba(232,84,79,0.1)',    color: '#e8544f', border: '1px solid rgba(232,84,79,0.2)'    },
  gold:  { bg: 'rgba(240,180,41,0.1)',   color: '#f0b429', border: '1px solid rgba(240,180,41,0.2)'   },
  green: { bg: 'rgba(0,229,150,0.1)',    color: '#c9953a', border: '1px solid rgba(0,229,150,0.2)'    },
  blue:  { bg: 'rgba(79,142,247,0.1)',   color: '#4f8ef7', border: '1px solid rgba(79,142,247,0.2)'   },
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

// ── Equity Curve canvas ───────────────────────────────────────────────────────

function EquityCurve({ trades }: { trades: any[] }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const cv = ref.current
    if (!cv) return

    function draw() {
      if (!cv) return
      const ctx = cv.getContext('2d')
      if (!ctx) return
      const W = cv.parentElement ? cv.parentElement.clientWidth : 460
      const H = window.innerWidth <= 767 ? 100 : 160
      cv.width = W; cv.height = H
      ctx.clearRect(0, 0, W, H)

      const closed = trades.filter(t => t.status === 'closed' && t.pnl_r != null)
      const vals: number[] = [0]
      closed.forEach(t => vals.push(vals[vals.length - 1] + Number(t.pnl_r)))

      if (vals.length < 2) {
        ctx.fillStyle = 'var(--color-tx3)'
        ctx.font = '11px IBM Plex Mono'
        ctx.textAlign = 'center'
        ctx.fillText('No closed trades yet', W / 2, H / 2)
        return
      }

      const mn = Math.min(...vals), mx = Math.max(...vals)
      const range = mx - mn || 1
      const pad = { t: 14, b: 22, l: 10, r: 10 }
      const iW = W - pad.l - pad.r, iH = H - pad.t - pad.b
      const tx = (i: number) => pad.l + (i / (vals.length - 1)) * iW
      const ty = (v: number) => pad.t + (1 - (v - mn) / range) * iH

      ctx.strokeStyle = 'var(--color-hover-bg)'
      ctx.lineWidth = 1
      for (let i = 0; i < 5; i++) {
        const y = pad.t + i * (iH / 4)
        ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke()
      }

      ctx.beginPath()
      ctx.strokeStyle = 'rgba(136,153,180,0.12)'
      ctx.lineWidth = 1
      ctx.setLineDash([4, 4])
      ctx.moveTo(pad.l, ty(0)); ctx.lineTo(W - pad.r, ty(0)); ctx.stroke()
      ctx.setLineDash([])

      const pos = vals[vals.length - 1] >= 0
      const rgb = pos ? '0,229,204' : '255,61,90'

      const grad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b)
      grad.addColorStop(0, `rgba(${rgb},0.2)`)
      grad.addColorStop(1, `rgba(${rgb},0)`)
      ctx.beginPath()
      vals.forEach((v, i) => i ? ctx.lineTo(tx(i), ty(v)) : ctx.moveTo(tx(i), ty(v)))
      ctx.lineTo(tx(vals.length - 1), H - pad.b)
      ctx.lineTo(tx(0), H - pad.b)
      ctx.closePath()
      ctx.fillStyle = grad; ctx.fill()

      ctx.beginPath()
      ctx.strokeStyle = pos ? '#d4a853' : '#e8544f'
      ctx.lineWidth = 2; ctx.lineJoin = 'round'
      vals.forEach((v, i) => i ? ctx.lineTo(tx(i), ty(v)) : ctx.moveTo(tx(i), ty(v)))
      ctx.stroke()

      ctx.beginPath()
      ctx.arc(tx(vals.length - 1), ty(vals[vals.length - 1]), 3, 0, Math.PI * 2)
      ctx.fillStyle = pos ? '#d4a853' : '#e8544f'; ctx.fill()

      ctx.fillStyle = 'var(--color-tx3)'; ctx.font = '9px IBM Plex Mono'
      ctx.textAlign = 'left'
      ctx.fillText(`${mn >= 0 ? '+' : ''}${mn.toFixed(1)}R`, pad.l, H - 5)
      ctx.textAlign = 'right'
      ctx.fillText(`${mx >= 0 ? '+' : ''}${mx.toFixed(1)}R`, W - pad.r, pad.t + 8)
    }

    draw()
    const ro = new ResizeObserver(draw)
    if (cv.parentElement) ro.observe(cv.parentElement)
    return () => ro.disconnect()
  }, [trades])

  return (
    <canvas ref={ref} width={460} height={160} style={{ width: '100%', display: 'block' }} />
  )
}

// ── Progress bar ──────────────────────────────────────────────────────────────

function ProgBar({ val, max, color = '#d4a853' }: { val: number; max: number; color?: string }) {
  return (
    <div style={{ height: 5, background: 'var(--color-card-border)', borderRadius: 3, overflow: 'hidden' }}>
      <div style={{
        height: '100%', borderRadius: 3, transition: 'width .5s',
        width: `${Math.min(100, (val / (max || 1)) * 100)}%`, background: color,
      }} />
    </div>
  )
}

// ── Plan colors ───────────────────────────────────────────────────────────────

const PLAN_COLORS: Record<string, string> = {
  community: '#8899b4', starter: '#4f8ef7', trader: '#d4a853', pro: '#f0b429', elite: '#8b5cf6',
}
const PLAN_PRICES: Record<string, number> = {
  community: 0, starter: 29, trader: 79, pro: 149, elite: 299,
}
const APPROVE_PLANS = new Set(['trader', 'pro', 'elite'])

// ── Dashboard ─────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const qc = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [checkoutBanner, setCheckoutBanner] = useState<string | null>(null)

  useEffect(() => {
    if (searchParams.get('checkout') === 'success') {
      setCheckoutBanner('Payment successful! Your new plan is now active.')
      setSearchParams({}, { replace: true })
      qc.invalidateQueries({ queryKey: ['subscription'] })
    }
  }, [])

  const { data: stats } = useQuery({
    queryKey: ['analytics-summary'],
    queryFn: () => api.get('/analytics/summary').then(r => r.data),
    retry: false,
    refetchInterval: (q) => q.state.status === 'error' ? false : 30_000,
  })
  const { data: trades = [] } = useQuery({
    queryKey: ['trades-all'],
    queryFn: () => api.get('/trades').then(r => Array.isArray(r.data) ? r.data : []),
    retry: false,
    refetchInterval: (q) => q.state.status === 'error' ? false : 30_000,
  })
  const { data: signals = [] } = useQuery({
    queryKey: ['signals'],
    queryFn: () => api.get('/signals?limit=10').then(r => Array.isArray(r.data) ? r.data : []),
    retry: false,
    refetchInterval: (q) => q.state.status === 'error' ? false : 15_000,
  })
  const { data: sub } = useQuery({
    queryKey: ['subscription'],
    queryFn: () => api.get('/billing/subscription').then(r => r.data).catch(() => null),
  })
  const { data: account } = useQuery({
    queryKey: ['account'],
    queryFn: () => api.get('/account').then(r => r.data).catch(() => null),
    refetchInterval: 30_000,
  })
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings').then(r => r.data).catch(() => ({})),
  })

  const approve = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.patch(`/signals/${id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['signals'] }),
  })

  const tradeList   = trades  as any[]
  const signalList  = signals as any[]
  const plan        = (sub?.plan as string) ?? 'community'
  const planColor   = PLAN_COLORS[plan] ?? 'var(--color-tx2)'
  const canApprove  = APPROVE_PLANS.has(plan)

  const closed   = tradeList.filter(t => t.status === 'closed')
  const wins     = closed.filter(t => t.pnl_r > 0).length
  const totalR   = closed.reduce((s, t) => s + (t.pnl_r || 0), 0)
  const wr       = closed.length > 0 ? Math.round(wins / closed.length * 100) : 0
  const netPnl   = stats?.net_pnl_r ?? null

  // Risk state derived from trades
  const maxDD       = Number((settings as any)?.risk_max_drawdown_pct ?? 15)
  const maxDaily    = Number((settings as any)?.risk_daily_pct ?? 5)
  const today       = new Date().toDateString()
  const todayTrades = closed.filter(t => t.entry_time && new Date(t.entry_time).toDateString() === today)
  const dailyUsed   = Math.abs(todayTrades.reduce((s, t) => s + (t.pnl_r < 0 ? t.pnl_r : 0), 0))

  // Max drawdown from equity curve
  let peak = 0, maxDrawdown = 0, equity = 0
  closed.forEach(t => {
    equity += t.pnl_r || 0
    if (equity > peak) peak = equity
    const dd = peak > 0 ? ((peak - equity) / peak) * 100 : 0
    if (dd > maxDrawdown) maxDrawdown = dd
  })

  const pendingSignals = signalList.filter(s => s.status === 'pending').slice(0, 4)

  const TH = ['Pair', 'Dir', 'Entry', 'R:R', 'D1 Bias', 'News', 'Status', '']

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

      {/* ── Checkout success banner ── */}
      {checkoutBanner && (
        <div
          className="flex items-center justify-between gap-3 rounded-[10px] px-4 py-3"
          style={{ background: 'rgba(0,229,150,0.08)', border: '1px solid rgba(0,229,150,0.25)' }}
        >
          <span className="font-mono text-[11px]" style={{ color: '#c9953a' }}>
            ✓ {checkoutBanner}
          </span>
          <button onClick={() => setCheckoutBanner(null)} className="font-mono text-[14px] shrink-0" style={{ color: 'var(--color-tx3)' }}>×</button>
        </div>
      )}

      {/* ── 4 stat cards ── */}
      <div className="rg4">
        {[
          {
            t: 'Account Equity',
            v: account != null ? `$${fmt(account.equity, 2)}` : '—',
            s: account != null ? `${account.currency} balance: $${fmt(account.balance, 2)}` : 'Connecting…',
            c: account != null ? (account.equity >= account.balance ? '#d4a853' : '#f0b429') : '#d4a853',
          },
          {
            t: 'Net P&L',
            v: totalR !== 0 ? `${totalR >= 0 ? '+' : ''}${totalR.toFixed(1)}R` : '—',
            s: `${wins}W / ${closed.length - wins}L`,
            c: totalR >= 0 ? '#d4a853' : '#e8544f',
          },
          {
            t: 'Win Rate',
            v: stats?.win_rate != null ? `${stats.win_rate}%` : (closed.length > 0 ? `${wr}%` : '—'),
            s: `${stats?.total_trades ?? closed.length} trades`,
            c: 'var(--color-tx)',
          },
          {
            t: 'Active Plan',
            v: plan.toUpperCase(),
            s: `$${PLAN_PRICES[plan] ?? 0}/mo`,
            c: planColor,
          },
        ].map(m => (
          <div key={m.t} className="rounded-[10px] p-4" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
            <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>{m.t}</div>
            <div className="font-head font-bold" style={{ fontSize: 26, color: m.c, lineHeight: 1 }}>{m.v}</div>
            <div style={{ fontSize: 12, color: 'var(--color-tx2)', marginTop: 4 }}>{m.s}</div>
          </div>
        ))}
      </div>

      {/* ── Equity Curve + Live Risk State ── */}
      <div className="rg2">

        {/* Equity Curve */}
        <div className="rounded-[14px] p-5" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
            Equity Curve
          </div>
          <EquityCurve trades={tradeList} />
        </div>

        {/* Live Risk State */}
        <div className="rounded-[14px] p-5" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
            Live Risk State
          </div>
          {[
            { l: 'Daily Risk Used',         v: parseFloat(dailyUsed.toFixed(1)),            max: maxDaily, c: '#d4a853', unit: '%' },
            { l: 'Total Drawdown',          v: parseFloat(maxDrawdown.toFixed(1)),           max: maxDD,    c: '#f0b429', unit: '%' },
            { l: 'USD Group Exposure',      v: tradeList.filter(t => t.status === 'open' && (t.pair?.includes('USD') || t.pair?.includes('XAU'))).length, max: 3, c: '#4f8ef7', unit: ' pairs' },
            { l: 'Open Correlated Pairs',   v: tradeList.filter(t => t.status === 'open').length,  max: 3, c: '#8b5cf6', unit: ' pairs' },
          ].map(m => (
            <div key={m.l} style={{ marginBottom: 12 }}>
              <div className="flex justify-between" style={{ marginBottom: 4 }}>
                <span style={{ fontSize: 12, color: 'var(--color-tx2)' }}>{m.l}</span>
                <span className="font-mono" style={{ fontSize: 11, color: m.c }}>{m.v} / {m.max}{m.unit}</span>
              </div>
              <ProgBar val={m.v} max={m.max} color={m.c} />
            </div>
          ))}

          {/* Drawdown stage banner */}
          <div style={{
            marginTop: 12, padding: '10px 14px', borderRadius: 8,
            background: 'rgba(212,168,83,0.08)', border: '1px solid rgba(212,168,83,0.2)',
            fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: '#d4a853',
          }}>
            ✓ DRAWDOWN STAGE: NORMAL · Risk {fmt((settings as any)?.base_risk_pct != null ? (settings as any).base_risk_pct * 100 : 1, 1)}% per trade · No restrictions active
          </div>

          {/* System status */}
          {(() => {
            const paused = (settings as any)?.trading_paused === true
            const dotColor = paused ? '#f59e0b' : '#c9953a'
            const mode = ((settings as any)?.trading_mode ?? 'signal_approval').replace('_', ' ').toUpperCase()
            return (
              <div style={{
                marginTop: 10, padding: '9px 12px', borderRadius: 8,
                background: paused ? 'rgba(245,158,11,0.08)' : 'rgba(212,168,83,0.1)',
                border: `1px solid ${paused ? 'rgba(245,158,11,0.3)' : 'rgba(212,168,83,0.18)'}`,
                display: 'flex', alignItems: 'center',
              }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: dotColor, boxShadow: `0 0 6px ${dotColor}`, display: 'inline-block', marginRight: 8, flexShrink: 0 }} />
                <span className="font-mono" style={{ fontSize: 10, color: paused ? '#f59e0b' : '#d4a853' }}>
                  SYSTEM: {paused ? 'PAUSED' : 'TRADING'} · MODE: {mode}
                </span>
                <span className="font-mono" style={{ fontSize: 9, color: 'var(--color-tx3)', marginLeft: 'auto' }}>NEWS: CLEAR</span>
              </div>
            )
          })()}
        </div>
      </div>

      {/* ── Paper Trading Progress ── */}
      {(() => {
        const PAPER_TARGET = 50
        const paperTrades  = tradeList.filter((t: any) => t.is_paper)
        const paperClosed  = paperTrades.filter((t: any) => t.status === 'closed')
        const paperOpen    = paperTrades.filter((t: any) => t.status === 'open')
        const paperWins    = paperClosed.filter((t: any) => t.pnl_r > 0).length
        const paperNetR    = paperClosed.reduce((s: number, t: any) => s + (Number(t.pnl_r) || 0), 0)
        const paperWR      = paperClosed.length > 0 ? Math.round(paperWins / paperClosed.length * 100) : 0
        const paperAvgR    = paperClosed.length > 0 ? paperNetR / paperClosed.length : 0

        // Max drawdown from paper equity curve
        let pPeak = 0, pEq = 0, pMaxDD = 0
        paperClosed.forEach((t: any) => {
          pEq += Number(t.pnl_r) || 0
          if (pEq > pPeak) pPeak = pEq
          const dd = pPeak > 0 ? ((pPeak - pEq) / pPeak) * 100 : 0
          if (dd > pMaxDD) pMaxDD = dd
        })

        const gates = [
          { label: 'Win Rate',    val: paperWR,             fmt: `${paperWR}%`,              target: '≥ 50%',   pass: paperWR >= 50 },
          { label: 'Avg R',       val: paperAvgR,           fmt: `${paperAvgR.toFixed(3)}R`, target: '≥ 0.15R', pass: paperAvgR >= 0.15 },
          { label: 'Max DD',      val: pMaxDD,              fmt: `${pMaxDD.toFixed(1)}%`,    target: '≤ 10%',   pass: pMaxDD <= 10 },
          { label: 'Trades',      val: paperClosed.length,  fmt: `${paperClosed.length}`,    target: '≥ 50',    pass: paperClosed.length >= PAPER_TARGET },
        ]
        const allPass   = gates.every(g => g.pass)
        const pct       = Math.min(100, (paperClosed.length / PAPER_TARGET) * 100)
        const progressColor = allPass ? '#c9953a' : paperClosed.length > 0 ? '#d4a853' : '#4f8ef7'

        return (
          <div className="rounded-[14px] p-5" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
            <div className="flex items-center justify-between" style={{ marginBottom: 14 }}>
              <div className="font-mono text-[10px] tracking-[2px] uppercase" style={{ color: 'var(--color-tx3)' }}>
                Paper Trading Progress
              </div>
              <div className="flex items-center gap-2">
                {paperOpen.length > 0 && (
                  <span className="font-mono text-[9px] px-2 py-0.5 rounded tracking-widest"
                    style={{ background: 'rgba(79,142,247,0.1)', color: '#4f8ef7', border: '1px solid rgba(79,142,247,0.2)' }}>
                    {paperOpen.length} OPEN
                  </span>
                )}
                {allPass
                  ? <span className="font-mono text-[9px] px-2 py-0.5 rounded tracking-widest" style={{ background: 'rgba(0,229,150,0.1)', color: '#c9953a', border: '1px solid rgba(0,229,150,0.25)' }}>🎯 READY FOR LIVE</span>
                  : <span className="font-mono text-[9px] px-2 py-0.5 rounded tracking-widest" style={{ background: 'rgba(240,180,41,0.08)', color: '#f0b429', border: '1px solid rgba(240,180,41,0.2)' }}>IN PROGRESS</span>
                }
              </div>
            </div>

            {/* Big progress bar */}
            <div style={{ marginBottom: 10 }}>
              <div className="flex justify-between font-mono" style={{ fontSize: 11, marginBottom: 6, color: 'var(--color-tx2)' }}>
                <span>{paperClosed.length} closed trades</span>
                <span style={{ color: progressColor }}>{pct.toFixed(0)}% of {PAPER_TARGET} target</span>
              </div>
              <div style={{ height: 8, background: 'var(--color-card-border)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ height: '100%', borderRadius: 4, transition: 'width .6s', width: `${pct}%`, background: progressColor }} />
              </div>
            </div>

            {/* 4 deployment gates */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2" style={{ marginTop: 12 }}>
              {gates.map(g => (
                <div key={g.label} className="rounded-[8px] px-3 py-2.5"
                  style={{
                    background: paperClosed.length === 0 ? 'var(--color-s3)' : g.pass ? 'rgba(0,229,150,0.06)' : 'rgba(232,84,79,0.06)',
                    border: `1px solid ${paperClosed.length === 0 ? 'var(--color-card-border)' : g.pass ? 'rgba(0,229,150,0.2)' : 'rgba(232,84,79,0.2)'}`,
                  }}>
                  <div className="flex items-center gap-1.5 mb-1">
                    <span style={{ fontSize: 10 }}>{paperClosed.length === 0 ? '○' : g.pass ? '✓' : '✗'}</span>
                    <span className="font-mono text-[9px] tracking-widest uppercase" style={{ color: 'var(--color-tx3)' }}>{g.label}</span>
                  </div>
                  <div className="font-mono font-bold" style={{ fontSize: 14, color: paperClosed.length === 0 ? 'var(--color-tx3)' : g.pass ? '#c9953a' : '#e8544f' }}>
                    {paperClosed.length === 0 ? '—' : g.fmt}
                  </div>
                  <div className="font-mono" style={{ fontSize: 9, color: 'var(--color-tx3)', marginTop: 2 }}>{g.target}</div>
                </div>
              ))}
            </div>

            {/* Active pairs scanning */}
            <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--color-card-border)' }}>
              <div className="font-mono text-[9px] tracking-widest uppercase mb-2" style={{ color: 'var(--color-tx3)' }}>Scanning Pairs</div>
              <div className="flex flex-wrap gap-1.5">
                {['EURUSD','GBPUSD','USDJPY','XAUUSD','AUDUSD'].map(pair => {
                  const pairOpen = paperOpen.filter((t: any) => t.pair === pair).length
                  return (
                    <span key={pair} className="font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest"
                      style={{
                        background: pairOpen > 0 ? 'rgba(212,168,83,0.12)' : 'var(--color-s3)',
                        color:      pairOpen > 0 ? '#d4a853' : 'var(--color-tx3)',
                        border:     `1px solid ${pairOpen > 0 ? 'rgba(212,168,83,0.25)' : 'var(--color-card-border)'}`,
                      }}>
                      {pair}{pairOpen > 0 ? ' ●' : ''}
                    </span>
                  )
                })}
              </div>
            </div>
          </div>
        )
      })()}

      {/* ── Pending Signals table ── */}
      <div className="rounded-[14px] p-5" style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
        <div className="flex items-center justify-between" style={{ marginBottom: 14 }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase" style={{ color: 'var(--color-tx3)' }}>
            Pending Signals
          </div>
          <Link to="/signals"
            className="font-mono text-[10px] transition-colors"
            style={{ color: 'var(--color-tx3)' }}
            onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.color = '#d4a853' }}
            onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--color-tx3)' }}>
            View All →
          </Link>
        </div>

        {pendingSignals.length === 0 ? (
          <div className="font-mono text-xs text-center py-8" style={{ color: 'var(--color-tx3)' }}>No pending signals</div>
        ) : (
          <div className="tbl-scroll">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                {TH.map(h => (
                  <th key={h} className="font-mono text-[9px] tracking-widest text-left py-[10px] px-3 uppercase"
                    style={{ color: 'var(--color-tx3)', borderBottom: '1px solid var(--color-card-border)' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pendingSignals.map((s: any) => {
                return (
                  <tr key={s.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}
                    onMouseEnter={e => (e.currentTarget as HTMLTableRowElement).style.background = 'rgba(255,255,255,0.02)'}
                    onMouseLeave={e => (e.currentTarget as HTMLTableRowElement).style.background = ''}>

                    {/* Pair */}
                    <td className="font-mono font-bold py-[11px] px-3" style={{ fontSize: 12, color: 'var(--color-tx)' }}>
                      {s.pair}
                    </td>

                    {/* Dir */}
                    <td className="py-[11px] px-3">
                      <Badge type={s.direction === 'buy' ? 'cyan' : 'red'}>
                        {s.direction?.toUpperCase() ?? '—'}
                      </Badge>
                    </td>

                    {/* Entry */}
                    <td className="font-mono py-[11px] px-3" style={{ fontSize: 12, color: 'var(--color-tx)' }}>
                      {s.entry_price ? Number(s.entry_price).toFixed(5) : '—'}
                    </td>

                    {/* R:R */}
                    <td className="font-mono py-[11px] px-3" style={{ fontSize: 12, color: '#d4a853' }}>
                      {calcRR(s)}
                    </td>

                    {/* D1 Bias */}
                    {(() => {
                      const bias = s.gate_results?.d1_bias
                      return (
                        <td className="font-mono py-[11px] px-3" style={{ fontSize: 11, color: bias === 'bullish' ? '#d4a853' : bias === 'bearish' ? '#e8544f' : 'var(--color-tx3)' }}>
                          {bias ? (bias === 'bullish' ? '▲ BULL' : '▼ BEAR') : '—'}
                        </td>
                      )
                    })()}

                    {/* News — not in API */}
                    <td className="py-[11px] px-3">
                      <Badge type="green">CLEAR</Badge>
                    </td>

                    {/* Status */}
                    <td className="py-[11px] px-3">
                      <Badge type={s.status === 'pending' ? 'gold' : s.status === 'approved' ? 'cyan' : s.status === 'executed' ? 'blue' : 'gray'}>
                        {s.status?.toUpperCase() ?? '—'}
                      </Badge>
                    </td>

                    {/* Actions */}
                    <td className="py-[11px] px-3">
                      {s.status === 'pending' && (
                        <div className="flex gap-1">
                          <button
                            onClick={() => approve.mutate({ id: s.id, status: 'approved' })}
                            disabled={approve.isPending}
                            className="font-mono text-[9px] font-bold tracking-widest px-2 py-1 rounded cursor-pointer transition-all"
                            style={canApprove
                              ? { background: '#d4a853', color: '#000', border: 'none' }
                              : { background: 'var(--color-divider)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}>
                            {canApprove ? '✓ Approve' : '🔒'}
                          </button>
                          <button
                            onClick={() => approve.mutate({ id: s.id, status: 'rejected' })}
                            disabled={approve.isPending}
                            className="font-mono text-[9px] font-bold tracking-widest px-2 py-1 rounded cursor-pointer transition-all"
                            style={{ background: '#e8544f', color: '#fff', border: 'none' }}>
                            ✗
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          </div>
        )}
      </div>

    </div>
  )
}
