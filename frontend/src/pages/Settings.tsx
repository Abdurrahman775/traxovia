import { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

// ─── Types ────────────────────────────────────────────────────────────────────

type Tab = 'trading' | 'risk' | 'pairs' | 'mt5' | 'telegram' | 'notifications'
type PlanId = 'community' | 'starter' | 'trader' | 'pro' | 'elite'

const PLAN_ORDER: PlanId[] = ['community', 'starter', 'trader', 'pro', 'elite']
const PAIRS = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'AUD/USD', 'XAU/USD']

const TG_COMMANDS = [
  { cmd: '/status',             desc: 'Account equity, open positions, system status',     plan: 'starter'  as PlanId },
  { cmd: '/signals',            desc: 'List pending signals awaiting action',               plan: 'starter'  as PlanId },
  { cmd: '/pnl',                desc: "Today's & weekly P&L summary",                       plan: 'starter'  as PlanId },
  { cmd: '/trades',             desc: 'Last 10 closed trades with results',                 plan: 'starter'  as PlanId },
  { cmd: '/approve_[id]',       desc: 'Approve a pending signal for execution',             plan: 'trader'   as PlanId },
  { cmd: '/reject_[id]',        desc: 'Reject a pending signal',                            plan: 'trader'   as PlanId },
  { cmd: '/pause',              desc: 'Pause all auto-trading immediately',                 plan: 'trader'   as PlanId },
  { cmd: '/resume',             desc: 'Resume auto-trading',                                plan: 'trader'   as PlanId },
  { cmd: '/risk [%]',           desc: 'Change base risk percentage',                        plan: 'pro'      as PlanId },
  { cmd: '/mode [auto|manual]', desc: 'Switch trading mode remotely',                      plan: 'pro'      as PlanId },
  { cmd: '/pairs',              desc: 'Enable or disable a trading pair',                  plan: 'pro'      as PlanId },
  { cmd: '/setsl [pips]',       desc: 'Override SL for next signal',                       plan: 'pro'      as PlanId },
  { cmd: '/bind [login]',       desc: 'Check bound MT5 account status',                    plan: 'pro'      as PlanId },
  { cmd: '/accounts',           desc: 'List all bound MT5 accounts (Elite multi-account)', plan: 'elite'    as PlanId },
  { cmd: '/api_key',            desc: 'Generate or rotate API key',                        plan: 'elite'    as PlanId },
  { cmd: '/whitelist [ip]',     desc: 'Add IP to API access whitelist',                    plan: 'elite'    as PlanId },
]

// ─── Shared UI ────────────────────────────────────────────────────────────────

const CARD: React.CSSProperties = {
  background: 'var(--color-s2)',
  border: '1px solid var(--color-card-border)',
  borderRadius: 14,
  padding: 20,
}

function Toggle({ checked, onChange, disabled, activeColor = '#00e5cc' }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; activeColor?: string }) {
  return (
    <label style={{ position: 'relative', width: 38, height: 20, flexShrink: 0, display: 'inline-block', cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.4 : 1 }}>
      <input type="checkbox" checked={checked} onChange={e => !disabled && onChange(e.target.checked)}
        style={{ opacity: 0, width: 0, height: 0, position: 'absolute' }} />
      <span style={{ position: 'absolute', inset: 0, background: checked ? activeColor : 'rgba(255,255,255,0.1)', borderRadius: 20, transition: '0.3s' }}>
        <span style={{ position: 'absolute', width: 14, height: 14, left: checked ? 21 : 3, top: 3, background: '#fff', borderRadius: '50%', transition: '0.3s' }} />
      </span>
    </label>
  )
}

function PlanBadge({ plan }: { plan: PlanId }) {
  const colors: Record<PlanId, string> = { community: '#8899b4', starter: '#4f8ef7', trader: '#00e5cc', pro: '#f0b429', elite: '#8b5cf6' }
  const c = colors[plan]
  return (
    <span className="inline-flex items-center font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest whitespace-nowrap"
      style={{ background: `${c}22`, color: c, border: `1px solid ${c}44` }}>
      {plan.toUpperCase()}
    </span>
  )
}

function SaveBadge({ state }: { state: 'idle' | 'saving' | 'saved' | 'error' }) {
  if (state === 'idle') return null
  const map = {
    saving: { color: '#f0b429', label: 'Saving…' },
    saved:  { color: '#00e5cc', label: '✓ Saved' },
    error:  { color: '#ff3d5a', label: '✗ Error' },
  }
  const { color, label } = map[state as keyof typeof map]
  return (
    <span className="font-mono text-[10px] px-2 py-0.5 rounded"
      style={{ background: `${color}15`, color, border: `1px solid ${color}30` }}>
      {label}
    </span>
  )
}

function RowItem({ label, sub, el }: { label: string; sub: string; el: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-[10px]"
      style={{ borderBottom: '1px solid var(--color-card-border)' }}>
      <div>
        <div style={{ fontSize: 13, color: 'var(--color-tx2)' }}>{label}</div>
        <div style={{ fontSize: 11, color: 'var(--color-tx3)', marginTop: 2 }}>{sub}</div>
      </div>
      {el}
    </div>
  )
}

// ─── MT5 Bind Form ────────────────────────────────────────────────────────────

const BROKER_SERVERS: { broker: string; servers: string[] }[] = [
  { broker: 'Exness',       servers: ['Exness-Real', 'Exness-Real8', 'Exness-Trial'] },
  { broker: 'IC Markets',   servers: ['ICMarkets-Live01', 'ICMarkets-Live02', 'ICMarkets-Demo01'] },
  { broker: 'Pepperstone',  servers: ['Pepperstone-Edge-Live', 'Pepperstone-Live', 'Pepperstone-Demo'] },
  { broker: 'XM',           servers: ['XMTrading-Real', 'XMTrading-Real2', 'XMTrading-Demo3'] },
  { broker: 'FP Markets',   servers: ['FPMarkets-Live01', 'FPMarkets-Demo01'] },
  { broker: 'FTMO',         servers: ['FTMO-Server', 'FTMO-Demo2'] },
  { broker: 'OctaFX',       servers: ['OctaFX-Real', 'OctaFX-Demo'] },
  { broker: 'Deriv',        servers: ['Deriv-Demo', 'Deriv-Server'] },
  { broker: 'Tickmill',     servers: ['Tickmill-Live', 'Tickmill-Demo'] },
  { broker: 'HFM',          servers: ['HFMarkets-Live', 'HFMarkets-Demo'] },
  { broker: 'Vantage',      servers: ['Vantage-Live', 'Vantage-Demo'] },
  { broker: 'EightCap',     servers: ['EightCap-Live', 'EightCap-Demo'] },
]

function BindMt5Form({ onSave, onCancel }: { onSave(acc: object): void; onCancel(): void }) {
  const [form, setForm] = useState({ login: '', password: '', server: '', label: '' })
  const [showPass, setShowPass] = useState(false)
  const [brokerOpen, setBrokerOpen] = useState(false)

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm(p => ({ ...p, [k]: e.target.value }))

  const INPUT: React.CSSProperties = {
    width: '100%', background: 'var(--color-s2)', border: '1px solid var(--color-input-border)',
    borderRadius: 7, padding: '8px 11px', color: 'var(--color-tx)',
    fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, outline: 'none',
  }
  const focus = (e: React.FocusEvent<HTMLInputElement>) => (e.target.style.borderColor = '#00e5cc')
  const blur  = (e: React.FocusEvent<HTMLInputElement>) => (e.target.style.borderColor = 'var(--color-input-border)')

  const canSubmit = form.login && form.password && form.server

  return (
    <div style={{ background: 'var(--color-s3)', border: '1px solid rgba(0,229,204,0.2)', borderRadius: 10, padding: 16, marginBottom: 10 }}>
      <div className="font-mono text-[10px] tracking-widest uppercase mb-1" style={{ color: '#00e5cc' }}>Bind MT5 Account</div>
      <div className="font-mono text-[10px] mb-4" style={{ color: 'var(--color-tx3)' }}>
        Works with any MT5 broker — enter the credentials from your broker's welcome email.
      </div>

      {/* Broker quick-select */}
      <div className="mb-3">
        <div className="font-mono text-[9px] uppercase tracking-widest mb-1" style={{ color: 'var(--color-tx3)' }}>
          Broker <span style={{ color: 'var(--color-tx3)', fontWeight: 400 }}>(optional — select to auto-fill server)</span>
        </div>
        <div style={{ position: 'relative' }}>
          <button
            type="button"
            onClick={() => setBrokerOpen(o => !o)}
            style={{ ...INPUT, textAlign: 'left', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
          >
            <span style={{ color: form.server ? 'var(--color-tx)' : 'var(--color-tx3)' }}>
              {BROKER_SERVERS.find(b => b.servers.includes(form.server))?.broker ?? 'Select broker or type server below'}
            </span>
            <span style={{ fontSize: 10 }}>{brokerOpen ? '▲' : '▼'}</span>
          </button>
          {brokerOpen && (
            <div style={{
              position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
              background: 'var(--color-s2)', border: '1px solid rgba(0,229,204,0.25)',
              borderRadius: 8, marginTop: 4, maxHeight: 240, overflowY: 'auto',
              boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
            }}>
              {BROKER_SERVERS.map(({ broker, servers }) => (
                <div key={broker}>
                  <div className="font-mono text-[9px] uppercase tracking-widest px-3 py-1.5"
                    style={{ color: '#00e5cc', background: 'rgba(0,229,204,0.05)', borderBottom: '1px solid rgba(0,229,204,0.1)' }}>
                    {broker}
                  </div>
                  {servers.map(srv => (
                    <div key={srv}
                      onClick={() => { setForm(p => ({ ...p, server: srv })); setBrokerOpen(false) }}
                      className="font-mono text-[11px] px-4 py-2 cursor-pointer"
                      style={{ color: 'var(--color-tx2)', borderBottom: '1px solid rgba(255,255,255,0.04)' }}
                      onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,229,204,0.08)')}
                      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                    >
                      {srv}
                    </div>
                  ))}
                </div>
              ))}
              <div style={{ padding: '8px 12px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                <span className="font-mono text-[9px]" style={{ color: 'var(--color-tx3)' }}>
                  Don't see your broker? Type the server name directly below.
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Form fields */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-2">
        <div>
          <div className="font-mono text-[9px] uppercase tracking-widest mb-1" style={{ color: 'var(--color-tx3)' }}>Login *</div>
          <input style={INPUT} value={form.login} onChange={set('login')} placeholder="12345678" onFocus={focus} onBlur={blur} />
        </div>
        <div>
          <div className="font-mono text-[9px] uppercase tracking-widest mb-1" style={{ color: 'var(--color-tx3)' }}>Password *</div>
          <div style={{ position: 'relative' }}>
            <input style={{ ...INPUT, paddingRight: 36 }} type={showPass ? 'text' : 'password'}
              value={form.password} onChange={set('password')} placeholder="••••••••" onFocus={focus} onBlur={blur} />
            <button type="button" onClick={() => setShowPass(s => !s)}
              style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)',
                background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-tx3)', fontSize: 12 }}>
              {showPass ? '🙈' : '👁'}
            </button>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3">
        <div>
          <div className="font-mono text-[9px] uppercase tracking-widest mb-1" style={{ color: 'var(--color-tx3)' }}>Server *</div>
          <input style={INPUT} value={form.server} onChange={set('server')} placeholder="BrokerName-Live01" onFocus={focus} onBlur={blur} />
        </div>
        <div>
          <div className="font-mono text-[9px] uppercase tracking-widest mb-1" style={{ color: 'var(--color-tx3)' }}>Label</div>
          <input style={INPUT} value={form.label} onChange={set('label')} placeholder="My Main Account" onFocus={focus} onBlur={blur} />
        </div>
      </div>

      <div className="font-mono text-[9px] mb-3" style={{ color: 'var(--color-tx3)' }}>
        * To find your server name: open MT5 → File → Open Account → search your broker name.
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => {
            if (canSubmit) onSave({
              login: form.login, password: form.password,
              server: form.server, label: form.label || form.login, active: true,
            })
          }}
          disabled={!canSubmit}
          className="font-mono text-[10px] font-bold tracking-widest px-4 py-1.5 rounded-lg transition-all disabled:opacity-40"
          style={{ background: '#00e5cc', color: '#000', border: 'none' }}>
          BIND ACCOUNT
        </button>
        <button onClick={onCancel}
          className="font-mono text-[10px] px-3 py-1.5 rounded-lg transition-all"
          style={{ background: 'var(--color-s2)', color: 'var(--color-tx3)', border: '1px solid var(--color-card-border)' }}>
          Cancel
        </button>
      </div>
    </div>
  )
}

// ─── Telegram linking tab ─────────────────────────────────────────────────────

function TelegramTab({ planIdx, botUsername }: { planIdx: number; botUsername?: string }) {
  const qc = useQueryClient()

  const { data: tgStatus, isLoading: statusLoading } = useQuery({
    queryKey: ['telegram-status'],
    queryFn:  () => api.get('/settings/telegram/status').then(r => r.data as { linked: boolean; telegram_chat_id: number | null; telegram_username: string | null }),
    staleTime: 30_000,
  })

  const [token,     setToken]     = useState<string | null>(null)
  const [expiresAt, setExpiresAt] = useState<number | null>(null)  // unix ms
  const [copied,    setCopied]    = useState(false)
  const [countdown, setCountdown] = useState(0)

  // tick down countdown every second
  useEffect(() => {
    if (!expiresAt) return
    const id = setInterval(() => {
      const left = Math.max(0, Math.floor((expiresAt - Date.now()) / 1000))
      setCountdown(left)
      if (left === 0) { setToken(null); setExpiresAt(null) }
    }, 1000)
    return () => clearInterval(id)
  }, [expiresAt])

  const generateMutation = useMutation({
    mutationFn: () => api.post('/settings/telegram/link-token').then(r => r.data as { token: string; expires_at: string }),
    onSuccess: d => {
      setToken(d.token)
      setExpiresAt(new Date(d.expires_at).getTime())
      setCountdown(900)
    },
  })

  const unlinkMutation = useMutation({
    mutationFn: () => api.delete('/settings/telegram/unlink'),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['telegram-status'] }),
  })

  const copyToken = useCallback(() => {
    if (!token) return
    navigator.clipboard.writeText(`/link ${token}`)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [token])

  const fmtCountdown = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

  return (
    <div className="space-y-4">

      {/* ── Link status card ── */}
      <div style={{ ...CARD }}>
        <div className="font-mono text-[10px] tracking-[2px] uppercase mb-3" style={{ color: 'var(--color-tx3)' }}>
          Account Link Status
        </div>

        {statusLoading ? (
          <div className="text-sm text-tx2 animate-pulse">Checking…</div>
        ) : tgStatus?.linked ? (
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full flex items-center justify-center text-base"
                style={{ background: 'rgba(0,229,204,0.12)', border: '1px solid rgba(0,229,204,0.3)' }}>✓</div>
              <div>
                <div className="text-sm font-semibold text-tx">Telegram linked</div>
                <div className="text-xs font-mono text-tx3 mt-0.5">
                  {tgStatus.telegram_username ? `@${tgStatus.telegram_username}` : `Chat ID: ${tgStatus.telegram_chat_id}`}
                </div>
              </div>
            </div>
            <button
              onClick={() => unlinkMutation.mutate()}
              disabled={unlinkMutation.isPending}
              className="px-3 py-1.5 rounded-lg text-xs font-mono transition-colors disabled:opacity-50"
              style={{ background: 'rgba(255,61,90,0.1)', color: '#ff3d5a', border: '1px solid rgba(255,61,90,0.25)' }}>
              {unlinkMutation.isPending ? 'Unlinking…' : 'Unlink'}
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full flex items-center justify-center text-base"
              style={{ background: 'rgba(255,61,90,0.08)', border: '1px solid rgba(255,61,90,0.2)', color: '#ff3d5a' }}>✗</div>
            <div>
              <div className="text-sm font-semibold text-tx">Not linked</div>
              <div className="text-xs text-tx3 mt-0.5">Generate a token below to connect your Telegram account.</div>
            </div>
          </div>
        )}
      </div>

      {/* ── Token generation card ── */}
      {!tgStatus?.linked && (
        <div style={{ ...CARD }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-3" style={{ color: 'var(--color-tx3)' }}>
            Link Your Telegram Account
          </div>

          <ol className="text-sm text-tx2 space-y-1.5 mb-4 list-decimal list-inside">
            <li>Find your bot on Telegram{botUsername ? <> — <span className="font-mono text-cy">@{botUsername}</span></> : ''}</li>
            <li>Click <b>Generate Token</b> below</li>
            <li>Copy the command and send it to the bot</li>
          </ol>

          {token ? (
            <div className="space-y-3">
              <div className="rounded-xl p-4 text-center" style={{ background: 'rgba(0,229,204,0.06)', border: '1px solid rgba(0,229,204,0.25)' }}>
                <div className="text-[10px] font-mono text-tx3 uppercase tracking-widest mb-2">Send this to the bot</div>
                <div className="font-mono text-lg font-bold tracking-wider" style={{ color: 'var(--color-cy)' }}>
                  /link {token}
                </div>
                <div className="text-[10px] font-mono text-tx3 mt-2">
                  Expires in <span style={{ color: countdown < 60 ? '#ff3d5a' : '#f0b429' }}>{fmtCountdown(countdown)}</span>
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={copyToken}
                  className="flex-1 py-2 rounded-lg text-xs font-mono font-bold tracking-widest transition-colors"
                  style={{ background: copied ? 'rgba(0,229,204,0.15)' : 'rgba(0,229,204,0.1)', color: 'var(--color-cy)', border: '1px solid rgba(0,229,204,0.3)' }}>
                  {copied ? '✓ COPIED' : '⎘ COPY COMMAND'}
                </button>
                <button onClick={() => generateMutation.mutate()}
                  className="px-4 py-2 rounded-lg text-xs font-mono text-tx2 border border-s3 hover:bg-s2 transition-colors">
                  Regenerate
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
              className="w-full py-2.5 rounded-xl font-mono font-bold text-sm tracking-widest transition-colors disabled:opacity-50"
              style={{ background: '#00e5cc', color: '#000' }}>
              {generateMutation.isPending ? 'Generating…' : 'Generate Token'}
            </button>
          )}
        </div>
      )}

      {/* ── Command reference ── */}
      <div style={{ ...CARD }}>
        <div className="font-mono text-[10px] tracking-[2px] uppercase mb-3" style={{ color: 'var(--color-tx3)' }}>
          Bot Commands — Your Plan
        </div>
        {TG_COMMANDS.map(cmd => {
          const cmdIdx = PLAN_ORDER.indexOf(cmd.plan)
          const locked = cmdIdx > planIdx
          return (
            <div key={cmd.cmd} className="flex justify-between items-center py-2.5"
              style={{ borderBottom: '1px solid var(--color-card-border)', opacity: locked ? 0.4 : 1 }}>
              <div>
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-xs" style={{ color: locked ? 'var(--color-tx3)' : '#00e5cc' }}>{cmd.cmd}</span>
                  {locked && <span className="text-[10px]">🔒</span>}
                </div>
                <div className="text-xs text-tx2 mt-0.5">{cmd.desc}</div>
              </div>
              <PlanBadge plan={cmd.plan} />
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Main ─────────────────────────────────────────────────────────────────────

const TABS: { key: Tab; icon: string; short: string }[] = [
  { key: 'trading',       icon: '⚡', short: 'Trading'  },
  { key: 'risk',          icon: '◈', short: 'Risk'     },
  { key: 'pairs',         icon: '◇', short: 'Pairs'    },
  { key: 'mt5',           icon: '⬡', short: 'MT5'      },
  { key: 'telegram',      icon: '✦', short: 'Telegram' },
  { key: 'notifications', icon: '◎', short: 'Alerts'   },
]

export default function Settings() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('trading')
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [showBindForm, setShowBindForm] = useState(false)

  // Local state mirrors — hydrated from API
  const [tradingPaused, setTradingPaused]   = useState(false)
  const [tradingMode, setTradingMode]       = useState('signal_approval')
  const [newsBlocking, setNewsBlocking]     = useState(true)
  const [fridayCutoff, setFridayCutoff]     = useState(true)
  const [copyTrade, setCopyTrade]           = useState(false)
  const [riskParams, setRiskParams]         = useState({ base: 1, max: 2, maxDD: 15, daily: 5 })
  const [activePairs, setActivePairs]       = useState<Record<string, boolean>>({
    'EUR/USD': true, 'GBP/USD': true, 'USD/JPY': false, 'AUD/USD': false, 'XAU/USD': false,
  })
  const [mt5Accounts, setMt5Accounts]       = useState<any[]>([])
  const [notifPrefs, setNotifPrefs]         = useState<Record<string, boolean>>({
    signal_alerts: true, trade_execution: true, daily_pnl: true,
    drawdown_warning: true, news_reminder: true, email_notifications: false, push_notifications: false,
  })

  // ── Remote data ──
  const { data: sub } = useQuery({
    queryKey: ['subscription'],
    queryFn: () => api.get('/billing/subscription').then(r => r.data).catch(() => null),
  })

  const { data: plans = [] } = useQuery<any[]>({
    queryKey: ['plans'],
    queryFn: () => api.get('/billing/plans').then(r => Array.isArray(r.data) ? r.data : (r.data?.plans ?? [])).catch(() => []),
  })

  const { data: settings, refetch } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings').then(r => r.data).catch(() => ({})),
    retry: false,
  })

  useEffect(() => {
    if (!settings) return
    const s = settings as any
    if (s.trading_paused  !== undefined) setTradingPaused(s.trading_paused)
    if (s.trading_mode)    setTradingMode(s.trading_mode)
    if (s.news_blocking   !== undefined) setNewsBlocking(s.news_blocking)
    if (s.friday_cutoff   !== undefined) setFridayCutoff(s.friday_cutoff)
    if (s.copy_trade_enabled !== undefined) setCopyTrade(s.copy_trade_enabled)
    setRiskParams({
      base:  s.base_risk_pct          ?? 1,
      max:   s.risk_max_pct           ?? 2,
      maxDD: s.risk_max_drawdown_pct  ?? 15,
      daily: s.risk_daily_pct         ?? 5,
    })
    if (s.active_pairs && typeof s.active_pairs === 'object')
      setActivePairs(s.active_pairs)
    if (Array.isArray(s.mt5_accounts))
      setMt5Accounts(s.mt5_accounts)
    if (s.notification_prefs && typeof s.notification_prefs === 'object')
      setNotifPrefs(s.notification_prefs)
  }, [settings])

  // ── Plan feature gate ──
  const plan: PlanId = (sub?.plan as PlanId) ?? 'community'
  const planIdx = PLAN_ORDER.indexOf(plan)
  const isAdmin = plan === 'elite'
  const planDef = plans.find((p: any) => p.plan_id === plan)
  const features = planDef?.features ?? {}
  // Elite/admin bypasses all feature gates — unlimited access
  const can = (feat: string) => isAdmin || !!features[feat]
  const maxPairs = isAdmin ? PAIRS.length : (Number(features.pairs) || 0)
  const maxMt5   = isAdmin ? 99           : (Number(features.mt5_accounts) || 1)

  // ── Save helper ──
  const save = useMutation({
    mutationFn: (body: object) => api.patch('/settings', body),
    onMutate:   () => setSaveState('saving'),
    onSuccess:  () => { setSaveState('saved'); refetch(); setTimeout(() => setSaveState('idle'), 2000) },
    onError:    () => { setSaveState('error');            setTimeout(() => setSaveState('idle'), 3000) },
  })

  const patch = (body: object) => save.mutate(body)

  return (
    <div className="space-y-4">

      {/* Tab bar */}
      <div className="rounded-[10px] p-1" style={{ background: 'var(--color-s3)' }}>
        {/* Mobile: icon + short label, scrollable */}
        <div className="flex sm:hidden gap-0.5 overflow-x-auto">
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)} title={t.key}
              className="shrink-0 flex flex-col items-center gap-0.5 px-3 py-2 rounded-[7px] transition-all border border-transparent"
              style={tab === t.key
                ? { background: 'var(--color-s2)', color: '#00e5cc', border: '1px solid var(--color-card-border)' }
                : { color: 'var(--color-tx3)' }
              }>
              <span className="text-sm leading-none">{t.icon}</span>
              <span className="font-mono text-[9px] tracking-wide whitespace-nowrap">{t.short}</span>
            </button>
          ))}
        </div>
        {/* sm+: equal-width full row */}
        <div className="hidden sm:flex gap-0.5">
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className="flex-1 flex items-center justify-center gap-1.5 py-[7px] font-mono text-[10px] tracking-widest cursor-pointer rounded-[7px] transition-all border border-transparent"
              style={tab === t.key
                ? { background: 'var(--color-s2)', color: '#00e5cc', border: '1px solid var(--color-card-border)' }
                : { color: 'var(--color-tx3)' }
              }>
              <span>{t.icon}</span>
              <span>{t.short.toUpperCase()}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Save status pill */}
      <div className="flex justify-end h-5">
        <SaveBadge state={saveState} />
      </div>

      {/* ── TRADING ── */}
      {tab === 'trading' && (
        <div style={CARD}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
            Trading Configuration
          </div>

          <RowItem label="Pause Trading" sub="Halt all automated trade execution (mirrors Telegram /pause)" el={
            <Toggle
              checked={tradingPaused}
              onChange={v => { setTradingPaused(v); patch({ trading_paused: v }) }}
              activeColor="#f59e0b"
            />
          } />

          <RowItem label="Trading Mode" sub="Auto-execute or require approval before each trade" el={
            <select
              value={tradingMode}
              onChange={e => {
                if (!can('auto_execute') && e.target.value === 'auto_trade') return
                setTradingMode(e.target.value)
                patch({ trading_mode: e.target.value })
              }}
              style={{
                fontFamily: '"IBM Plex Mono",monospace', fontSize: 11,
                background: 'var(--color-s3)', color: 'var(--color-tx)',
                border: '1px solid var(--color-input-border)', borderRadius: 6, padding: '7px 10px',
                outline: 'none', cursor: 'pointer',
              }}>
              <option value="signal_approval">SIGNAL APPROVAL</option>
              <option value="auto_trade" disabled={!can('auto_execute')}>
                AUTO TRADE{!can('auto_execute') ? ' 🔒' : ''}
              </option>
            </select>
          } />

          <RowItem label="Copy Trade" sub="Mirror trades to a second MT5 account"
            el={<Toggle checked={copyTrade} disabled={!can('copy_trade')}
              onChange={v => { setCopyTrade(v); patch({ copy_trade_enabled: v }) }} />}
          />

          <RowItem label="News Blocking" sub="Block trades 30 min before high-impact news events"
            el={<Toggle checked={newsBlocking}
              onChange={v => { setNewsBlocking(v); patch({ news_blocking: v }) }} />}
          />

          <RowItem label="Friday Cutoff" sub="No new trades after 16:00 UTC on Fridays"
            el={<Toggle checked={fridayCutoff}
              onChange={v => { setFridayCutoff(v); patch({ friday_cutoff: v }) }} />}
          />

          {!can('copy_trade') && (
            <div className="mt-3 px-3 py-2 rounded-lg font-mono text-[10px]"
              style={{ background: 'rgba(240,180,41,0.07)', color: '#f0b429', border: '1px solid rgba(240,180,41,0.15)' }}>
              ⬡ Copy Trade requires TRADER plan or above
            </div>
          )}
          {!can('auto_execute') && (
            <div className="mt-2 px-3 py-2 rounded-lg font-mono text-[10px]"
              style={{ background: 'rgba(240,180,41,0.07)', color: '#f0b429', border: '1px solid rgba(240,180,41,0.15)' }}>
              ⬡ Auto Trade requires PRO plan or above
            </div>
          )}
        </div>
      )}

      {/* ── RISK ── */}
      {tab === 'risk' && (() => {
        const locked = planIdx < PLAN_ORDER.indexOf('starter')
        return (
          <div style={{ position: 'relative' }}>
            <div style={{ ...CARD, opacity: locked ? 0.4 : 1 }}>
              <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
                Risk Parameters
              </div>
              {[
                { k: 'base',  api: 'base_risk_pct',         l: 'Base Risk %',       min: 0.5, max: 10, step: 0.1 },
                { k: 'max',   api: 'risk_max_pct',           l: 'Max Risk %',        min: 1,   max: 10, step: 0.1 },
                { k: 'maxDD', api: 'risk_max_drawdown_pct',  l: 'Max Drawdown %',    min: 5,   max: 25, step: 1   },
                { k: 'daily', api: 'risk_daily_pct',         l: 'Max Daily Risk %',  min: 2,   max: 10, step: 0.5 },
              ].map(p => (
                <div key={p.k} className="flex items-center justify-between py-[10px]"
                  style={{ borderBottom: '1px solid var(--color-card-border)' }}>
                  <div>
                    <div style={{ fontSize: 13, color: 'var(--color-tx2)' }}>{p.l}</div>
                    <div className="font-mono" style={{ fontSize: 11, color: '#00e5cc', marginTop: 2 }}>
                      {riskParams[p.k as keyof typeof riskParams]}%
                    </div>
                  </div>
                  <input type="range" min={p.min} max={p.max} step={p.step}
                    value={riskParams[p.k as keyof typeof riskParams]}
                    onChange={e => setRiskParams(prev => ({ ...prev, [p.k]: parseFloat(e.target.value) }))}
                    onMouseUp={e => patch({ [p.api]: parseFloat((e.target as HTMLInputElement).value) })}
                    onTouchEnd={e => patch({ [p.api]: parseFloat((e.target as HTMLInputElement).value) })}
                    style={{ accentColor: '#00e5cc', width: 130 }} />
                </div>
              ))}
              {can('tg_bot_settings') && (
                <div className="mt-3 px-3 py-2 rounded-lg font-mono text-[10px]"
                  style={{ background: 'rgba(240,180,41,0.07)', color: '#f0b429', border: '1px solid rgba(240,180,41,0.15)' }}>
                  ⚡ You can also adjust risk via Telegram bot: /risk [%]
                </div>
              )}
            </div>
            {locked && (
              <div style={{
                position: 'absolute', inset: 0, background: 'rgba(5,8,15,0.8)', backdropFilter: 'blur(3px)',
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
        <div style={CARD}>
          <div className="flex items-center justify-between mb-[14px]">
            <div className="font-mono text-[10px] tracking-[2px] uppercase" style={{ color: 'var(--color-tx3)' }}>
              Active Trading Pairs
            </div>
            <div className="font-mono text-[10px]" style={{ color: 'var(--color-tx3)' }}>
              {Object.values(activePairs).filter(Boolean).length} / {maxPairs} active
            </div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2.5">
            {PAIRS.map((pair, i) => {
              const allowed = i < maxPairs
              const active  = activePairs[pair] && allowed
              return (
                <div key={pair} className="flex items-center justify-between sm:flex-col sm:items-center sm:justify-center gap-3 sm:gap-2 rounded-[10px] px-3 py-3 sm:py-[14px]"
                  style={{
                    background: 'var(--color-s3)',
                    border: `1px solid ${active ? 'rgba(0,229,204,0.3)' : 'var(--color-card-border)'}`,
                    opacity: allowed ? 1 : 0.5,
                  }}>
                  <div style={{
                    fontFamily: '"IBM Plex Mono",monospace', fontSize: 12, fontWeight: 700,
                    color: active ? '#00e5cc' : 'var(--color-tx3)',
                  }}>
                    {pair}
                  </div>
                  <div className="flex flex-col items-center gap-1">
                    <Toggle checked={active} disabled={!allowed}
                      onChange={v => {
                        if (!allowed) return
                        const updated = { ...activePairs, [pair]: v }
                        setActivePairs(updated)
                        patch({ active_pairs: updated })
                      }}
                    />
                    {!allowed && (
                      <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 9, color: 'var(--color-tx3)' }}>
                        UPGRADE
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
          {maxPairs === 0 && (
            <div className="mt-4 px-3 py-2 rounded-lg font-mono text-[10px] text-center"
              style={{ background: 'rgba(240,180,41,0.07)', color: '#f0b429', border: '1px solid rgba(240,180,41,0.15)' }}>
              Upgrade to STARTER or above to activate trading pairs
            </div>
          )}
        </div>
      )}

      {/* ── MT5 ── */}
      {tab === 'mt5' && (
        <div style={CARD}>
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
                width: 36, height: 36, borderRadius: 8, background: 'rgba(0,229,204,0.1)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontFamily: '"IBM Plex Mono",monospace', fontSize: 11, color: '#00e5cc',
              }}>
                MT5
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 13, fontWeight: 700, color: 'var(--color-tx)' }}>
                  {acc.login}
                </div>
                <div style={{ fontSize: 11, color: 'var(--color-tx3)' }}>
                  {acc.server}{acc.label ? ` · ${acc.label}` : ''}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: acc.active ? '#00e596' : '#888', display: 'inline-block' }} />
                <span style={{ fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: acc.active ? '#00e5cc' : 'var(--color-tx3)' }}>
                  {acc.active ? 'BOUND' : 'INACTIVE'}
                </span>
                <button
                  onClick={() => {
                    const updated = mt5Accounts.filter((_, j) => j !== i)
                    setMt5Accounts(updated)
                    patch({ mt5_accounts: updated })
                  }}
                  className="font-mono text-[10px] font-bold tracking-widest px-3 py-1.5 rounded-lg cursor-pointer transition-all"
                  style={{ background: 'rgba(255,61,90,0.1)', color: '#ff3d5a', border: '1px solid rgba(255,61,90,0.2)' }}>
                  UNBIND
                </button>
              </div>
            </div>
          ))}

          {showBindForm ? (
            <BindMt5Form
              onSave={acc => {
                const updated = [...mt5Accounts, acc]
                setMt5Accounts(updated)
                patch({ mt5_accounts: updated })
                setShowBindForm(false)
              }}
              onCancel={() => setShowBindForm(false)}
            />
          ) : mt5Accounts.length < maxMt5 ? (
            <button
              onClick={() => setShowBindForm(true)}
              className="font-mono text-[11px] font-bold tracking-widest px-[18px] py-[9px] rounded-lg cursor-pointer transition-all w-full flex justify-center"
              style={{ background: 'var(--color-s3)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}
              onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.09)' }}
              onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'var(--color-s3)' }}>
              + BIND NEW MT5 ACCOUNT
            </button>
          ) : (
            <div className="font-mono text-[10px] text-center py-2" style={{ color: 'var(--color-tx3)' }}>
              Account limit reached. Upgrade to bind more accounts.
            </div>
          )}

          <div style={{
            marginTop: 12, padding: '10px 14px', background: 'var(--color-s3)',
            borderRadius: 8, fontFamily: '"IBM Plex Mono",monospace', fontSize: 10, color: 'var(--color-tx3)',
          }}>
            ⚠ MT5 accounts can only be bound or unbound from this web interface, not via Telegram.
          </div>
        </div>
      )}

      {/* ── TELEGRAM ── */}
      {tab === 'telegram' && <TelegramTab planIdx={planIdx} botUsername={(settings as any)?.telegram_bot_username} />}

      {/* ── NOTIFICATIONS ── */}
      {tab === 'notifications' && (() => {
        const rows = [
          { key: 'signal_alerts',       l: 'Signal alerts (Telegram)',       s: 'Instant message when a new signal is generated'       },
          { key: 'trade_execution',     l: 'Trade execution confirmations',  s: 'When a trade is placed or closed by the bot'          },
          { key: 'daily_pnl',           l: 'Daily P&L summary',              s: 'End-of-day summary sent at 22:00 UTC'                 },
          { key: 'drawdown_warning',    l: 'Drawdown warnings',              s: 'Alert when account drawdown exceeds 10%'              },
          { key: 'news_reminder',       l: 'News event reminders',           s: '30 minutes before high-impact economic events',       },
          { key: 'email_notifications', l: 'Email notifications',            s: 'Daily summary and trade reports to your email'        },
          { key: 'push_notifications',  l: 'Push notifications (mobile)',    s: `Requires mobile app${!can('mobile_app') ? ' · Upgrade to TRADER+' : ''}` },
        ]
        return (
          <div style={CARD}>
            <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
              Notification Preferences
            </div>
            {rows.map(n => {
              const disabled = n.key === 'push_notifications' && !can('mobile_app')
              return (
                <RowItem key={n.key} label={n.l} sub={n.s} el={
                  <Toggle
                    checked={!!notifPrefs[n.key]}
                    disabled={disabled}
                    onChange={v => {
                      const updated = { ...notifPrefs, [n.key]: v }
                      setNotifPrefs(updated)
                      patch({ notification_prefs: updated })
                    }}
                  />
                } />
              )
            })}
          </div>
        )
      })()}

    </div>
  )
}
