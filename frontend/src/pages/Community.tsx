import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Stats {
  members: number
  signal_drops: number
  result_drops: number
  conversion_rate: number
  active_channels: number
}

interface Drop {
  id: string
  pair: string
  direction: string
  pnl_r: number
  created_at: string
}

interface Channel {
  id: number
  name: string
  chat_id: string
  channel_type: string
  description: string
  is_active: boolean
  member_count: number
  created_at: string
}

// ─── Design tokens ────────────────────────────────────────────────────────────

const CARD: React.CSSProperties = {
  background: 'var(--color-s2)',
  border: '1px solid var(--color-card-border)',
  borderRadius: 14,
  padding: 20,
}

const LABEL: React.CSSProperties = {
  display: 'block',
  fontFamily: '"IBM Plex Mono",monospace',
  fontSize: 10,
  letterSpacing: 1,
  color: 'var(--color-tx3)',
  marginBottom: 6,
  textTransform: 'uppercase',
}

const INPUT: React.CSSProperties = {
  width: '100%',
  background: 'var(--color-s3)',
  border: '1px solid var(--color-input-border)',
  borderRadius: 8,
  padding: '9px 12px',
  color: 'var(--color-tx)',
  fontFamily: 'Figtree, sans-serif',
  fontSize: 13,
  outline: 'none',
}

// ─── Small helpers ────────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, string> = {
  signals:   '#4f8ef7',
  community: '#00e5cc',
  admin:     '#8b5cf6',
  general:   '#f0b429',
}

function TypeBadge({ type }: { type: string }) {
  const c = TYPE_COLORS[type] ?? '#8899b4'
  return (
    <span className="font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest"
      style={{ background: `${c}20`, color: c, border: `1px solid ${c}35` }}>
      {type.toUpperCase()}
    </span>
  )
}

function Feedback({ msg, ok, onClose }: { msg: string; ok: boolean; onClose(): void }) {
  const c = ok ? '#00e5cc' : '#ff3d5a'
  return (
    <div className="flex items-center justify-between px-4 py-3 rounded-xl text-xs font-mono"
      style={{ background: `${c}10`, border: `1px solid ${c}30`, color: c }}>
      <span>{ok ? '✓' : '✗'} {msg}</span>
      <button onClick={onClose} className="ml-4 opacity-50 hover:opacity-100">✕</button>
    </div>
  )
}

// ─── Add Channel Modal ────────────────────────────────────────────────────────

function AddChannelModal({ onClose, onAdded }: { onClose(): void; onAdded(): void }) {
  const [form, setForm] = useState({ name: '', chat_id: '', channel_type: 'community', description: '' })
  const [err, setErr] = useState('')

  const create = useMutation({
    mutationFn: () => api.post('/community/channels', form).then(r => r.data),
    onSuccess: () => { onAdded(); onClose() },
    onError: (e: any) => setErr(e.response?.data?.detail ?? 'Failed to add channel'),
  })

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm(p => ({ ...p, [k]: e.target.value }))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.6)' }}>
      <div style={{ ...CARD, width: '100%', maxWidth: 480 }} className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-tx">Add Telegram Channel</h3>
          <button onClick={onClose} className="text-tx3 hover:text-tx text-lg">✕</button>
        </div>

        {err && <Feedback msg={err} ok={false} onClose={() => setErr('')} />}

        <div>
          <label style={LABEL}>Channel Name</label>
          <input style={INPUT} value={form.name} onChange={set('name')} placeholder="My Signals Channel"
            onFocus={e => (e.target.style.borderColor = '#00e5cc')}
            onBlur={e => (e.target.style.borderColor = 'var(--color-input-border)')} />
        </div>
        <div>
          <label style={LABEL}>Chat ID</label>
          <input style={INPUT} value={form.chat_id} onChange={set('chat_id')} placeholder="-1001234567890"
            onFocus={e => (e.target.style.borderColor = '#00e5cc')}
            onBlur={e => (e.target.style.borderColor = 'var(--color-input-border)')} />
          <div className="font-mono text-[10px] mt-1" style={{ color: 'var(--color-tx3)' }}>
            Add the bot as channel admin first, then get the chat ID from @userinfobot or getUpdates API.
          </div>
        </div>
        <div>
          <label style={LABEL}>Type</label>
          <select style={{ ...INPUT, cursor: 'pointer' }} value={form.channel_type} onChange={set('channel_type')}>
            <option value="signals">Signals — new trade signals</option>
            <option value="community">Community — results & updates</option>
            <option value="admin">Admin — alerts & errors</option>
            <option value="general">General — announcements</option>
          </select>
        </div>
        <div>
          <label style={LABEL}>Description (optional)</label>
          <input style={INPUT} value={form.description} onChange={set('description')} placeholder="e.g. VIP signals group"
            onFocus={e => (e.target.style.borderColor = '#00e5cc')}
            onBlur={e => (e.target.style.borderColor = 'var(--color-input-border)')} />
        </div>

        <div className="flex gap-3 pt-1">
          <button
            onClick={() => create.mutate()}
            disabled={create.isPending || !form.chat_id.trim()}
            className="flex-1 py-2.5 rounded-xl text-xs font-bold font-mono tracking-widest transition-colors disabled:opacity-50"
            style={{ background: '#00e5cc', color: '#000', border: 'none' }}>
            {create.isPending ? 'Verifying…' : 'Add Channel'}
          </button>
          <button onClick={onClose}
            className="px-5 py-2.5 rounded-xl text-xs font-mono transition-colors"
            style={{ background: 'var(--color-s3)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Channel Row ──────────────────────────────────────────────────────────────

function ChannelRow({ ch, onRefresh }: { ch: Channel; onRefresh(): void }) {
  const qc = useQueryClient()
  const [invite, setInvite] = useState('')
  const [copied, setCopied] = useState(false)

  const del = useMutation({
    mutationFn: () => api.delete(`/community/channels/${ch.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['community-channels'] }),
  })

  const genLink = useMutation({
    mutationFn: () => api.post(`/community/channels/${ch.id}/invite-link`).then(r => r.data),
    onSuccess: (d) => setInvite(d.invite_link),
  })

  const refreshCount = useMutation({
    mutationFn: () => api.post(`/community/channels/${ch.id}/refresh-count`).then(r => r.data),
    onSuccess: () => { onRefresh(); qc.invalidateQueries({ queryKey: ['community-channels'] }) },
  })

  const copyLink = () => {
    navigator.clipboard.writeText(invite)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div style={CARD} className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-semibold text-tx text-sm truncate">{ch.name}</span>
            <TypeBadge type={ch.channel_type} />
            {!ch.is_active && (
              <span className="font-mono text-[9px] px-1.5 py-0.5 rounded"
                style={{ background: 'rgba(255,61,90,0.1)', color: '#ff3d5a', border: '1px solid rgba(255,61,90,0.2)' }}>
                INACTIVE
              </span>
            )}
          </div>
          <div className="font-mono text-[10px]" style={{ color: 'var(--color-tx3)' }}>
            Chat ID: <span style={{ color: 'var(--color-tx2)' }}>{ch.chat_id}</span>
          </div>
          {ch.description && (
            <div className="text-xs mt-1" style={{ color: 'var(--color-tx3)' }}>{ch.description}</div>
          )}
        </div>
        <div className="text-right shrink-0">
          <div className="font-mono font-bold text-lg" style={{ color: 'var(--color-cy)' }}>
            {ch.member_count.toLocaleString()}
          </div>
          <div className="font-mono text-[9px]" style={{ color: 'var(--color-tx3)' }}>members</div>
        </div>
      </div>

      {invite && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg"
          style={{ background: 'var(--color-s3)', border: '1px solid var(--color-card-border)' }}>
          <span className="font-mono text-[10px] flex-1 truncate" style={{ color: 'var(--color-cy)' }}>{invite}</span>
          <button onClick={copyLink}
            className="font-mono text-[10px] px-2 py-0.5 rounded transition-colors"
            style={{ background: copied ? '#00e5cc20' : 'var(--color-s2)', color: copied ? '#00e5cc' : 'var(--color-tx2)',
              border: '1px solid var(--color-card-border)' }}>
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button onClick={() => genLink.mutate()} disabled={genLink.isPending}
          className="font-mono text-[10px] px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          style={{ background: 'rgba(0,229,204,0.08)', color: '#00e5cc', border: '1px solid rgba(0,229,204,0.2)' }}>
          {genLink.isPending ? 'Generating…' : '🔗 Invite Link'}
        </button>
        <button onClick={() => refreshCount.mutate()} disabled={refreshCount.isPending}
          className="font-mono text-[10px] px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          style={{ background: 'var(--color-s3)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}>
          {refreshCount.isPending ? 'Refreshing…' : '↻ Refresh Count'}
        </button>
        <button onClick={() => { if (confirm(`Remove "${ch.name}"?`)) del.mutate() }} disabled={del.isPending}
          className="font-mono text-[10px] px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50 ml-auto"
          style={{ background: 'rgba(255,61,90,0.07)', color: '#ff3d5a', border: '1px solid rgba(255,61,90,0.15)' }}>
          Remove
        </button>
      </div>
    </div>
  )
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export default function Community() {
  const qc = useQueryClient()
  const [showAdd, setShowAdd] = useState(false)
  const [dropMsg, setDropMsg] = useState<{ ok: boolean; msg: string } | null>(null)

  const { data: stats } = useQuery<Stats>({
    queryKey: ['community-stats'],
    queryFn: () => api.get('/community/stats').then(r => r.data),
    refetchInterval: 60_000,
  })

  const { data: drops = [] } = useQuery<Drop[]>({
    queryKey: ['community-drops'],
    queryFn: () => api.get('/community/drops').then(r => r.data),
  })

  const { data: channels = [], refetch: refetchChannels } = useQuery<Channel[]>({
    queryKey: ['community-channels'],
    queryFn: () => api.get('/community/channels').then(r => r.data),
  })

  const notify = (ok: boolean, msg: string) => {
    setDropMsg({ ok, msg })
    setTimeout(() => setDropMsg(null), 4000)
  }

  const dropSignal = useMutation({
    mutationFn: () => api.post('/community/drop-signal').then(r => r.data),
    onSuccess: (d) => {
      notify(true, `Signal dropped: ${d.pair} ${d.direction}`)
      qc.invalidateQueries({ queryKey: ['community-stats'] })
      qc.invalidateQueries({ queryKey: ['community-drops'] })
    },
    onError: (e: any) => notify(false, e.response?.data?.detail ?? 'Failed to drop signal'),
  })

  const dropResult = useMutation({
    mutationFn: () => api.post('/community/drop-result').then(r => r.data),
    onSuccess: (d) => {
      notify(true, `Result dropped: ${d.pair} ${d.pnl_r > 0 ? '+' : ''}${d.pnl_r?.toFixed(1)}R`)
      qc.invalidateQueries({ queryKey: ['community-stats'] })
      qc.invalidateQueries({ queryKey: ['community-drops'] })
    },
    onError: (e: any) => notify(false, e.response?.data?.detail ?? 'Failed to drop result'),
  })

  return (
    <div className="space-y-6">

      {showAdd && (
        <AddChannelModal
          onClose={() => setShowAdd(false)}
          onAdded={() => qc.invalidateQueries({ queryKey: ['community-channels'] })}
        />
      )}

      {/* Header */}
      <div>
        <h1 className="text-xl font-bold font-head text-tx">Community</h1>
        <p className="text-sm mt-0.5" style={{ color: 'var(--color-tx2)' }}>
          Manage Telegram channels, drop signals and results to your community
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {[
          { label: 'Community Members', value: stats?.members ?? '—' },
          { label: 'Active Channels',   value: stats?.active_channels ?? '—' },
          { label: 'Signal Drops',      value: stats?.signal_drops ?? '—' },
          { label: 'Result Drops',      value: stats?.result_drops ?? '—' },
          { label: 'Conversion Rate',   value: stats ? `${stats.conversion_rate}%` : '—' },
        ].map(s => (
          <div key={s.label} style={CARD}>
            <div className="font-mono text-[9px] tracking-widest uppercase mb-2" style={{ color: 'var(--color-tx3)' }}>
              {s.label}
            </div>
            <div className="text-2xl font-bold font-head" style={{ color: 'var(--color-cy)' }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Two-column layout: drops left, recent history right */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Manual drops */}
        <div style={CARD} className="space-y-4">
          <div>
            <div className="font-mono text-[10px] tracking-[2px] uppercase mb-1" style={{ color: 'var(--color-tx3)' }}>
              Manual Drops
            </div>
            <p className="text-xs" style={{ color: 'var(--color-tx2)' }}>
              Push the latest pending signal or most recent closed trade result to your configured Telegram channels.
            </p>
          </div>

          {dropMsg && <Feedback msg={dropMsg.msg} ok={dropMsg.ok} onClose={() => setDropMsg(null)} />}

          {/* Signal drop preview */}
          <div className="rounded-xl p-4 space-y-1"
            style={{ background: 'var(--color-s3)', border: '1px solid var(--color-card-border)' }}>
            <div className="font-mono text-[10px] uppercase tracking-widest mb-2" style={{ color: 'var(--color-tx3)' }}>
              Signal Drop Preview
            </div>
            <div className="font-mono text-xs space-y-0.5" style={{ color: 'var(--color-tx2)' }}>
              <div>📊 <b style={{ color: 'var(--color-tx)' }}>NEW SIGNAL</b></div>
              <div>Pair:&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; EUR/USD  BUY</div>
              <div>Entry:&nbsp;&nbsp;&nbsp;&nbsp;<b style={{ color: 'var(--color-cy)' }}>1.0840</b></div>
              <div>SL / TP:&nbsp;&nbsp; 1.0800 / 1.0910</div>
              <div>AI conf:&nbsp;&nbsp; 78%</div>
              <div>Regime:&nbsp;&nbsp;&nbsp; 📈 Trending</div>
            </div>
          </div>

          <button
            onClick={() => dropSignal.mutate()}
            disabled={dropSignal.isPending}
            className="w-full py-2.5 rounded-xl font-mono text-xs font-bold tracking-widest transition-colors disabled:opacity-50"
            style={{ background: '#00e5cc', color: '#000', border: 'none' }}>
            {dropSignal.isPending ? 'Dropping…' : '📡 Drop Signal to Telegram'}
          </button>

          {/* Result drop preview */}
          <div className="rounded-xl p-4 space-y-1"
            style={{ background: 'var(--color-s3)', border: '1px solid var(--color-card-border)' }}>
            <div className="font-mono text-[10px] uppercase tracking-widest mb-2" style={{ color: 'var(--color-tx3)' }}>
              Result Drop Preview
            </div>
            <div className="font-mono text-xs space-y-0.5" style={{ color: 'var(--color-tx2)' }}>
              <div>✅ <b style={{ color: 'var(--color-tx)' }}>Trade Closed</b></div>
              <div>Pair:&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; EUR/USD  BUY</div>
              <div>Result:&nbsp;&nbsp;&nbsp; <b style={{ color: '#4ade80' }}>+2.1R</b></div>
              <div>Regime:&nbsp;&nbsp;&nbsp; 📈 Trending</div>
              <div>AI conf:&nbsp;&nbsp; 78%</div>
            </div>
          </div>

          <button
            onClick={() => dropResult.mutate()}
            disabled={dropResult.isPending}
            className="w-full py-2.5 rounded-xl font-mono text-xs font-bold tracking-widest transition-colors disabled:opacity-50"
            style={{ background: 'rgba(0,229,204,0.08)', color: '#00e5cc', border: '1px solid rgba(0,229,204,0.25)' }}>
            {dropResult.isPending ? 'Dropping…' : '📬 Drop Result to Telegram'}
          </button>

          <div className="font-mono text-[10px] pt-1" style={{ color: 'var(--color-tx3)' }}>
            ⓘ Results are also dropped automatically when trades close (if enabled in Admin → Config).
          </div>
        </div>

        {/* Recent drops */}
        <div style={CARD}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-4" style={{ color: 'var(--color-tx3)' }}>
            Recent Closed Trades
          </div>
          {drops.length === 0 ? (
            <div className="text-sm text-center py-10" style={{ color: 'var(--color-tx3)' }}>No closed trades yet.</div>
          ) : (
            <div className="space-y-0 divide-y" style={{ borderColor: 'var(--color-card-border)' }}>
              {drops.map(d => (
                <div key={d.id} className="flex items-center justify-between py-3">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-sm" style={{ color: 'var(--color-tx)' }}>{d.pair}</span>
                    <span className="font-mono text-[9px] font-bold px-1.5 py-0.5 rounded"
                      style={{
                        background: d.direction === 'BUY' ? 'rgba(0,229,204,0.1)' : 'rgba(255,61,90,0.1)',
                        color: d.direction === 'BUY' ? '#00e5cc' : '#ff3d5a',
                        border: `1px solid ${d.direction === 'BUY' ? 'rgba(0,229,204,0.2)' : 'rgba(255,61,90,0.2)'}`,
                      }}>
                      {d.direction}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="font-mono font-bold text-sm"
                      style={{ color: d.pnl_r > 0 ? '#4ade80' : '#ff3d5a' }}>
                      {d.pnl_r > 0 ? '+' : ''}{d.pnl_r?.toFixed(1)}R
                    </span>
                    <span className="font-mono text-[10px]" style={{ color: 'var(--color-tx3)' }}>{d.created_at}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Channels section */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold font-head text-tx">Telegram Channels</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--color-tx2)' }}>
              Manage channels the bot is connected to. Generate invite links and track member counts.
            </p>
          </div>
          <button
            onClick={() => setShowAdd(true)}
            className="font-mono text-xs font-bold tracking-widest px-4 py-2 rounded-xl transition-colors"
            style={{ background: '#00e5cc', color: '#000', border: 'none' }}>
            + Add Channel
          </button>
        </div>

        {channels.length === 0 ? (
          <div style={CARD} className="text-center py-12">
            <div className="text-3xl mb-3">📡</div>
            <div className="font-semibold text-tx mb-1">No channels yet</div>
            <div className="text-xs mb-4" style={{ color: 'var(--color-tx2)' }}>
              Add your Telegram channel or group to start managing members and drops.
            </div>
            <button
              onClick={() => setShowAdd(true)}
              className="font-mono text-xs font-bold tracking-widest px-5 py-2.5 rounded-xl transition-colors"
              style={{ background: '#00e5cc', color: '#000', border: 'none' }}>
              Add Your First Channel
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {channels.map(ch => (
              <ChannelRow key={ch.id} ch={ch} onRefresh={() => refetchChannels()} />
            ))}
          </div>
        )}

        {/* How-to guide */}
        <div style={{ ...CARD, marginTop: 16 }}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-3" style={{ color: 'var(--color-tx3)' }}>
            How to add a channel
          </div>
          <ol className="space-y-2 font-mono text-xs" style={{ color: 'var(--color-tx2)' }}>
            {[
              'Create a Telegram channel or group (or use an existing one)',
              'Search for your bot by username and add it to the channel',
              'Promote the bot to Admin with "Post Messages" permission',
              'Get the chat ID: send a message in the channel, then call the Telegram getUpdates API',
              'Paste the chat ID in the form above — the bot will verify it automatically',
              'Use "Invite Link" to generate a shareable join link for your users',
            ].map((step, i) => (
              <li key={i} className="flex gap-3">
                <span style={{ color: 'var(--color-cy)' }} className="shrink-0">{i + 1}.</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>

    </div>
  )
}
