import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

type PlanId = 'community' | 'starter' | 'trader' | 'pro' | 'elite'
type Tab = 'plans' | 'invoices' | 'usage'

interface PlanDef {
  plan_id: string
  name: string
  price: number
  color: string
  popular?: boolean
  features: Record<string, boolean | number>
}

// Fallback used while loading from API
const FALLBACK_PLANS: PlanDef[] = [
  { plan_id: 'community', name: 'Community', price: 0,   color: '#8899b4', features: { pairs: 0, mt5_accounts: 0, dashboard: false, signals_web: false, signals_tg_drops: true,  tg_bot_approve: false, tg_bot_settings: false, auto_execute: false, copy_trade: false, api_access: false, mobile_app: false, priority_support: false } },
  { plan_id: 'starter',   name: 'Starter',   price: 29,  color: '#4f8ef7', features: { pairs: 2, mt5_accounts: 1, dashboard: true,  signals_web: true,  signals_tg_drops: true,  tg_bot_approve: false, tg_bot_settings: false, auto_execute: false, copy_trade: false, api_access: false, mobile_app: false, priority_support: false } },
  { plan_id: 'trader',    name: 'Trader',    price: 79,  color: '#00e5cc', popular: true, features: { pairs: 5, mt5_accounts: 1, dashboard: true, signals_web: true, signals_tg_drops: true, tg_bot_approve: true, tg_bot_settings: false, auto_execute: false, copy_trade: true, api_access: false, mobile_app: true, priority_support: false } },
  { plan_id: 'pro',       name: 'Pro',       price: 149, color: '#f0b429', features: { pairs: 5, mt5_accounts: 2, dashboard: true, signals_web: true, signals_tg_drops: true, tg_bot_approve: true, tg_bot_settings: true,  auto_execute: true,  copy_trade: true, api_access: false, mobile_app: true, priority_support: true } },
  { plan_id: 'elite',     name: 'Elite',     price: 299, color: '#8b5cf6', features: { pairs: 5, mt5_accounts: 5, dashboard: true, signals_web: true, signals_tg_drops: true, tg_bot_approve: true, tg_bot_settings: true,  auto_execute: true,  copy_trade: true, api_access: true,  mobile_app: true, priority_support: true } },
]

const FEATURE_LIST = [
  { key: 'dashboard',        label: 'Web Dashboard Access' },
  { key: 'signals_web',      label: 'Signal Viewing (Web)' },
  { key: 'signals_tg_drops', label: 'Telegram Signal Drops' },
  { key: 'tg_bot_approve',   label: 'Telegram: Approve/Reject Trades' },
  { key: 'tg_bot_settings',  label: 'Telegram: Change Settings & Params' },
  { key: 'auto_execute',     label: 'Auto-Execute Mode' },
  { key: 'copy_trade',       label: 'Copy Trade (2nd Account)' },
  { key: 'mobile_app',       label: 'Mobile App Access' },
  { key: 'api_access',       label: 'API Access' },
  { key: 'priority_support', label: 'Priority Support' },
]

function PlanBadge({ plan, plans }: { plan: string; plans?: PlanDef[] }) {
  const p = (plans ?? FALLBACK_PLANS).find(x => x.plan_id === plan)
  if (!p) return (
    <span className="inline-flex items-center font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest whitespace-nowrap"
      style={{ background: 'var(--color-hover-bg)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}>
      {plan.toUpperCase()}
    </span>
  )
  return (
    <span
      className="inline-flex items-center font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest whitespace-nowrap"
      style={{ background: `${p.color}22`, color: p.color, border: `1px solid ${p.color}44` }}
    >
      {plan.toUpperCase()}
    </span>
  )
}

function ProgBar({ val, max, color = '#00e5cc' }: { val: number; max: number; color?: string }) {
  return (
    <div className="h-[5px] rounded-full overflow-hidden" style={{ background: 'var(--color-card-border)' }}>
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${Math.min(100, (val / (max || 1)) * 100)}%`, background: color }}
      />
    </div>
  )
}

export default function Billing() {
  const [tab, setTab] = useState<Tab>('plans')

  const { data: sub } = useQuery({
    queryKey: ['subscription'],
    queryFn: () => api.get('/billing/subscription').then(r => r.data).catch(() => null),
  })

  const { data: usageData } = useQuery({
    queryKey: ['billing-usage'],
    queryFn: () => api.get('/billing/usage').then(r => r.data).catch(() => null),
    retry: false,
  })

  const { data: invoicesData } = useQuery({
    queryKey: ['billing-invoices'],
    queryFn: () => api.get('/billing/invoices').then(r => r.data).catch(() => []),
    retry: false,
  })

  const { data: plansData } = useQuery({
    queryKey: ['billing-plans'],
    queryFn: () => api.get('/billing/plans').then(r => r.data as PlanDef[]).catch(() => FALLBACK_PLANS),
    retry: false,
  })

  const plans = plansData ?? FALLBACK_PLANS
  const plan: PlanId = (sub?.plan as PlanId) ?? 'community'
  const isAdmin = plan === 'elite'
  const p = plans.find(x => x.plan_id === plan) ?? plans[0]

  const upgrade = async (planId: string) => {
    try {
      const res = await api.post('/billing/create-checkout-session', { plan: planId })
      const url = res.data.checkout_url || res.data.url
      if (url) window.location.href = url
    } catch { /* handled */ }
  }

  const openPortal = async () => {
    try {
      const res = await api.post('/billing/customer-portal')
      const url = res.data.portal_url || res.data.url
      if (url) window.location.href = url
    } catch { /* handled */ }
  }

  const TABS: Tab[] = ['plans', 'invoices', 'usage']

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Tab bar */}
      <div className="flex gap-0.5 mb-0 bg-s3 p-1 rounded-[10px]">
        {TABS.map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className="flex-1 text-center py-[7px] font-mono text-[10px] tracking-widest cursor-pointer rounded-[7px] transition-all border border-transparent"
            style={tab === t
              ? { background: 'var(--color-s2)', color: '#00e5cc', border: '1px solid var(--color-card-border)' }
              : { color: 'var(--color-tx3)' }
            }
          >
            {t.toUpperCase()}
          </button>
        ))}
      </div>

      {/* PLANS TAB */}
      {tab === 'plans' && (
        <div>
          {/* Current plan banner */}
          <div
            className="flex items-center justify-between rounded-[14px] p-5 mb-4"
            style={{ background: 'var(--color-s2)', border: '1px solid var(--color-input-border)' }}
          >
            <div>
              <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[6px]" style={{ color: 'var(--color-tx3)' }}>
                Current Plan
              </div>
              <div className="flex items-center gap-[10px]">
                <PlanBadge plan={plan} plans={plans} />
                <span className="font-head text-[20px] font-bold" style={{ color: p?.color }}>
                  ${p?.price ?? 0}/mo
                </span>
                <span className="font-mono text-[10px]" style={{ color: 'var(--color-tx3)' }}>
                  {sub?.current_period_end
                    ? `Next billing: ${new Date(sub.current_period_end * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`
                    : ''}
                </span>
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => {}}
                className="font-mono text-[11px] font-bold tracking-widest px-[18px] py-[9px] rounded-lg cursor-pointer transition-all flex items-center gap-1.5"
                style={{ background: '#00e5cc', color: '#000' }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = '#00ffea' }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = '#00e5cc' }}
              >
                Upgrade Plan →
              </button>
            </div>
          </div>

          {/* Plan grid */}
          <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fit,minmax(140px,1fr))`, gap: 10 }}>
            {plans.map((pl, pidIdx) => {
              const isCurrent   = pl.plan_id === plan
              const isCommunity = pl.plan_id === 'community'
              const currentIdx  = plans.findIndex(x => x.plan_id === plan)

              return (
                <div
                  key={pl.plan_id}
                  style={{
                    background: 'var(--color-s2)',
                    border: `1px solid ${isCurrent ? '#00e5cc' : 'var(--color-card-border)'}`,
                    borderRadius: 14,
                    padding: 18,
                    position: 'relative',
                    overflow: 'hidden',
                  }}
                >
                  {/* POPULAR ribbon */}
                  {pl.popular && (
                    <div style={{
                      position: 'absolute', top: 14, right: -20,
                      background: '#f0b429', color: '#000',
                      fontFamily: '"IBM Plex Mono",monospace', fontSize: 8, fontWeight: 700,
                      padding: '3px 28px', letterSpacing: 2, transform: 'rotate(45deg)',
                    }}>
                      MOST POPULAR
                    </div>
                  )}

                  {/* ACTIVE badge */}
                  {isCurrent && (
                    <div style={{
                      position: 'absolute', top: 10, right: 10,
                      background: '#00e5cc', color: '#000',
                      fontFamily: '"IBM Plex Mono",monospace', fontSize: 8, fontWeight: 700,
                      padding: '2px 6px', borderRadius: 3,
                    }}>
                      ACTIVE
                    </div>
                  )}

                  <PlanBadge plan={pl.plan_id} plans={plans} />

                  <div style={{
                    fontFamily: 'Syne, sans-serif', fontSize: 22, fontWeight: 800,
                    margin: '10px 0 4px', color: pl.color,
                  }}>
                    {isCommunity ? 'FREE' : `$${pl.price}`}
                  </div>
                  <p style={{ fontSize: 10, color: 'var(--color-tx3)', marginBottom: 12 }}>per month</p>

                  {/* Feature checklist */}
                  {FEATURE_LIST.map(f => {
                    const has = isCurrent && isAdmin ? true : !!pl.features[f.key]
                    return (
                      <div key={f.key} style={{
                        display: 'flex', gap: 6, padding: '4px 0', fontSize: 11,
                        color: has ? 'var(--color-tx2)' : 'var(--color-tx3)',
                      }}>
                        <span style={{ color: has ? '#00e5cc' : 'var(--color-tx3)' }}>{has ? '✓' : '✗'}</span>
                        {f.label}
                      </div>
                    )
                  })}

                  {!isCurrent && !isAdmin && (
                    <button
                      onClick={() => upgrade(pl.plan_id)}
                      className="font-mono text-[10px] font-bold tracking-widest px-3 py-1.5 rounded-lg cursor-pointer transition-all"
                      style={{
                        width: '100%', marginTop: 14, justifyContent: 'center', display: 'flex',
                        background: 'var(--color-divider)', color: 'var(--color-tx2)',
                        border: '1px solid var(--color-card-border)',
                      }}
                      onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.09)' }}
                      onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'var(--color-divider)' }}
                    >
                      {pidIdx > currentIdx ? 'Upgrade →' : 'Downgrade'}
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* INVOICES TAB */}
      {tab === 'invoices' && (
        <div className="bg-s2 rounded-[14px] p-5" style={{ border: '1px solid var(--color-card-border)' }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
            Invoice History
          </div>
          <table className="w-full border-collapse">
            <thead>
              <tr>
                {['Date', 'Plan', 'Amount', 'Status', ''].map(h => (
                  <th
                    key={h}
                    className="font-mono text-[9px] tracking-widest text-left pb-[10px] px-3 uppercase"
                    style={{ color: 'var(--color-tx3)', borderBottom: '1px solid var(--color-card-border)' }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(invoicesData as any[] ?? []).length === 0 ? (
                <tr>
                  <td colSpan={5} className="font-mono text-xs py-8 px-3 text-center" style={{ color: 'var(--color-tx3)' }}>
                    No invoices yet
                  </td>
                </tr>
              ) : (invoicesData as any[]).map((inv, i) => (
                <tr key={inv.id ?? i} className="group">
                  <td className="font-mono text-xs py-[11px] px-3 text-tx2" style={{ borderBottom: '1px solid var(--color-divider)' }}>
                    {inv.date}
                  </td>
                  <td className="py-[11px] px-3" style={{ borderBottom: '1px solid var(--color-divider)' }}>
                    <PlanBadge plan={inv.plan ?? '—'} plans={plans} />
                  </td>
                  <td className="font-mono text-xs py-[11px] px-3 text-cy" style={{ borderBottom: '1px solid var(--color-divider)' }}>
                    {inv.amount}
                  </td>
                  <td className="py-[11px] px-3" style={{ borderBottom: '1px solid var(--color-divider)' }}>
                    <span
                      className="inline-flex items-center font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest"
                      style={inv.status === 'PAID'
                        ? { background: 'rgba(0,229,150,0.1)', color: '#00e596', border: '1px solid rgba(0,229,150,0.2)' }
                        : { background: 'rgba(240,180,41,0.1)', color: '#f0b429', border: '1px solid rgba(240,180,41,0.2)' }}
                    >
                      {inv.status}
                    </span>
                  </td>
                  <td className="py-[11px] px-3" style={{ borderBottom: '1px solid var(--color-divider)' }}>
                    {inv.pdf
                      ? <a href={inv.pdf} target="_blank" rel="noreferrer"
                          className="font-mono text-[10px] font-bold tracking-widest px-3 py-1.5 rounded-lg cursor-pointer transition-all inline-block"
                          style={{ background: 'var(--color-divider)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}>
                          PDF
                        </a>
                      : <span className="font-mono text-[10px]" style={{ color: 'var(--color-tx3)' }}>—</span>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* USAGE TAB */}
      {tab === 'usage' && (
        <div className="rg2">
          {[
            { l: 'Signals Generated',   v: usageData?.signals_generated ?? 0,  max: isAdmin ? 99999 : 100,   unit: 'this month' },
            { l: 'Trades Executed',     v: usageData?.trades_executed   ?? 0,  max: isAdmin ? 99999 : 30,    unit: 'this month' },
            { l: 'API Calls',           v: (isAdmin || p?.features.api_access) ? (usageData?.api_calls ?? 0) : 0,  max: isAdmin ? 99999 : 10000, unit: 'this month' },
            { l: 'MT5 Accounts Bound',  v: usageData?.mt5_accounts ?? 0,       max: isAdmin ? 99 : (Number(p?.features.mt5_accounts) || 1), unit: 'of plan limit' },
          ].map(m => (
            <div
              key={m.l}
              className="rounded-[10px] p-4"
              style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}
            >
              <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
                {m.l}
              </div>
              <div className="flex justify-between mb-2">
                <span className="font-head text-[22px] font-bold text-cy">{m.v}</span>
                <span className="font-mono text-[11px]" style={{ color: 'var(--color-tx3)' }}>{m.unit}</span>
              </div>
              <ProgBar val={m.v} max={m.max} />
            </div>
          ))}
        </div>
      )}

    </div>
  )
}
