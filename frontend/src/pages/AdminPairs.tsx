import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

// ── Types ─────────────────────────────────────────────────────────────────────

type SessionWindow = [number, number]

interface ManagedPair {
  symbol:          string
  display_name:    string
  is_active:       boolean
  session_windows: SessionWindow[] | null
  added_at:        string | null
  last_tested_at:  string | null
  test_result:     TestResult | null
  notes:           string | null
}

interface GateDetail {
  val:       number
  pass:      boolean
  threshold: string
}

interface TestResult {
  status:         string
  symbol?:        string
  trades?:        number
  wins?:          number
  losses?:        number
  win_rate?:      number
  net_r?:         number
  avg_r?:         number
  max_dd_r?:      number
  h4_bars?:       number
  m15_bars?:      number
  all_gates_pass?: boolean
  gates?:         Record<string, GateDetail>
  error?:         string
  last_tested_at?: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(s: string | null) {
  if (!s) return '—'
  return new Date(s).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function fmtWindows(w: SessionWindow[] | null) {
  if (!w || w.length === 0) return 'All hours'
  return w.map(([s, e]) => `${String(s).padStart(2, '0')}–${String(e).padStart(2, '0')}h`).join(' · ')
}

function parseWindows(raw: string): SessionWindow[] | null {
  if (!raw.trim()) return null
  const parts = raw.split(',').map(s => s.trim()).filter(Boolean)
  const result: SessionWindow[] = []
  for (const p of parts) {
    const m = p.match(/^(\d{1,2})[–\-](\d{1,2})/)
    if (!m) throw new Error(`Invalid window "${p}" — use format: 7-17, 0-1, 13-15`)
    const [, a, b] = m.map(Number) as [string, number, number]
    if (a >= b) throw new Error(`Start must be < end in "${p}"`)
    result.push([a, b])
  }
  return result.length ? result : null
}

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, { label: string; bg: string; color: string; border: string }> = {
    pass:              { label: 'PASS',       bg: 'rgba(0,229,150,0.1)',   color: '#00e596', border: 'rgba(0,229,150,0.25)' },
    fail:              { label: 'FAIL',       bg: 'rgba(255,61,90,0.1)',   color: '#ff3d5a', border: 'rgba(255,61,90,0.25)' },
    insufficient_data: { label: 'LOW DATA',  bg: 'rgba(240,180,41,0.1)',  color: '#f0b429', border: 'rgba(240,180,41,0.25)' },
    running:           { label: 'RUNNING…',  bg: 'rgba(79,142,247,0.1)',  color: '#4f8ef7', border: 'rgba(79,142,247,0.25)' },
    error:             { label: 'ERROR',     bg: 'rgba(255,61,90,0.1)',   color: '#ff3d5a', border: 'rgba(255,61,90,0.25)' },
    never_tested:      { label: 'UNTESTED',  bg: 'rgba(255,255,255,0.05)', color: 'var(--color-tx3)', border: 'rgba(255,255,255,0.1)' },
  }
  const c = cfg[status] ?? cfg['never_tested']
  return (
    <span className="inline-flex items-center font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest"
      style={{ background: c.bg, color: c.color, border: `1px solid ${c.border}` }}>
      {c.label}
    </span>
  )
}

function GateRow({ label, val, pass, threshold }: { label: string; val: number | string; pass: boolean; threshold: string }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="font-mono text-[11px]" style={{ color: 'var(--color-tx2)' }}>{label}</span>
      <div className="flex items-center gap-2">
        <span className="font-mono text-[11px]" style={{ color: pass ? '#00e5cc' : '#ff3d5a' }}>{String(val)}</span>
        <span className="font-mono text-[9px]" style={{ color: 'var(--color-tx3)' }}>{threshold}</span>
        <span style={{ color: pass ? '#00e596' : '#ff3d5a', fontSize: 13 }}>{pass ? '✓' : '✗'}</span>
      </div>
    </div>
  )
}

// ── Add Pair Modal ────────────────────────────────────────────────────────────

function AddPairModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [symbol,   setSymbol]   = useState('')
  const [name,     setName]     = useState('')
  const [sessions, setSessions] = useState('')
  const [notes,    setNotes]    = useState('')
  const [err,      setErr]      = useState<string | null>(null)

  const add = useMutation({
    mutationFn: async () => {
      let windows: SessionWindow[] | null = null
      if (sessions.trim()) {
        windows = parseWindows(sessions) // throws on bad format
      }
      const res = await api.post('/admin/pairs', {
        symbol:          symbol.trim().toUpperCase(),
        display_name:    name.trim() || symbol.trim().toUpperCase(),
        session_windows: windows,
        notes:           notes.trim(),
      })
      return res.data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['managed-pairs'] })
      onClose()
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.detail ?? e?.message ?? 'Failed to add pair')
    },
  })

  const inputCls = "w-full bg-s2 border border-s3 rounded-lg px-3 py-2 text-sm text-tx focus:outline-none focus:border-cy/50 transition-colors font-mono placeholder:opacity-40"

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }}>
      <div className="w-full max-w-md rounded-2xl p-6 space-y-5"
        style={{ background: 'var(--color-s1)', border: '1px solid var(--color-card-border)' }}>

        <div className="flex items-center justify-between">
          <h2 className="font-head font-bold text-base" style={{ color: 'var(--color-tx)' }}>Add New Pair</h2>
          <button onClick={onClose} className="text-tx2 hover:text-tx transition-colors text-lg leading-none">✕</button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block font-mono text-[10px] uppercase tracking-widest mb-1.5" style={{ color: 'var(--color-tx3)' }}>
              Symbol <span className="text-rd">*</span>
            </label>
            <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())}
              placeholder="e.g. GBPJPY"
              className={inputCls} maxLength={12} />
          </div>

          <div>
            <label className="block font-mono text-[10px] uppercase tracking-widest mb-1.5" style={{ color: 'var(--color-tx3)' }}>
              Display Name
            </label>
            <input value={name} onChange={e => setName(e.target.value)}
              placeholder="e.g. British Pound / Japanese Yen"
              className={inputCls} />
          </div>

          <div>
            <label className="block font-mono text-[10px] uppercase tracking-widest mb-1.5" style={{ color: 'var(--color-tx3)' }}>
              ICT Session Windows (UTC) — comma separated
            </label>
            <input value={sessions} onChange={e => setSessions(e.target.value)}
              placeholder="e.g. 7-10, 13-16  (blank = all hours)"
              className={inputCls} />
            <p className="mt-1 font-mono text-[10px]" style={{ color: 'var(--color-tx3)' }}>
              Format: start-end pairs, e.g. <span style={{ color: 'var(--color-cy)' }}>7-11, 13-17</span>
            </p>
          </div>

          <div>
            <label className="block font-mono text-[10px] uppercase tracking-widest mb-1.5" style={{ color: 'var(--color-tx3)' }}>
              Notes (optional)
            </label>
            <input value={notes} onChange={e => setNotes(e.target.value)}
              placeholder="Any notes about this pair"
              className={inputCls} />
          </div>
        </div>

        {err && <p className="font-mono text-xs" style={{ color: '#ff3d5a' }}>{err}</p>}

        <div className="flex gap-3 pt-1">
          <button onClick={onClose}
            className="flex-1 py-2 rounded-lg text-sm font-semibold transition-colors"
            style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)', color: 'var(--color-tx2)' }}>
            Cancel
          </button>
          <button
            onClick={() => { setErr(null); add.mutate() }}
            disabled={!symbol.trim() || add.isPending}
            className="flex-1 py-2 rounded-lg text-sm font-semibold transition-colors disabled:opacity-40"
            style={{ background: '#00e5cc', color: '#0a0e17' }}>
            {add.isPending ? 'Adding…' : 'Add Pair'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Edit Sessions Modal ───────────────────────────────────────────────────────

function EditSessionsModal({ pair, onClose }: { pair: ManagedPair; onClose: () => void }) {
  const qc = useQueryClient()
  const [sessions, setSessions] = useState(
    pair.session_windows ? pair.session_windows.map(([s, e]) => `${s}-${e}`).join(', ') : ''
  )
  const [notes, setNotes] = useState(pair.notes ?? '')
  const [err,   setErr]   = useState<string | null>(null)

  const save = useMutation({
    mutationFn: async () => {
      const windows = sessions.trim() ? parseWindows(sessions) : null
      await api.patch(`/admin/pairs/${pair.symbol}`, {
        session_windows: windows,
        notes: notes.trim() || null,
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['managed-pairs'] })
      onClose()
    },
    onError: (e: any) => setErr(e?.response?.data?.detail ?? e?.message ?? 'Save failed'),
  })

  const inputCls = "w-full bg-s2 border border-s3 rounded-lg px-3 py-2 text-sm text-tx focus:outline-none focus:border-cy/50 transition-colors font-mono placeholder:opacity-40"

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }}>
      <div className="w-full max-w-md rounded-2xl p-6 space-y-5"
        style={{ background: 'var(--color-s1)', border: '1px solid var(--color-card-border)' }}>
        <div className="flex items-center justify-between">
          <h2 className="font-head font-bold text-base" style={{ color: 'var(--color-tx)' }}>
            Edit {pair.symbol} Sessions
          </h2>
          <button onClick={onClose} className="text-tx2 hover:text-tx transition-colors text-lg">✕</button>
        </div>

        <div>
          <label className="block font-mono text-[10px] uppercase tracking-widest mb-1.5" style={{ color: 'var(--color-tx3)' }}>
            ICT Session Windows (UTC)
          </label>
          <input value={sessions} onChange={e => setSessions(e.target.value)}
            placeholder="7-11, 13-17  (blank = all hours)"
            className={inputCls} />
        </div>
        <div>
          <label className="block font-mono text-[10px] uppercase tracking-widest mb-1.5" style={{ color: 'var(--color-tx3)' }}>Notes</label>
          <input value={notes} onChange={e => setNotes(e.target.value)} className={inputCls} />
        </div>

        {err && <p className="font-mono text-xs" style={{ color: '#ff3d5a' }}>{err}</p>}

        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 py-2 rounded-lg text-sm font-semibold"
            style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)', color: 'var(--color-tx2)' }}>
            Cancel
          </button>
          <button onClick={() => { setErr(null); save.mutate() }} disabled={save.isPending}
            className="flex-1 py-2 rounded-lg text-sm font-semibold disabled:opacity-40"
            style={{ background: '#00e5cc', color: '#0a0e17' }}>
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Pair Card ─────────────────────────────────────────────────────────────────

function PairCard({ pair }: { pair: ManagedPair }) {
  const qc = useQueryClient()
  const [showEdit, setShowEdit]       = useState(false)
  const [expanded, setExpanded]       = useState(false)

  const testStatus = pair.test_result?.status ?? 'never_tested'

  const runTest = useMutation({
    mutationFn: () => api.post(`/admin/pairs/${pair.symbol}/test`).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['managed-pairs'] }),
  })

  const toggleActive = useMutation({
    mutationFn: () => api.patch(`/admin/pairs/${pair.symbol}`, { is_active: !pair.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['managed-pairs'] }),
  })

  const deletePair = useMutation({
    mutationFn: () => api.delete(`/admin/pairs/${pair.symbol}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['managed-pairs'] }),
  })

  const tr = pair.test_result

  return (
    <>
      {showEdit && <EditSessionsModal pair={pair} onClose={() => setShowEdit(false)} />}

      <div className="rounded-[14px] p-5 space-y-4"
        style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>

        {/* Header row */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-head font-bold text-[15px]" style={{ color: 'var(--color-tx)' }}>{pair.symbol}</span>
                <span className={`inline-flex items-center font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest ${pair.is_active ? 'text-green-400 bg-green-400/10 border border-green-400/25' : 'text-tx2 bg-white/5 border border-white/10'}`}>
                  {pair.is_active ? 'ACTIVE' : 'INACTIVE'}
                </span>
              </div>
              <p className="font-mono text-[11px] mt-0.5" style={{ color: 'var(--color-tx3)' }}>
                {pair.display_name}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <StatusBadge status={testStatus} />
          </div>
        </div>

        {/* Sessions */}
        <div className="rounded-lg px-3 py-2 flex items-center justify-between"
          style={{ background: 'rgba(0,229,204,0.05)', border: '1px solid rgba(0,229,204,0.1)' }}>
          <div>
            <p className="font-mono text-[9px] uppercase tracking-widest mb-0.5" style={{ color: 'var(--color-tx3)' }}>ICT Sessions (UTC)</p>
            <p className="font-mono text-[11px]" style={{ color: '#00e5cc' }}>{fmtWindows(pair.session_windows)}</p>
          </div>
          <button onClick={() => setShowEdit(true)}
            className="font-mono text-[10px] px-2 py-1 rounded transition-colors hover:text-cy"
            style={{ color: 'var(--color-tx3)', border: '1px solid var(--color-card-border)' }}>
            edit
          </button>
        </div>

        {/* Last test quick stats */}
        {tr && tr.status !== 'never_tested' && tr.status !== 'running' && tr.trades != null && (
          <div className="grid grid-cols-4 gap-2">
            {[
              { l: 'Trades', v: String(tr.trades ?? '—') },
              { l: 'Win Rate', v: tr.win_rate != null ? `${tr.win_rate}%` : '—' },
              { l: 'Avg R', v: tr.avg_r != null ? `${tr.avg_r >= 0 ? '+' : ''}${tr.avg_r?.toFixed(3)}R` : '—' },
              { l: 'Max DD', v: tr.max_dd_r != null ? `${tr.max_dd_r?.toFixed(1)}R` : '—' },
            ].map(s => (
              <div key={s.l} className="rounded-lg px-2 py-2 text-center"
                style={{ background: 'var(--color-s1)', border: '1px solid var(--color-card-border)' }}>
                <p className="font-mono text-[8px] uppercase tracking-widest mb-1" style={{ color: 'var(--color-tx3)' }}>{s.l}</p>
                <p className="font-mono text-[12px] font-bold" style={{ color: 'var(--color-cy)' }}>{s.v}</p>
              </div>
            ))}
          </div>
        )}

        {/* Expandable gate details */}
        {tr?.gates && (
          <div>
            <button onClick={() => setExpanded(v => !v)}
              className="font-mono text-[10px] transition-colors hover:text-cy w-full text-left flex items-center gap-1"
              style={{ color: 'var(--color-tx3)' }}>
              {expanded ? '▾' : '▸'} Gate breakdown
            </button>
            {expanded && (
              <div className="mt-2 rounded-lg px-3 py-2 space-y-0"
                style={{ background: 'var(--color-s1)', border: '1px solid var(--color-card-border)' }}>
                {Object.entries(tr.gates).map(([k, g]) => (
                  <GateRow key={k}
                    label={k.replace(/_/g, ' ')}
                    val={k === 'win_rate' ? `${g.val}%` : k === 'trade_count' ? g.val : `${g.val}R`}
                    pass={g.pass}
                    threshold={g.threshold}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Error msg */}
        {tr?.status === 'error' && tr.error && (
          <p className="font-mono text-[11px] rounded-lg px-3 py-2"
            style={{ color: '#ff3d5a', background: 'rgba(255,61,90,0.08)', border: '1px solid rgba(255,61,90,0.2)' }}>
            {tr.error}
          </p>
        )}

        {tr?.last_tested_at && (
          <p className="font-mono text-[10px]" style={{ color: 'var(--color-tx3)' }}>
            Last tested: {fmtDate(tr.last_tested_at)}
          </p>
        )}

        {/* Action buttons */}
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => runTest.mutate()}
            disabled={runTest.isPending || testStatus === 'running'}
            className="flex-1 py-2 rounded-lg text-xs font-semibold font-mono transition-colors disabled:opacity-40"
            style={{ background: 'rgba(0,229,204,0.12)', color: '#00e5cc', border: '1px solid rgba(0,229,204,0.25)' }}>
            {runTest.isPending || testStatus === 'running' ? '⏳ Running…' : '▶ Run Backtest'}
          </button>

          <button
            onClick={() => toggleActive.mutate()}
            disabled={toggleActive.isPending}
            className="px-3 py-2 rounded-lg text-xs font-semibold font-mono transition-colors disabled:opacity-40"
            style={{ background: 'var(--color-s1)', border: '1px solid var(--color-card-border)', color: 'var(--color-tx2)' }}>
            {pair.is_active ? 'Disable' : 'Enable'}
          </button>

          <button
            onClick={() => {
              if (confirm(`Delete pair ${pair.symbol}? This cannot be undone.`)) deletePair.mutate()
            }}
            disabled={deletePair.isPending}
            className="px-3 py-2 rounded-lg text-xs font-semibold font-mono transition-colors disabled:opacity-40"
            style={{ background: 'rgba(255,61,90,0.08)', border: '1px solid rgba(255,61,90,0.2)', color: '#ff3d5a' }}>
            Delete
          </button>
        </div>
      </div>
    </>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function AdminPairs() {
  const qc = useQueryClient()
  const [showAdd, setShowAdd] = useState(false)

  const { data: pairs = [], isLoading, isError } = useQuery<ManagedPair[]>({
    queryKey: ['managed-pairs'],
    queryFn:  () => api.get('/admin/pairs').then(r => r.data),
    refetchInterval: 10_000,
  })

  const active   = pairs.filter(p => p.is_active)
  const inactive = pairs.filter(p => !p.is_active)
  const passing  = pairs.filter(p => p.test_result?.all_gates_pass)

  return (
    <>
      {showAdd && <AddPairModal onClose={() => setShowAdd(false)} />}

      <div className="max-w-5xl mx-auto py-8 px-4 space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold" style={{ color: 'var(--color-tx)' }}>Pair Management</h1>
            <p className="text-sm mt-0.5" style={{ color: 'var(--color-tx2)' }}>
              Add pairs, configure ICT session windows, and backtest against historical DB data.
            </p>
          </div>
          <button
            onClick={() => setShowAdd(true)}
            className="px-4 py-2 rounded-lg text-sm font-semibold transition-colors"
            style={{ background: '#00e5cc', color: '#0a0e17' }}>
            + Add Pair
          </button>
        </div>

        {/* Summary */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { l: 'Total Pairs',   v: pairs.length,   c: 'var(--color-tx)' },
            { l: 'Active',        v: active.length,  c: '#00e5cc' },
            { l: 'Gate Passing',  v: passing.length, c: '#00e596' },
          ].map(s => (
            <div key={s.l} className="rounded-[10px] px-4 py-3 flex items-center justify-between"
              style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
              <span className="font-mono text-[10px] uppercase tracking-widest" style={{ color: 'var(--color-tx3)' }}>{s.l}</span>
              <span className="font-head font-bold text-lg" style={{ color: s.c }}>{s.v}</span>
            </div>
          ))}
        </div>

        {/* Pairs grid */}
        {isLoading && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-52 rounded-[14px] animate-pulse" style={{ background: 'var(--color-s2)' }} />
            ))}
          </div>
        )}

        {isError && (
          <div className="rounded-[14px] px-5 py-8 text-center font-mono text-sm"
            style={{ background: 'var(--color-s2)', color: '#ff3d5a', border: '1px solid rgba(255,61,90,0.2)' }}>
            Failed to load pairs — API error
          </div>
        )}

        {!isLoading && !isError && (
          <>
            {active.length > 0 && (
              <div className="space-y-3">
                <p className="font-mono text-[10px] uppercase tracking-[3px]" style={{ color: 'var(--color-tx3)' }}>Active Pairs</p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {active.map(p => <PairCard key={p.symbol} pair={p} />)}
                </div>
              </div>
            )}

            {inactive.length > 0 && (
              <div className="space-y-3">
                <p className="font-mono text-[10px] uppercase tracking-[3px]" style={{ color: 'var(--color-tx3)' }}>Inactive Pairs</p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {inactive.map(p => <PairCard key={p.symbol} pair={p} />)}
                </div>
              </div>
            )}

            {pairs.length === 0 && (
              <div className="rounded-[14px] px-5 py-12 text-center space-y-2"
                style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
                <p className="font-mono text-sm" style={{ color: 'var(--color-tx3)' }}>No pairs yet</p>
                <p className="font-mono text-xs" style={{ color: 'var(--color-tx3)' }}>Click "Add Pair" to add your first trading pair</p>
              </div>
            )}
          </>
        )}

        {/* Info box */}
        <div className="rounded-[14px] px-5 py-4 space-y-2"
          style={{ background: 'var(--color-s1)', border: '1px solid var(--color-card-border)' }}>
          <p className="font-mono text-[10px] uppercase tracking-widest" style={{ color: 'var(--color-tx3)' }}>How it works</p>
          <ul className="space-y-1.5 font-mono text-[11px]" style={{ color: 'var(--color-tx2)' }}>
            <li><span style={{ color: '#00e5cc' }}>1. Add pair</span> — enter symbol + optional ICT session windows (UTC hour ranges)</li>
            <li><span style={{ color: '#00e5cc' }}>2. Upload data</span> — go to Data Management → upload M15 and H4 CSV files for the pair</li>
            <li><span style={{ color: '#00e5cc' }}>3. Run backtest</span> — click "Run Backtest" to test the 4-gate ICT pipeline against your data</li>
            <li><span style={{ color: '#00e5cc' }}>4. Check gates</span> — WR ≥50% · Avg R ≥0.15R · Max DD ≤10R · Trades ≥50 must all pass</li>
            <li><span style={{ color: '#00e5cc' }}>5. Enable</span> — once gates pass, activate the pair for live paper / live trading</li>
          </ul>
        </div>

      </div>
    </>
  )
}
