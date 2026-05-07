import { useState, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import api from '../api/client'

type Tab = 'trading' | 'risk' | 'pairs' | 'mt5' | 'telegram' | 'notifications'
type PlanId = 'community' | 'starter' | 'trader' | 'pro' | 'elite'

const PLAN_ORDER: PlanId[] = ['community', 'starter', 'trader', 'pro', 'elite']

const PLAN_FEATURES: Record<PlanId, Record<string, boolean | number>> = {
  community: { pairs: 0, auto_execute: false, copy_trade: false, tg_bot_approve: false, tg_bot_settings: false, mobile_app: false, mt5_accounts: 0 },
  starter:   { pairs: 2, auto_execute: false, copy_trade: false, tg_bot_approve: false, tg_bot_settings: false, mobile_app: false, mt5_accounts: 1 },
  trader:    { pairs: 5, auto_execute: false, copy_trade: true,  tg_bot_approve: true,  tg_bot_settings: false, mobile_app: true,  mt5_accounts: 1 },
  pro:       { pairs: 5, auto_execute: true,  copy_trade: true,  tg_bot_approve: true,  tg_bot_settings: true,  mobile_app: true,  mt5_accounts: 2 },
  elite:     { pairs: 5, auto_execute: true,  copy_trade: true,  tg_bot_approve: true,  tg_bot_settings: true,  mobile_app: true,  mt5_accounts: 5 },
}

const PLAN_COLORS: Record<PlanId, string> = {
  community: '#8899b4', starter: '#4f8ef7', trader: '#00e5cc', pro: '#f0b429', elite: '#8b5cf6',
}

const PAIRS = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'AUD/USD', 'XAU/USD']

const TG_COMMANDS = [
  { cmd: '/status',        desc: 'Account equity, open positions, system status',  plan: 'starter' as PlanId },
  { cmd: '/signals',       desc: 'List pending signals awaiting action',            plan: 'starter' as PlanId },
  { cmd: '/pnl',           desc: "Today's & weekly P&L summary",                   plan: 'starter' as PlanId },
  { cmd: '/trades',        desc: 'Last 10 closed trades with results',              plan: 'starter' as PlanId },
  { cmd: '/approve_[id]',  desc: 'Approve a pending signal for execution',          plan: 'trader'  as PlanId },
  { cmd: '/reject_[id]',   desc: 'Reject a pending signal',                         plan: 'trader'  as PlanId },
  { cmd: '/pause',         desc: 'Pause all auto-trading immediately',              plan: 'trader'  as PlanId },
  { cmd: '/resume',        desc: 'Resume auto-trading',                             plan: 'trader'  as PlanId },
  { cmd: '/risk [%]',      desc: 'Change base risk percentage',                     plan: 'pro'     as PlanId },
  { cmd: '/mode [auto|manual]', desc: 'Switch trading mode remotely',              plan: 'pro'     as PlanId },
  { cmd: '/pairs',         desc: 'Enable or disable a trading pair',               plan: 'pro'     as PlanId },
  { cmd: '/setsl [pips]',  desc: 'Override SL for next signal',                    plan: 'pro'     as PlanId },
  { cmd: '/bind [login]',  desc: 'Check bound MT5 account status',                 plan: 'pro'     as PlanId },
  { cmd: '/accounts',      desc: 'List all bound MT5 accounts (Elite multi-account)', plan: 'elite' as PlanId },
  { cmd: '/api_key',       desc: 'Generate or rotate API key',                     plan: 'elite'   as PlanId },
  { cmd: '/whitelist [ip]',desc: 'Add IP to API access whitelist',                 plan: 'elite'   as PlanId },
]

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label style={{ position: 'relative', width: 38, height: 20, flexShrink: 0, display: 'inline-block', cursor: 'pointer' }}>
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)}
        style={{ opacity: 0, width: 0, height: 0, position: 'absolute' }} />
      <span style={{
        position: 'absolute', inset: 0,
        background: checked ? '#00e5cc' : 'rgba(255,255,255,0.1)',
        borderRadius: 20, transition: '0.3s', cursor: 'pointer',
      }}>
        <span style={{
          position: 'absolute', width: 14, height: 14, left: checked ? 21 : 3, top: 3,
          background: '#fff', borderRadius: '50%', transition: '0.3s',
        }} />
      </span>
    </label>
  )
}

function PlanBadge({ plan }: { plan: PlanId }) {
  const color = PLAN_COLORS[plan]
  return (
    <span className="inline-flex items-center font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest whitespace-nowrap"
      style={{ background: `${color}22`, color, border: `1px solid ${color}44` }}>
      {plan.toUpperCase()}
    </span>
  )
}

const TABS: Tab[] = ['trading', 'risk', 'pairs', 'mt5', 'telegram', 'notifications']

export default function Settings() {
  const [tab, setTab] = useState<Tab>('trading')
  const [tradingMode, setTradingMode] = useState('signal_approval')
  const [riskParams, setRiskParams] = useState({ base: 1, max: 2, maxDD: 15, daily: 5 })
  const [activePairs, setActivePairs] = useState<Record<string, boolean>>({
    'EUR/USD': true, 'GBP/USD': true, 'USD/JPY': false, 'AUD/USD': false, 'XAU/USD': false,
  })
  const [mt5Accounts, setMt5Accounts] = useState([
    { login: '12345678', server: 'Exness-Real', label: 'Primary Account', active: true },
  ])

  const { data: sub } = useQuery({
    queryKey: ['subscription'],
    queryFn: () => api.get('/billing/subscription').then(r => r.data).catch(() => null),
  })

  const { data: settings, refetch } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings').then(r => r.data).catch(() => ({})),
    retry: false,
  })

  const save = useMutation({
    mutationFn: (body: object) => api.patch('/settings', body),
    onSuccess: () => refetch(),
  })

  useEffect(() => {
    if (!settings) return
    const s = settings as any
    if (s.trading_mode)   setTradingMode(s.trading_mode)
    setRiskParams({
      base:  s.base_risk_pct           ?? 1,
      max:   s.risk_max_pct            ?? 2,
      maxDD: s.risk_max_drawdown_pct   ?? 15,
      daily: s.risk_daily_pct          ?? 5,
    })
    if (s.active_pairs && typeof s.active_pairs === 'object')
      setActivePairs(s.active_pairs)
    if (Array.isArray(s.mt5_accounts) && s.mt5_accounts.length)
      setMt5Accounts(s.mt5_accounts)
  }, [settings])

  const plan: PlanId = (sub?.plan as PlanId) ?? 'community'
  const features = PLAN_FEATURES[plan]
  const can = (feat: string) => !!features[feat]
  const planIdx = PLAN_ORDER.indexOf(plan)
  const maxPairs = Number(features.pairs) || 0
  const maxMt5 = Number(features.mt5_accounts) || 1

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Tab bar */}
      <div className="flex gap-0.5 bg-s3 p-1 rounded-[10px]">
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)}
            className="flex-1 text-center py-[7px] font-mono text-[10px] tracking-widest cursor-pointer rounded-[7px] transition-all border border-transparent"
            style={tab === t
              ? { background: 'var(--color-s2)', color: '#00e5cc', border: '1px solid var(--color-card-border)' }
              : { color: 'var(--color-tx3)' }
            }>
            {t.toUpperCase()}
          </button>
        ))}
      </div>

      {/* ── TRADING ── */}
      {tab === 'trading' && (
        <div className="bg-s2 rounded-[14px] p-5" style={{ border: '1px solid var(--color-card-border)' }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
            Trading Configuration
          </div>
          {[
            {
              l: 'Trading Mode', sub: 'Auto-execute or require approval',
              el: (
                <select
                  value={tradingMode}
                  onChange={e => {
                    if (!can('auto_execute') && e.target.value === 'auto_trade') return
                    setTradingMode(e.target.value)
                    save.mutate({ trading_mode: e.target.value })
                  }}
                  style={{
                    fontFamily: '"IBM Plex Mono",monospace', fontSize: 11,
                    background: 'var(--color-s3)', color: 'var(--color-tx)',
                    border: '1px solid var(--color-input-border)', borderRadius: 6, padding: '7px 10px',
                    outline: 'none', cursor: 'pointer',
                  }}>
                  <option value="signal_approval">SIGNAL APPROVAL</option>
                  <option value="auto_trade" disabled={!can('auto_execute')}>
                    AUTO TRADE {can('auto_execute') ? '' : '🔒'}
                  </option>
                </select>
              ),
            },
            {
              l: 'Copy Trade', sub: 'Mirror trades to second MT5 account',
              el: <Toggle checked={can('copy_trade')} onChange={() => {}} />,
            },
            {
              l: 'News Blocking', sub: 'Block trades 30min before high-impact events',
              el: <Toggle checked={!!((settings as any)?.news_blocking ?? true)}
                onChange={v => save.mutate({ news_blocking: v })} />,
            },
            {
              l: 'Friday Cutoff', sub: 'No new trades after 16:00 UTC on Fridays',
              el: <Toggle checked={!!((settings as any)?.friday_cutoff ?? true)}
                onChange={v => save.mutate({ friday_cutoff: v })} />,
            },
          ].map(row => (
            <div key={row.l} className="flex items-center justify-between py-[10px]"
              style={{ borderBottom: '1px solid var(--color-card-border)' }}>
              <div>
                <div style={{ fontSize: 13, color: 'var(--color-tx2)' }}>{row.l}</div>
                <div style={{ fontSize: 11, color: 'var(--color-tx3)', marginTop: 2 }}>{row.sub}</div>
              </div>
              {row.el}
            </div>
          ))}
        </div>
      )}

      {/* ── RISK ── */}
      {tab === 'risk' && (() => {
        const locked = planIdx < PLAN_ORDER.indexOf('starter')
        return (
          <div style={{ position: 'relative' }}>
            <div className="bg-s2 rounded-[14px] p-5" style={{ border: '1px solid var(--color-card-border)', opacity: locked ? 0.4 : 1 }}>
              <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
                Risk Parameters
              </div>
              {[
                { k: 'base',  api: 'base_risk_pct',          l: 'Base Risk %',      min: 0.5, max: 2,  step: 0.1 },
                { k: 'max',   api: 'risk_max_pct',            l: 'Max Risk %',        min: 1,   max: 3,  step: 0.1 },
                { k: 'maxDD', api: 'risk_max_drawdown_pct',   l: 'Max Drawdown %',    min: 5,   max: 25, step: 1   },
                { k: 'daily', api: 'risk_daily_pct',          l: 'Max Daily Risk %',  min: 2,   max: 10, step: 0.5 },
              ].map(p => (
                <div key={p.k} className="flex items-center justify-between py-[10px]"
                  style={{ borderBottom: '1px solid var(--color-card-border)' }}>
                  <div>
                    <div style={{ fontSize: 13, color: 'var(--color-tx2)' }}>{p.l}</div>
                    <div className="font-mono" style={{ fontSize: 11, color: 'var(--color-tx3)', marginTop: 2 }}>
                      {riskParams[p.k as keyof typeof riskParams]}%
                    </div>
                  </div>
                  <input type="range" min={p.min} max={p.max} step={p.step}
                    value={riskParams[p.k as keyof typeof riskParams]}
                    onChange={e => setRiskParams(prev => ({ ...prev, [p.k]: parseFloat(e.target.value) }))}
                    onMouseUp={e => save.mutate({ [p.api]: parseFloat((e.target as HTMLInputElement).value) })}
                    style={{ accentColor: '#00e5cc', width: 130 }} />
                </div>
              ))}
              {!can('tg_bot_settings') && (
                <div style={{
                  marginTop: 16, padding: '10px 14px',
                  background: 'rgba(240,180,41,0.1)', borderRadius: 8,
                  fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: '#f0b429',
                }}>
                  ⚡ PRO plan: Change these parameters via Telegram bot with /risk command
                </div>
              )}
            </div>
            {locked && (
              <div style={{
                position: 'absolute', inset: 0,
                background: 'rgba(5,8,15,0.8)', backdropFilter: 'blur(3px)',
                borderRadius: 14, display: 'flex', alignItems: 'center', justifyContent: 'center',
                zIndex: 10, flexDirection: 'column', gap: 10,
              }}>
                <div style={{ fontSize: 20 }}>🔒</div>
                <div className="font-mono text-[11px] text-center" style={{ color: '#f0b429' }}>
                  Requires STARTER plan
                </div>
              </div>
            )}
          </div>
        )
      })()}

      {/* ── PAIRS ── */}
      {tab === 'pairs' && (
        <div className="bg-s2 rounded-[14px] p-5" style={{ border: '1px solid var(--color-card-border)' }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
            Active Trading Pairs
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 10 }}>
            {PAIRS.map((pair, i) => {
              const allowed = i < maxPairs
              const active = activePairs[pair] && allowed
              return (
                <div key={pair} style={{
                  background: 'var(--color-s3)',
                  border: `1px solid ${active ? 'rgba(0,229,204,0.3)' : 'var(--color-card-border)'}`,
                  borderRadius: 10, padding: '14px 12px', textAlign: 'center',
                  opacity: allowed ? 1 : 0.5,
                }}>
                  <div style={{
                    fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, fontWeight: 700,
                    marginBottom: 8, color: active ? '#00e5cc' : 'var(--color-tx3)',
                  }}>
                    {pair}
                  </div>
                  <Toggle
                    checked={active}
                    onChange={v => {
                      if (!allowed) return
                      const updated = { ...activePairs, [pair]: v }
                      setActivePairs(updated)
                      save.mutate({ active_pairs: updated })
                    }}
                  />
                  {!allowed && (
                    <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 9, color: 'var(--color-tx3)', marginTop: 6 }}>
                      UPGRADE
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── MT5 ── */}
      {tab === 'mt5' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="bg-s2 rounded-[14px] p-5" style={{ border: '1px solid var(--color-card-border)' }}>
            <div className="flex items-center justify-between mb-[14px]">
              <div className="font-mono text-[10px] tracking-[2px] uppercase" style={{ color: 'var(--color-tx3)' }}>
                Bound MT5 Accounts
              </div>
              <div className="font-mono text-[10px]" style={{ color: 'var(--color-tx3)' }}>
                {mt5Accounts.length} / {maxMt5} allowed
              </div>
            </div>

            {mt5Accounts.map((acc, i) => (
              <div key={i} style={{
                background: 'var(--color-s3)', border: '1px solid var(--color-card-border)',
                borderRadius: 10, padding: 14, marginBottom: 10,
                display: 'flex', alignItems: 'center', gap: 12,
              }}>
                <div style={{
                  width: 36, height: 36, borderRadius: 8,
                  background: 'rgba(0,229,204,0.1)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontFamily: '"IBM Plex Mono",monospace', fontSize: 11, color: '#00e5cc',
                }}>
                  MT5
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 13, fontWeight: 700 }}>
                    {acc.login}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--color-tx3)' }}>
                    {acc.server} · {acc.label}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#00e596', boxShadow: '0 0 6px #00e596', display: 'inline-block' }} />
                  <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: '#00e5cc' }}>CONNECTED</span>
                  <button
                    onClick={() => {
                      const updated = mt5Accounts.filter((_, j) => j !== i)
                      setMt5Accounts(updated)
                      save.mutate({ mt5_accounts: updated })
                    }}
                    className="font-mono text-[10px] font-bold tracking-widest px-3 py-1.5 rounded-lg cursor-pointer transition-all"
                    style={{ background: '#ff3d5a', color: '#fff', border: 'none' }}>
                    UNBIND
                  </button>
                </div>
              </div>
            ))}

            {mt5Accounts.length < maxMt5 && (
              <button
                className="font-mono text-[11px] font-bold tracking-widest px-[18px] py-[9px] rounded-lg cursor-pointer transition-all w-full flex justify-center"
                style={{ background: 'var(--color-divider)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.09)' }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'var(--color-divider)' }}>
                + BIND NEW MT5 ACCOUNT
              </button>
            )}

            <div style={{
              marginTop: 12, padding: '10px 14px', background: 'var(--color-s3)',
              borderRadius: 8, fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: 'var(--color-tx3)',
            }}>
              ⚠ MT5 accounts can only be bound or unbound from this web/app interface. Not via Telegram.
            </div>
          </div>
        </div>
      )}

      {/* ── TELEGRAM ── */}
      {tab === 'telegram' && (
        <div className="bg-s2 rounded-[14px] p-5" style={{ border: '1px solid var(--color-card-border)' }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
            Telegram Bot — Available Commands
          </div>

          <div style={{
            marginBottom: 16, padding: '10px 14px',
            background: 'rgba(79,142,247,0.1)', border: '1px solid rgba(79,142,247,0.2)',
            borderRadius: 8, fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: '#4f8ef7',
          }}>
            Your bot: @TradingAI_bot · Connect via Telegram to get started
          </div>

          {TG_COMMANDS.map(cmd => {
            const cmdIdx = PLAN_ORDER.indexOf(cmd.plan)
            const locked = cmdIdx > planIdx
            return (
              <div key={cmd.cmd}
                className="flex justify-between items-center py-[10px]"
                style={{ borderBottom: '1px solid var(--color-card-border)', opacity: locked ? 0.5 : 1 }}>
                <div>
                  <div className="flex items-center gap-1.5">
                    <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, color: '#00e5cc' }}>
                      {cmd.cmd}
                    </span>
                    {locked && <span style={{ color: 'var(--color-tx3)' }}>🔒</span>}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--color-tx2)', marginTop: 2 }}>{cmd.desc}</div>
                </div>
                <PlanBadge plan={cmd.plan} />
              </div>
            )
          })}
        </div>
      )}

      {/* ── NOTIFICATIONS ── */}
      {tab === 'notifications' && (
        <div className="bg-s2 rounded-[14px] p-5" style={{ border: '1px solid var(--color-card-border)' }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
            Notification Preferences
          </div>
          {[
            { l: 'Signal alerts (Telegram)',        s: 'Instant message on new signals',             checked: true },
            { l: 'Trade execution confirmations',   s: 'When a trade is placed or closed',           checked: true },
            { l: 'Daily P&L summary',               s: 'End-of-day summary at 22:00 UTC',            checked: true },
            { l: 'Drawdown warnings',               s: 'Alert when drawdown exceeds 10%',            checked: true },
            { l: 'News event reminders',            s: '30 minutes before high-impact events',       checked: can('tg_bot_approve') },
            { l: 'Email notifications',             s: 'Daily summary and trade reports',            checked: false },
            { l: 'Push notifications (mobile)',     s: 'Requires mobile app',                        checked: can('mobile_app') },
          ].map(n => (
            <div key={n.l} className="flex items-center justify-between py-[10px]"
              style={{ borderBottom: '1px solid var(--color-card-border)' }}>
              <div>
                <div style={{ fontSize: 13, color: 'var(--color-tx2)' }}>{n.l}</div>
                <div style={{ fontSize: 11, color: 'var(--color-tx3)', marginTop: 2 }}>{n.s}</div>
              </div>
              <Toggle checked={n.checked} onChange={() => {}} />
            </div>
          ))}
        </div>
      )}

    </div>
  )
}
