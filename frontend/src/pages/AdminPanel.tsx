import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

// ─── Types ───────────────────────────────────────────────────────────────────

interface User {
  id: string
  email: string
  plan: string
  is_admin: boolean
  is_paper_mode: boolean
  created_at: string
  trial_expires_at: string | null
}

interface Stats {
  users: {
    total_users: number
    admin_count: number
    new_this_week: number
    new_this_month: number
  }
  plan_distribution: { plan: string; count: number }[]
  signals: {
    total_signals: number
    approved: number
    rejected: number
    pending: number
  }
  trades: {
    total_trades: number
    open_trades: number
  }
  revenue: {
    mrr: number
  }
}

interface AuditEntry {
  id: string
  user_id: string
  email: string
  action: string
  detail: string | null
  ip_address: string | null
  created_at: string
}

interface PlanConfig {
  plan_id: string
  name: string
  price: number
  color: string
  popular: boolean
  is_active: boolean
  features: Record<string, boolean | number>
}

// ─── Shared ───────────────────────────────────────────────────────────────────

const PAGE_SIZE = 25

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="bg-s1 border border-s3 rounded-xl p-5 flex flex-col gap-1">
      <p className="text-tx2 text-xs uppercase tracking-widest">{label}</p>
      <p className="text-3xl font-bold text-tx font-head">{value}</p>
      {sub && <p className="text-tx2 text-xs">{sub}</p>}
    </div>
  )
}

function PlanBadge({ plan, plans }: { plan: string; plans?: PlanConfig[] }) {
  const cfg = plans?.find(p => p.plan_id === plan)
  if (cfg) {
    return (
      <span
        className="px-2 py-0.5 rounded text-[11px] font-semibold uppercase tracking-wide"
        style={{ background: `${cfg.color}22`, color: cfg.color, border: `1px solid ${cfg.color}44` }}
      >
        {plan}
      </span>
    )
  }
  return (
    <span className="px-2 py-0.5 rounded text-[11px] font-semibold uppercase tracking-wide bg-s3 text-tx2">
      {plan}
    </span>
  )
}

function AdminBadge() {
  return (
    <span className="px-2 py-0.5 rounded text-[11px] font-bold uppercase tracking-wide bg-cy/15 text-cy border border-cy/30">
      admin
    </span>
  )
}

function Pagination({
  page, total, pageSize, onChange,
}: { page: number; total: number; pageSize: number; onChange: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-s2 border-t border-s3 text-xs text-tx2">
      <button
        onClick={() => onChange(page - 1)} disabled={page <= 1}
        className="px-2 py-1 rounded hover:bg-s3 disabled:opacity-40 transition-colors"
      >← Prev</button>
      <span className="flex-1 text-center">Page {page} of {pages} ({total} total)</span>
      <button
        onClick={() => onChange(page + 1)} disabled={page >= pages}
        className="px-2 py-1 rounded hover:bg-s3 disabled:opacity-40 transition-colors"
      >Next →</button>
    </div>
  )
}

// ─── Edit User Modal ──────────────────────────────────────────────────────────

function EditUserModal({ user, onClose }: { user: User; onClose: () => void }) {
  const qc = useQueryClient()
  const [plan,       setPlan]      = useState(user.plan)
  const [isAdmin,    setIsAdmin]   = useState(user.is_admin)
  const [paperMode,  setPaperMode] = useState(user.is_paper_mode)

  const { data: plans } = useQuery({
    queryKey: ['admin-plans'],
    queryFn: () => api.get('/admin/plans').then(r => r.data as PlanConfig[]),
  })

  // Keep is_admin toggle in sync with plan selector
  function handlePlanChange(p: string) {
    setPlan(p)
    setIsAdmin(p === 'elite')
  }

  function handleAdminToggle() {
    const next = !isAdmin
    setIsAdmin(next)
    if (next) setPlan('elite')
    else if (plan === 'elite') setPlan('community')
  }

  const patch = useMutation({
    mutationFn: () => api.patch(`/admin/users/${user.id}`, { plan, is_paper_mode: paperMode }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      onClose()
    },
  })

  const planOptions = plans?.map(p => p.plan_id) ?? ['community', 'starter', 'trader', 'pro', 'elite', 'trial']

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 backdrop-blur-sm">
      <div className="bg-s1 border border-s3 rounded-2xl p-6 w-full max-w-md shadow-2xl">
        <h2 className="text-lg font-bold text-tx font-head mb-1">Edit User</h2>
        <p className="text-tx2 text-sm mb-5 truncate">{user.email}</p>

        <div className="space-y-4">
          <div>
            <label className="block text-xs text-tx2 mb-1.5">Plan</label>
            <select
              value={plan}
              onChange={e => handlePlanChange(e.target.value)}
              className="w-full bg-s2 border border-s3 rounded-lg px-3 py-2.5 text-sm text-tx focus:outline-none focus:border-cy/50 transition-colors"
            >
              {planOptions.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          <label className="flex items-center gap-3 cursor-pointer select-none">
            <div
              onClick={handleAdminToggle}
              className={`w-10 h-5 rounded-full transition-colors flex items-center ${isAdmin ? 'bg-cy' : 'bg-s3'}`}
            >
              <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform mx-0.5 ${isAdmin ? 'translate-x-5' : 'translate-x-0'}`} />
            </div>
            <span className="text-sm text-tx">Admin access (sets plan → elite)</span>
          </label>

          <label className="flex items-center gap-3 cursor-pointer select-none">
            <div
              onClick={() => setPaperMode(v => !v)}
              className={`w-10 h-5 rounded-full transition-colors flex items-center ${paperMode ? 'bg-gd' : 'bg-s3'}`}
            >
              <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform mx-0.5 ${paperMode ? 'translate-x-5' : 'translate-x-0'}`} />
            </div>
            <span className="text-sm text-tx">Paper mode</span>
          </label>
        </div>

        {patch.isError && (
          <p className="mt-3 text-rd text-sm">Failed to update user.</p>
        )}

        <div className="flex gap-3 mt-6">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded-lg border border-s3 text-tx2 text-sm hover:bg-s2 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => patch.mutate()}
            disabled={patch.isPending}
            className="flex-1 px-4 py-2 rounded-lg bg-cy text-bg font-semibold text-sm hover:bg-cy/90 transition-colors disabled:opacity-50"
          >
            {patch.isPending ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Users Table ──────────────────────────────────────────────────────────────

function UsersTable() {
  const [editUser,  setEditUser] = useState<User | null>(null)
  const [search,    setSearch]   = useState('')
  const [query,     setQuery]    = useState('')
  const [page,      setPage]     = useState(1)

  const { data: plans } = useQuery({
    queryKey: ['admin-plans'],
    queryFn: () => api.get('/admin/plans').then(r => r.data as PlanConfig[]),
  })

  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin-users', query, page],
    queryFn: () =>
      api.get('/admin/users', {
        params: { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE, ...(query ? { search: query } : {}) },
      }).then(r => r.data as { total: number; users: User[] }),
  })

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    setQuery(search.trim())
    setPage(1)
  }

  if (isLoading) return <p className="text-tx2 text-sm animate-pulse">Loading users…</p>
  if (isError)   return <p className="text-rd text-sm">Failed to load users.</p>

  return (
    <>
      {editUser && <EditUserModal user={editUser} onClose={() => setEditUser(null)} />}

      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2 mb-4">
        <input
          type="text"
          placeholder="Search by email…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="flex-1 bg-s1 border border-s3 rounded-lg px-3 py-2 text-sm text-tx placeholder-tx3 focus:outline-none focus:border-cy/50 transition-colors"
        />
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-cy text-bg text-xs font-bold tracking-widest hover:bg-cy/90 transition-colors"
        >
          Search
        </button>
        {query && (
          <button
            type="button"
            onClick={() => { setSearch(''); setQuery(''); setPage(1) }}
            className="px-3 py-2 rounded-lg border border-s3 text-tx2 text-xs hover:bg-s2 transition-colors"
          >
            Clear
          </button>
        )}
      </form>

      <div className="overflow-x-auto rounded-xl border border-s3">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-s2 text-tx2 text-xs uppercase tracking-wide">
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Plan</th>
              <th className="text-left px-4 py-3">Role</th>
              <th className="text-left px-4 py-3">Paper</th>
              <th className="text-left px-4 py-3">Joined</th>
              <th className="text-left px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-s3">
            {data?.users.map(u => (
              <tr key={u.id} className="hover:bg-s2/50 transition-colors">
                <td className="px-4 py-3 text-tx font-mono text-xs">{u.email}</td>
                <td className="px-4 py-3"><PlanBadge plan={u.plan} plans={plans} /></td>
                <td className="px-4 py-3">
                  {u.is_admin ? <AdminBadge /> : <span className="text-tx2 text-xs">user</span>}
                </td>
                <td className="px-4 py-3">
                  {u.is_paper_mode
                    ? <span className="text-[11px] font-semibold px-2 py-0.5 rounded bg-gd/10 text-gd border border-gd/20">paper</span>
                    : <span className="text-tx3 text-xs">live</span>
                  }
                </td>
                <td className="px-4 py-3 text-tx2 text-xs">
                  {new Date(u.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => setEditUser(u)}
                    className="text-xs text-cy hover:text-cy/80 transition-colors font-medium"
                  >
                    Edit
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pagination
          page={page}
          total={data?.total ?? 0}
          pageSize={PAGE_SIZE}
          onChange={setPage}
        />
      </div>
    </>
  )
}

// ─── Audit Log ────────────────────────────────────────────────────────────────

function AuditLog() {
  const [page,       setPage]    = useState(1)
  const [action,     setAction]  = useState('')
  const [search,     setSearch]  = useState('')
  const [emailQuery, setEmailQ]  = useState('')

  const { data: actions } = useQuery({
    queryKey: ['admin-audit-actions'],
    queryFn: () => api.get('/admin/audit/actions').then(r => r.data as string[]),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['admin-audit', action, emailQuery, page],
    queryFn: () =>
      api.get('/admin/audit', {
        params: {
          limit:  PAGE_SIZE,
          offset: (page - 1) * PAGE_SIZE,
          ...(action     ? { action }        : {}),
          ...(emailQuery ? { search: emailQuery } : {}),
        },
      }).then(r => r.data as { total: number; entries: AuditEntry[] }),
  })

  function handleEmailSearch(e: React.FormEvent) {
    e.preventDefault()
    setEmailQ(search.trim())
    setPage(1)
  }

  if (isLoading) return <p className="text-tx2 text-sm animate-pulse">Loading audit log…</p>

  return (
    <div className="space-y-3">
      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <form onSubmit={handleEmailSearch} className="flex gap-2 flex-1 min-w-[200px]">
          <input
            type="text"
            placeholder="Filter by email…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="flex-1 bg-s1 border border-s3 rounded-lg px-3 py-2 text-sm text-tx placeholder-tx3 focus:outline-none focus:border-cy/50 transition-colors"
          />
          <button type="submit"
            className="px-4 py-2 rounded-lg bg-cy text-bg text-xs font-bold tracking-widest hover:bg-cy/90 transition-colors">
            Search
          </button>
          {emailQuery && (
            <button type="button" onClick={() => { setSearch(''); setEmailQ(''); setPage(1) }}
              className="px-3 py-2 rounded-lg border border-s3 text-tx2 text-xs hover:bg-s2 transition-colors">
              Clear
            </button>
          )}
        </form>

        <select
          value={action}
          onChange={e => { setAction(e.target.value); setPage(1) }}
          className="bg-s1 border border-s3 rounded-lg px-3 py-2 text-sm text-tx focus:outline-none focus:border-cy/50 transition-colors"
        >
          <option value="">All actions</option>
          {(actions ?? []).map(a => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
      </div>

      <div className="overflow-x-auto rounded-xl border border-s3">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-s2 text-tx2 uppercase tracking-wide">
              <th className="text-left px-4 py-3">Time</th>
              <th className="text-left px-4 py-3">User</th>
              <th className="text-left px-4 py-3">Action</th>
              <th className="text-left px-4 py-3">Detail</th>
              <th className="text-left px-4 py-3">IP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-s3">
            {data?.entries.map(e => (
              <tr key={e.id} className="hover:bg-s2/50 transition-colors">
                <td className="px-4 py-2.5 text-tx2 font-mono whitespace-nowrap">
                  {new Date(e.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-2.5 text-tx font-mono truncate max-w-[180px]">{e.email ?? '—'}</td>
                <td className="px-4 py-2.5">
                  <span className="px-2 py-0.5 rounded bg-s3 text-cy font-semibold">{e.action}</span>
                </td>
                <td className="px-4 py-2.5 text-tx2 truncate max-w-[240px]">{e.detail ?? '—'}</td>
                <td className="px-4 py-2.5 text-tx2 font-mono">{e.ip_address ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pagination
          page={page}
          total={data?.total ?? 0}
          pageSize={PAGE_SIZE}
          onChange={setPage}
        />
      </div>
    </div>
  )
}

// ─── Plans Editor ─────────────────────────────────────────────────────────────

const BOOL_FEATURES: { key: string; label: string }[] = [
  { key: 'dashboard',        label: 'Web Dashboard' },
  { key: 'signals_web',      label: 'Signals (Web)' },
  { key: 'signals_tg_drops', label: 'TG Signal Drops' },
  { key: 'tg_bot_approve',   label: 'TG Approve/Reject' },
  { key: 'tg_bot_settings',  label: 'TG Settings' },
  { key: 'auto_execute',     label: 'Auto-Execute' },
  { key: 'copy_trade',       label: 'Copy Trade' },
  { key: 'api_access',       label: 'API Access' },
  { key: 'mobile_app',       label: 'Mobile App' },
  { key: 'priority_support', label: 'Priority Support' },
]

function PlanEditor({ plan, onSaved }: { plan: PlanConfig; onSaved: () => void }) {
  const qc = useQueryClient()
  const [name,     setName]    = useState(plan.name)
  const [price,    setPrice]   = useState(plan.price)
  const [color,    setColor]   = useState(plan.color)
  const [popular,  setPopular] = useState(plan.popular)
  const [isActive, setActive]  = useState(plan.is_active)
  const [feats,    setFeats]   = useState<Record<string, boolean | number>>({ ...plan.features })
  const [dirty,    setDirty]   = useState(false)

  useEffect(() => {
    setName(plan.name)
    setPrice(plan.price)
    setColor(plan.color)
    setPopular(plan.popular)
    setActive(plan.is_active)
    setFeats({ ...plan.features })
    setDirty(false)
  }, [plan.plan_id])

  const save = useMutation({
    mutationFn: () => api.patch(`/admin/plans/${plan.plan_id}`, {
      name, price, color, popular, is_active: isActive, features: feats,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-plans'] })
      qc.invalidateQueries({ queryKey: ['plans'] })
      setDirty(false)
      onSaved()
    },
  })

  const mark = () => setDirty(true)
  const setFeat = (key: string, val: boolean | number) => { setFeats(p => ({ ...p, [key]: val })); mark() }

  return (
    <div className="bg-s1 border border-s3 rounded-xl p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] font-bold px-2 py-0.5 rounded tracking-widest"
            style={{ background: `${color}22`, color, border: `1px solid ${color}44` }}>
            {plan.plan_id.toUpperCase()}
          </span>
          {popular && (
            <span className="font-mono text-[9px] px-1.5 py-0.5 rounded bg-cy/10 text-cy border border-cy/20">POPULAR</span>
          )}
        </div>
        {dirty ? (
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending}
            className="text-xs font-semibold px-3 py-1 rounded-lg bg-cy text-bg hover:bg-cy/90 transition-colors disabled:opacity-50"
          >
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
        ) : (
          <span className="text-[10px] font-mono text-tx3">No changes</span>
        )}
      </div>

      {/* Display name */}
      <div>
        <div className="text-[10px] font-mono text-tx3 uppercase tracking-widest mb-1">Display Name</div>
        <input
          value={name}
          onChange={e => { setName(e.target.value); mark() }}
          className="w-full bg-s2 border border-s3 rounded-lg px-2 py-1.5 text-sm text-tx focus:outline-none focus:border-cy/50"
        />
      </div>

      {/* Price + color + popular */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <div className="text-[10px] font-mono text-tx3 uppercase tracking-widest mb-1">Price / mo</div>
          <div className="flex items-center gap-1">
            <span className="text-tx3 text-sm">$</span>
            <input
              type="number" min={0} step={1}
              value={price}
              onChange={e => { setPrice(parseFloat(e.target.value) || 0); mark() }}
              className="w-full bg-s2 border border-s3 rounded-lg px-2 py-1.5 text-sm text-tx font-mono focus:outline-none focus:border-cy/50"
            />
          </div>
        </div>
        <div>
          <div className="text-[10px] font-mono text-tx3 uppercase tracking-widest mb-1">Badge Color</div>
          <div className="flex items-center gap-2">
            <input type="color" value={color}
              onChange={e => { setColor(e.target.value); mark() }}
              className="w-9 h-8 rounded cursor-pointer bg-s2 border border-s3" />
            <span className="text-[10px] font-mono text-tx3">{color}</span>
          </div>
        </div>
      </div>

      {/* Pairs + MT5 */}
      <div className="grid grid-cols-2 gap-2">
        {[{ key: 'pairs', label: 'Max Pairs' }, { key: 'mt5_accounts', label: 'MT5 Accts' }].map(f => (
          <div key={f.key}>
            <div className="text-[10px] font-mono text-tx3 uppercase tracking-widest mb-1">{f.label}</div>
            <input
              type="number" min={0} step={1}
              value={Number(feats[f.key] ?? 0)}
              onChange={e => setFeat(f.key, parseInt(e.target.value) || 0)}
              className="w-full bg-s2 border border-s3 rounded-lg px-2 py-1.5 text-sm text-tx font-mono focus:outline-none focus:border-cy/50"
            />
          </div>
        ))}
      </div>

      {/* Active + Popular toggles */}
      <div className="flex flex-col gap-1.5">
        {[
          { label: 'Active (visible in billing)', val: isActive, set: (v: boolean) => { setActive(v); mark() } },
          { label: 'Mark as Popular',             val: popular,  set: (v: boolean) => { setPopular(v); mark() } },
        ].map(row => (
          <div key={row.label} className="flex items-center justify-between cursor-pointer select-none" onClick={() => row.set(!row.val)}>
            <span className="text-xs text-tx2">{row.label}</span>
            <div className={`w-8 h-4 rounded-full transition-colors flex items-center ${row.val ? 'bg-cy' : 'bg-s3'}`}>
              <div className={`w-3 h-3 bg-white rounded-full shadow transition-transform mx-0.5 ${row.val ? 'translate-x-4' : 'translate-x-0'}`} />
            </div>
          </div>
        ))}
      </div>

      {/* Feature toggles */}
      <div className="space-y-1.5">
        <div className="text-[10px] font-mono text-tx3 uppercase tracking-widest">Features</div>
        {BOOL_FEATURES.map(f => (
          <div key={f.key} className="flex items-center justify-between cursor-pointer select-none" onClick={() => setFeat(f.key, !feats[f.key])}>
            <span className="text-xs text-tx2">{f.label}</span>
            <div className={`w-8 h-4 rounded-full transition-colors flex items-center ${feats[f.key] ? 'bg-cy' : 'bg-s3'}`}>
              <div className={`w-3 h-3 bg-white rounded-full shadow transition-transform mx-0.5 ${feats[f.key] ? 'translate-x-4' : 'translate-x-0'}`} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const DEFAULT_FEATURES = {
  pairs: 0, mt5_accounts: 0, dashboard: false, signals_web: false,
  signals_tg_drops: false, tg_bot_approve: false, tg_bot_settings: false,
  auto_execute: false, copy_trade: false, api_access: false,
  mobile_app: false, priority_support: false,
}

function CreatePlanModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({
    plan_id: '', name: '', price: 0, color: '#8899b4', popular: false,
  })
  const [feats, setFeats] = useState<Record<string, boolean | number>>({ ...DEFAULT_FEATURES })
  const [err,   setErr]   = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () => api.post('/admin/plans', { ...form, features: feats }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-plans'] })
      qc.invalidateQueries({ queryKey: ['plans'] })
      onClose()
    },
    onError: (e: any) => setErr(e?.response?.data?.detail ?? 'Failed to create plan'),
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 backdrop-blur-sm">
      <div className="bg-s1 border border-s3 rounded-2xl p-6 w-full max-w-lg shadow-2xl overflow-y-auto max-h-[90vh]">
        <h2 className="text-lg font-bold text-tx font-head mb-4">Create New Plan</h2>

        <div className="space-y-3 mb-4">
          {[
            { key: 'plan_id', label: 'Plan ID (slug)', placeholder: 'e.g. growth' },
            { key: 'name',    label: 'Display Name',   placeholder: 'e.g. Growth' },
          ].map(f => (
            <div key={f.key}>
              <label className="block text-xs text-tx2 mb-1">{f.label}</label>
              <input
                value={(form as any)[f.key]}
                onChange={e => setForm(p => ({ ...p, [f.key]: e.target.value }))}
                placeholder={f.placeholder}
                className="w-full bg-s2 border border-s3 rounded-lg px-3 py-2 text-sm text-tx focus:outline-none focus:border-cy/50"
              />
            </div>
          ))}
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="block text-xs text-tx2 mb-1">Price / mo ($)</label>
              <input type="number" min={0} value={form.price}
                onChange={e => setForm(p => ({ ...p, price: parseFloat(e.target.value) || 0 }))}
                className="w-full bg-s2 border border-s3 rounded-lg px-3 py-2 text-sm text-tx focus:outline-none focus:border-cy/50"
              />
            </div>
            <div className="flex-1">
              <label className="block text-xs text-tx2 mb-1">Badge Color</label>
              <div className="flex items-center gap-2">
                <input type="color" value={form.color}
                  onChange={e => setForm(p => ({ ...p, color: e.target.value }))}
                  className="w-10 h-9 rounded cursor-pointer bg-s2 border border-s3" />
                <span className="text-xs text-tx2 font-mono">{form.color}</span>
              </div>
            </div>
          </div>
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="block text-xs text-tx2 mb-1">Pairs</label>
              <input type="number" min={0} value={Number(feats.pairs)}
                onChange={e => setFeats(p => ({ ...p, pairs: parseInt(e.target.value) || 0 }))}
                className="w-full bg-s2 border border-s3 rounded-lg px-3 py-2 text-sm text-tx focus:outline-none focus:border-cy/50"
              />
            </div>
            <div className="flex-1">
              <label className="block text-xs text-tx2 mb-1">MT5 Accounts</label>
              <input type="number" min={0} value={Number(feats.mt5_accounts)}
                onChange={e => setFeats(p => ({ ...p, mt5_accounts: parseInt(e.target.value) || 0 }))}
                className="w-full bg-s2 border border-s3 rounded-lg px-3 py-2 text-sm text-tx focus:outline-none focus:border-cy/50"
              />
            </div>
          </div>
          <div>
            <div className="text-xs text-tx2 mb-2">Features</div>
            <div className="grid grid-cols-2 gap-1.5">
              {BOOL_FEATURES.map(f => (
                <label key={f.key} className="flex items-center justify-between cursor-pointer select-none">
                  <span className="text-xs text-tx2">{f.label}</span>
                  <div onClick={() => setFeats(p => ({ ...p, [f.key]: !p[f.key] }))}
                    className={`w-8 h-4 rounded-full transition-colors flex items-center ${feats[f.key] ? 'bg-cy' : 'bg-s3'}`}>
                    <div className={`w-3 h-3 bg-white rounded-full shadow transition-transform mx-0.5 ${feats[f.key] ? 'translate-x-4' : 'translate-x-0'}`} />
                  </div>
                </label>
              ))}
            </div>
          </div>
        </div>

        {err && <p className="text-rd text-xs mb-3">{err}</p>}

        <div className="flex gap-3">
          <button onClick={onClose}
            className="flex-1 px-4 py-2 rounded-lg border border-s3 text-tx2 text-sm hover:bg-s2 transition-colors">
            Cancel
          </button>
          <button
            onClick={() => create.mutate()}
            disabled={create.isPending || !form.plan_id || !form.name}
            className="flex-1 px-4 py-2 rounded-lg bg-cy text-bg font-semibold text-sm hover:bg-cy/90 transition-colors disabled:opacity-50">
            {create.isPending ? 'Creating…' : 'Create Plan'}
          </button>
        </div>
      </div>
    </div>
  )
}

function PlansEditor() {
  const qc = useQueryClient()
  const [saved,      setSaved]    = useState<string | null>(null)
  const [showCreate, setCreate]   = useState(false)
  const [confirmDel, setConfirmDel] = useState<PlanConfig | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['admin-plans'],
    queryFn: () => api.get('/admin/plans').then(r => r.data as PlanConfig[]),
  })

  const deletePlan = useMutation({
    mutationFn: (planId: string) => api.delete(`/admin/plans/${planId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-plans'] })
      qc.invalidateQueries({ queryKey: ['plans'] })
      setConfirmDel(null)
    },
    onError: (e: any) => alert(e?.response?.data?.detail ?? 'Failed to delete plan'),
  })

  if (isLoading) return <p className="text-tx2 text-sm animate-pulse">Loading plans…</p>
  if (!data) return (
    <div className="bg-s1 border border-rd/20 rounded-xl p-6 text-center">
      <div className="text-rd text-sm font-mono mb-1">Could not load plans</div>
      <div className="text-tx3 text-xs">The /admin/plans endpoint returned no data. Restart the server to apply the latest routes, then refresh.</div>
    </div>
  )

  return (
    <div className="space-y-4">
      {showCreate && <CreatePlanModal onClose={() => setCreate(false)} />}

      {confirmDel && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 backdrop-blur-sm">
          <div className="bg-s1 border border-s3 rounded-2xl p-6 w-full max-w-sm shadow-2xl">
            <h2 className="text-base font-bold text-tx font-head mb-2">Delete Plan</h2>
            <p className="text-tx2 text-sm mb-5">
              Delete <span className="font-bold text-rd">{confirmDel.name}</span>? This cannot be undone.
              All users must be moved off this plan first.
            </p>
            <div className="flex gap-3">
              <button onClick={() => setConfirmDel(null)}
                className="flex-1 px-4 py-2 rounded-lg border border-s3 text-tx2 text-sm hover:bg-s2 transition-colors">
                Cancel
              </button>
              <button
                onClick={() => deletePlan.mutate(confirmDel.plan_id)}
                disabled={deletePlan.isPending}
                className="flex-1 px-4 py-2 rounded-lg bg-rd text-white font-semibold text-sm hover:bg-rd/80 transition-colors disabled:opacity-50">
                {deletePlan.isPending ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-tx2 text-sm">Edit prices and feature flags. Changes apply to Billing immediately.</p>
        <div className="flex items-center gap-3">
          {saved && <span className="text-xs text-cy font-mono">✓ {saved} saved</span>}
          <button
            onClick={() => setCreate(true)}
            className="px-3 py-1.5 rounded-lg bg-cy text-bg text-xs font-bold tracking-widest hover:bg-cy/90 transition-colors">
            + NEW PLAN
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
        {(data ?? []).map(p => (
          <div key={p.plan_id} className="relative">
            <PlanEditor plan={p} onSaved={() => {
              setSaved(p.name)
              setTimeout(() => setSaved(null), 2500)
            }} />
            <button
              onClick={() => setConfirmDel(p)}
              title="Delete plan"
              className="absolute top-3 right-3 text-[10px] font-mono text-rd/60 hover:text-rd transition-colors"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Feature Flags ───────────────────────────────────────────────────────────

interface FeatureFlags {
  registration_enabled:   boolean
  maintenance_mode:       boolean
  trial_enabled:          boolean
  telegram_login_enabled: boolean
}

function FeatureFlagsPanel() {
  const qc = useQueryClient()
  const [flags,    setFlags]    = useState<FeatureFlags | null>(null)
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['admin-config'],
    queryFn:  () => api.get('/admin/config').then(r => r.data),
  })

  useEffect(() => {
    if (!data) return
    setFlags({
      registration_enabled:   data.registration_enabled   ?? true,
      maintenance_mode:       data.maintenance_mode        ?? false,
      trial_enabled:          data.trial_enabled           ?? true,
      telegram_login_enabled: data.telegram_login_enabled ?? true,
    })
  }, [data])

  const save = useMutation({
    mutationFn: () => api.patch('/admin/config', flags),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-config'] })
      setFeedback({ ok: true, msg: 'Feature flags saved.' })
      setTimeout(() => setFeedback(null), 3000)
    },
    onError: () => setFeedback({ ok: false, msg: 'Failed to save.' }),
  })

  if (isLoading || !flags) return null

  const rows: { key: keyof FeatureFlags; label: string; sub: string; danger?: boolean }[] = [
    {
      key:    'registration_enabled',
      label:  'Open Registration',
      sub:    'Allow new users to create accounts. Disable to close signups.',
    },
    {
      key:    'trial_enabled',
      label:  'Free Trial',
      sub:    'Allow users to start a free trial from the landing page.',
    },
    {
      key:    'telegram_login_enabled',
      label:  'Telegram Login',
      sub:    'Show the "Connect via Telegram" login option on the login page.',
    },
    {
      key:    'maintenance_mode',
      label:  'Maintenance Mode',
      sub:    'Show a maintenance page to all non-admin users. Admins can still log in.',
      danger: true,
    },
  ]

  return (
    <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-tx">Feature Flags</h3>
        <p className="text-xs text-tx3 mt-0.5">Toggle platform features without redeploying.</p>
      </div>

      {feedback && (
        <div className={`flex items-center justify-between px-4 py-3 rounded-xl text-xs font-mono ${feedback.ok ? 'bg-cy/5 border border-cy/20 text-cy' : 'bg-rd/5 border border-rd/20 text-rd'}`}>
          <span>{feedback.ok ? '✓' : '✗'} {feedback.msg}</span>
          <button onClick={() => setFeedback(null)} className="opacity-50 hover:opacity-100 ml-4">✕</button>
        </div>
      )}

      <div className="divide-y divide-s3">
        {rows.map(row => (
          <div
            key={row.key}
            className="flex items-center justify-between py-3 cursor-pointer select-none"
            onClick={() => setFlags(f => f ? { ...f, [row.key]: !f[row.key] } : f)}
          >
            <div>
              <div className={`text-sm font-medium ${row.danger ? 'text-rd' : 'text-tx'}`}>{row.label}</div>
              <div className="text-xs text-tx3 mt-0.5">{row.sub}</div>
            </div>
            <div className={`w-10 h-5 rounded-full transition-colors flex items-center shrink-0 ml-4 ${flags[row.key] ? (row.danger ? 'bg-rd' : 'bg-cy') : 'bg-s3'}`}>
              <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform mx-0.5 ${flags[row.key] ? 'translate-x-5' : 'translate-x-0'}`} />
            </div>
          </div>
        ))}
      </div>

      <button
        onClick={() => save.mutate()}
        disabled={save.isPending}
        className="px-5 py-2.5 rounded-lg bg-cy text-bg text-xs font-bold tracking-widest hover:bg-cy/90 transition-colors disabled:opacity-50"
      >
        {save.isPending ? 'Saving…' : 'Save Flags'}
      </button>
    </div>
  )
}

// ─── Email Config ─────────────────────────────────────────────────────────────

function EmailConfig() {
  const qc = useQueryClient()
  const [form, setForm] = useState({
    smtp_host: '', smtp_port: 587, smtp_user: '', smtp_password: '',
    smtp_from_email: '', smtp_from_name: '', smtp_enabled: false,
  })
  const [feedback, setFeedback] = useState<{ msg: string; ok: boolean } | null>(null)
  const [testing, setTesting] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['admin-config'],
    queryFn: () => api.get('/admin/config').then(r => r.data),
  })

  useEffect(() => {
    if (!data) return
    setForm({
      smtp_host:       data.smtp_host       ?? '',
      smtp_port:       data.smtp_port       ?? 587,
      smtp_user:       data.smtp_user       ?? '',
      smtp_password:   data.smtp_password   ?? '',
      smtp_from_email: data.smtp_from_email ?? '',
      smtp_from_name:  data.smtp_from_name  ?? '',
      smtp_enabled:    data.smtp_enabled    ?? false,
    })
  }, [data])

  const notify = (ok: boolean, msg: string) => {
    setFeedback({ ok, msg })
    setTimeout(() => setFeedback(null), 4000)
  }

  const save = useMutation({
    mutationFn: () => api.patch('/admin/config', form),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-config'] }); notify(true, 'Email settings saved.') },
    onError: () => notify(false, 'Failed to save.'),
  })

  async function testEmail() {
    setTesting(true); setFeedback(null)
    try {
      const res = await api.post('/admin/config/test-email')
      notify(true, res.data.message)
    } catch (e: any) {
      notify(false, e?.response?.data?.detail ?? 'Test failed.')
    } finally { setTesting(false) }
  }

  const set = (k: keyof typeof form) => (v: string | number | boolean) =>
    setForm(p => ({ ...p, [k]: v }))

  if (isLoading) return null

  return (
    <div className="space-y-4">
      {feedback && (
        <div className={`flex items-center justify-between px-4 py-3 rounded-xl text-sm font-mono ${feedback.ok ? 'bg-cy/5 border border-cy/20 text-cy' : 'bg-rd/5 border border-rd/20 text-rd'}`}>
          <span>{feedback.ok ? '✓' : '✗'} {feedback.msg}</span>
          <button onClick={() => setFeedback(null)} className="opacity-50 hover:opacity-100 ml-4">✕</button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Left: SMTP config */}
        <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-tx">Email / SMTP</h3>
              <p className="text-xs text-tx3 mt-0.5">Used for daily summaries, trade reports, and transactional emails</p>
            </div>
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <span className="text-xs text-tx2">Enable</span>
              <div onClick={() => set('smtp_enabled')(!form.smtp_enabled)}
                className={`w-9 h-5 rounded-full flex items-center transition-colors ${form.smtp_enabled ? 'bg-cy' : 'bg-s3'}`}>
                <div className={`w-3.5 h-3.5 bg-white rounded-full shadow mx-0.5 transition-transform ${form.smtp_enabled ? 'translate-x-4' : 'translate-x-0'}`} />
              </div>
            </label>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <ConfigInput label="SMTP Host" value={form.smtp_host} onChange={set('smtp_host') as any}
                placeholder="smtp.gmail.com" hint="e.g. smtp.gmail.com · smtp.sendgrid.net" />
            </div>
            <div>
              <label className="block text-[10px] font-mono text-tx3 uppercase tracking-widest mb-1.5">Port</label>
              <input type="number" value={form.smtp_port}
                onChange={e => set('smtp_port')(parseInt(e.target.value) || 587)}
                className="w-full bg-s2 border border-s3 rounded-lg px-3 py-2 text-sm text-tx font-mono focus:outline-none focus:border-cy/50 transition-colors"
              />
            </div>
          </div>

          <ConfigInput label="Username / Email" value={form.smtp_user} onChange={set('smtp_user') as any}
            placeholder="you@gmail.com" />
          <ConfigInput label="Password / App Password" type="password"
            value={form.smtp_password} onChange={set('smtp_password') as any}
            placeholder="••••••••" hint="Gmail: use an App Password, not your account password." />

          <div className="grid grid-cols-2 gap-3">
            <ConfigInput label="From Email" value={form.smtp_from_email} onChange={set('smtp_from_email') as any}
              placeholder="noreply@yourdomain.com" />
            <ConfigInput label="From Name" value={form.smtp_from_name} onChange={set('smtp_from_name') as any}
              placeholder="Traxovia AI" />
          </div>

          <div className="flex gap-2 pt-1">
            <button onClick={() => save.mutate()} disabled={save.isPending}
              className="px-5 py-2.5 rounded-lg bg-cy text-bg text-xs font-bold tracking-widest hover:bg-cy/90 transition-colors disabled:opacity-50">
              {save.isPending ? 'Saving…' : 'Save Settings'}
            </button>
            <button onClick={testEmail} disabled={testing}
              className="px-4 py-2.5 rounded-lg border border-s3 text-xs font-mono text-tx2 hover:bg-s2 transition-colors disabled:opacity-50">
              {testing ? '…' : 'Send Test Email'}
            </button>
          </div>
        </div>

        {/* Right: provider guide */}
        <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-semibold text-tx">Provider Quick-Start</h3>
          {[
            { name: 'Gmail', host: 'smtp.gmail.com', port: '587', note: 'Enable 2FA → create App Password at myaccount.google.com/apppasswords' },
            { name: 'SendGrid', host: 'smtp.sendgrid.net', port: '587', note: 'Username: apikey · Password: your SendGrid API key' },
            { name: 'Mailgun', host: 'smtp.mailgun.org', port: '587', note: 'Credentials in Sending → Domain Settings → SMTP credentials' },
            { name: 'Outlook/365', host: 'smtp.office365.com', port: '587', note: 'Use your Microsoft account email and password (or app password)' },
          ].map(p => (
            <div key={p.name} className="px-3 py-2.5 bg-s2 border border-s3 rounded-lg">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-semibold text-tx">{p.name}</span>
                <span className="font-mono text-[10px] text-tx3">{p.host}:{p.port}</span>
              </div>
              <p className="text-[11px] text-tx3">{p.note}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ─── Payment Config ───────────────────────────────────────────────────────────

function PaymentConfig() {
  const qc = useQueryClient()
  const [keys, setKeys] = useState({ paystack_secret_key: '', paystack_public_key: '' })
  const [planCodes, setPlanCodes] = useState<Record<string, string>>({})
  const [feedback, setFeedback] = useState<{ msg: string; ok: boolean } | null>(null)
  const [saving, setSaving] = useState(false)

  const { data: config } = useQuery({
    queryKey: ['admin-config'],
    queryFn: () => api.get('/admin/config').then(r => r.data),
  })
  const { data: plans } = useQuery({
    queryKey: ['admin-plans'],
    queryFn: () => api.get('/admin/plans').then(r => r.data as any[]),
  })

  const paidPlans = (plans ?? []).filter((p: any) => p.plan_id !== 'community')

  useEffect(() => {
    if (!config) return
    setKeys({
      paystack_secret_key: config.paystack_secret_key ?? '',
      paystack_public_key: config.paystack_public_key ?? '',
    })
  }, [config])

  // Load plan codes from plan_config.features.paystack_plan_code
  useEffect(() => {
    if (!plans) return
    const codes: Record<string, string> = {}
    for (const p of plans) {
      if (p.plan_id !== 'community') {
        codes[p.plan_id] = p.features?.paystack_plan_code ?? ''
      }
    }
    setPlanCodes(codes)
  }, [plans])

  const notify = (ok: boolean, msg: string) => {
    setFeedback({ ok, msg }); setTimeout(() => setFeedback(null), 4000)
  }

  async function save() {
    setSaving(true)
    try {
      // Save Paystack keys to bot_config
      await api.patch('/admin/config', { payment_gateway: 'paystack', ...keys })
      // Save each plan's paystack_plan_code into plan_config.features
      await Promise.all(
        paidPlans.map((p: any) =>
          api.patch(`/admin/plans/${p.plan_id}`, {
            features: { ...p.features, paystack_plan_code: planCodes[p.plan_id] ?? '' },
          })
        )
      )
      qc.invalidateQueries({ queryKey: ['admin-config'] })
      qc.invalidateQueries({ queryKey: ['admin-plans'] })
      notify(true, 'Payment settings saved.')
    } catch {
      notify(false, 'Failed to save.')
    } finally {
      setSaving(false)
    }
  }

  async function testGateway() {
    try {
      const res = await api.post('/admin/config/test-payment')
      notify(true, res.data.message)
    } catch (e: any) {
      notify(false, e?.response?.data?.detail ?? 'Test failed.')
    }
  }

  return (
    <div className="space-y-4">
      {feedback && (
        <div className={`flex items-center justify-between px-4 py-3 rounded-xl text-sm font-mono ${feedback.ok ? 'bg-cy/5 border border-cy/20 text-cy' : 'bg-rd/5 border border-rd/20 text-rd'}`}>
          <span>{feedback.ok ? '✓' : '✗'} {feedback.msg}</span>
          <button onClick={() => setFeedback(null)} className="opacity-50 hover:opacity-100 ml-4">✕</button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Paystack API keys */}
        <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-semibold text-tx">Paystack Keys</h3>
          <ConfigInput label="Secret Key" type="password" value={keys.paystack_secret_key}
            onChange={v => setKeys(k => ({ ...k, paystack_secret_key: v }))}
            placeholder="sk_live_••••"
            hint="Paystack Dashboard → Settings → API Keys & Webhooks" />
          <ConfigInput label="Public Key" value={keys.paystack_public_key}
            onChange={v => setKeys(k => ({ ...k, paystack_public_key: v }))}
            placeholder="pk_live_••••"
            hint="Used for Paystack Inline popup (optional)" />
          <div className="flex gap-2 pt-1">
            <button onClick={save} disabled={saving}
              className="px-5 py-2.5 rounded-lg bg-cy text-bg text-xs font-bold tracking-widest hover:bg-cy/90 transition-colors disabled:opacity-50">
              {saving ? 'Saving…' : 'Save All'}
            </button>
            <button onClick={testGateway}
              className="px-4 py-2.5 rounded-lg border border-s3 text-xs font-mono text-tx2 hover:bg-s2 transition-colors">
              Test Connection
            </button>
          </div>
        </div>

        {/* Per-plan Paystack plan codes — auto-generated from plan_config */}
        <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-3">
          <div>
            <h3 className="text-sm font-semibold text-tx">Plan Codes</h3>
            <p className="text-xs text-tx3 mt-0.5">
              Paystack Dashboard → Products → Plans → copy each plan code.
              Leave blank to use one-time payments. Adds/removes automatically when plans are created or deleted.
            </p>
          </div>
          {paidPlans.length === 0 && (
            <p className="text-tx3 text-xs font-mono">No paid plans configured yet.</p>
          )}
          {paidPlans.map((p: any) => (
            <ConfigInput key={p.plan_id}
              label={p.name.toUpperCase()}
              value={planCodes[p.plan_id] ?? ''}
              onChange={v => setPlanCodes(c => ({ ...c, [p.plan_id]: v }))}
              placeholder="PLN_••••" />
          ))}
          {paidPlans.length > 0 && (
            <button onClick={save} disabled={saving}
              className="w-full py-2.5 rounded-lg bg-cy text-bg text-xs font-bold tracking-widest hover:bg-cy/90 transition-colors disabled:opacity-50 mt-1">
              {saving ? 'Saving…' : 'Save Plan Codes'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Finnhub Config ───────────────────────────────────────────────────────────

function FinnhubConfig() {
  const qc = useQueryClient()
  const [apiKey, setApiKey]     = useState('')
  const [feedback, setFeedback] = useState<{ msg: string; ok: boolean } | null>(null)
  const [testing, setTesting]   = useState(false)
  // Track whether the user has manually edited the key so we don't
  // overwrite their input when the query re-fetches after save.
  const initialised = useRef(false)

  const { data, isLoading } = useQuery({
    queryKey: ['admin-config'],
    queryFn: () => api.get('/admin/config').then(r => r.data),
  })

  useEffect(() => {
    // Only populate from server on first load, not after re-fetches
    // triggered by invalidateQueries — that would clobber the user's input.
    if (data && !initialised.current) {
      setApiKey(data.finnhub_api_key ?? '')
      initialised.current = true
    }
  }, [data])

  const notify = (ok: boolean, msg: string) => {
    setFeedback({ ok, msg })
    setTimeout(() => setFeedback(null), 4000)
  }

  const save = useMutation({
    mutationFn: () => api.patch('/admin/config', { finnhub_api_key: apiKey }),
    onSuccess: () => {
      // Reset so the field refreshes with the masked value from server
      // only after an explicit page reload — not mid-session.
      qc.invalidateQueries({ queryKey: ['admin-config'] })
      notify(true, 'Finnhub API key saved.')
    },
    onError: () => notify(false, 'Failed to save.'),
  })

  async function testKey() {
    setTesting(true)
    setFeedback(null)
    try {
      const res = await api.post('/admin/config/test-finnhub')
      notify(true, res.data.message)
    } catch (e: any) {
      notify(false, e?.response?.data?.detail ?? 'Connection failed.')
    } finally {
      setTesting(false)
    }
  }

  if (isLoading) return <p className="text-tx2 text-sm animate-pulse">Loading…</p>

  return (
    <div className="space-y-4">
      {feedback && (
        <div className={`flex items-center justify-between px-4 py-3 rounded-xl text-sm font-mono ${feedback.ok ? 'bg-cy/5 border border-cy/20 text-cy' : 'bg-rd/5 border border-rd/20 text-rd'}`}>
          <span>{feedback.ok ? '✓' : '✗'} {feedback.msg}</span>
          <button onClick={() => setFeedback(null)} className="opacity-50 hover:opacity-100 ml-4">✕</button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Left: key input */}
        <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-tx">Finnhub API Key</h3>
              <p className="text-xs text-tx3 mt-0.5">Used for high-impact news event reminders sent 30 min before events</p>
            </div>
            {data?.finnhub_api_key_set && (
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cy/10 text-cy border border-cy/20">KEY SET</span>
            )}
          </div>

          <ConfigInput
            label="API Key"
            type="password"
            value={apiKey}
            onChange={setApiKey}
            placeholder="d1a2b3c4d5e6f7…"
            hint="Free tier: 60 calls/min. Get your key at finnhub.io → Dashboard → API Keys."
            action={testKey}
            actionLabel="Test Connection"
            actionLoading={testing}
          />

          <button
            onClick={() => save.mutate()}
            disabled={save.isPending}
            className="px-5 py-2.5 rounded-lg bg-cy text-bg text-xs font-bold tracking-widest hover:bg-cy/90 transition-colors disabled:opacity-50"
          >
            {save.isPending ? 'Saving…' : 'Save Key'}
          </button>
        </div>

        {/* Right: setup guide */}
        <div className="bg-s1 border border-s3 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-tx mb-3">Setup Guide</h3>
          <ol className="space-y-2 text-xs text-tx2 font-mono">
            {[
              'Go to finnhub.io and create a free account',
              'Open the Dashboard → API Keys section',
              'Copy your sandbox or production API key',
              'Paste it above and click Save Key',
              'Click Test Connection — it will show events for today',
              'Users with news_reminder enabled in Settings → Notifications will receive a Telegram alert 30 min before every high-impact economic event',
            ].map((step, i) => (
              <li key={i} className="flex gap-3">
                <span className="text-cy shrink-0">{i + 1}.</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
          <div className="mt-4 px-3 py-2.5 rounded-lg bg-s2 border border-s3">
            <p className="text-[10px] font-mono text-tx3">Free tier limits</p>
            <p className="text-xs text-tx2 mt-0.5">60 API calls/minute · The news task runs every 10 min — 144 calls/day well within the free limit.</p>
          </div>
        </div>

      </div>
    </div>
  )
}


// ─── Telegram Config ──────────────────────────────────────────────────────────

interface BotConfig {
  telegram_bot_token:         string
  telegram_bot_token_set:     boolean
  telegram_signals_channel:   string
  telegram_community_channel: string
  telegram_admin_chat_id:     string
  signals_drop_enabled:       boolean
  results_drop_enabled:       boolean
  notify_on_approve:          boolean
  notify_on_reject:           boolean
  bridge_alerts_enabled:      boolean
  finnhub_api_key:            string
  finnhub_api_key_set:        boolean
  updated_at:                 string | null
}

function Toggle({ value, onChange, label, sub }: { value: boolean; onChange: (v: boolean) => void; label: string; sub?: string }) {
  return (
    <label className="flex items-center justify-between cursor-pointer select-none py-2">
      <div>
        <div className="text-sm text-tx">{label}</div>
        {sub && <div className="text-xs text-tx3 mt-0.5">{sub}</div>}
      </div>
      <div onClick={() => onChange(!value)}
        className={`w-10 h-5 rounded-full transition-colors flex items-center shrink-0 ml-4 ${value ? 'bg-cy' : 'bg-s3'}`}>
        <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform mx-0.5 ${value ? 'translate-x-5' : 'translate-x-0'}`} />
      </div>
    </label>
  )
}

function ConfigInput({
  label, value, onChange, placeholder, type = 'text', hint, action, actionLabel, actionLoading,
}: {
  label: string; value: string; onChange: (v: string) => void
  placeholder?: string; type?: string; hint?: string
  action?: () => void; actionLabel?: string; actionLoading?: boolean
}) {
  const [show, setShow] = useState(false)
  const inputType = type === 'password' ? (show ? 'text' : 'password') : type
  return (
    <div>
      <label className="block text-[10px] font-mono text-tx3 uppercase tracking-widest mb-1.5">{label}</label>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type={inputType}
            value={value}
            onChange={e => onChange(e.target.value)}
            placeholder={placeholder}
            className="w-full bg-s2 border border-s3 rounded-lg px-3 py-2 text-sm text-tx font-mono focus:outline-none focus:border-cy/50 transition-colors pr-10"
          />
          {type === 'password' && (
            <button type="button" onClick={() => setShow(v => !v)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-tx3 hover:text-tx2 text-xs transition-colors">
              {show ? '🙈' : '👁'}
            </button>
          )}
        </div>
        {action && (
          <button
            onClick={action}
            disabled={actionLoading}
            className="px-3 py-2 rounded-lg border border-s3 text-xs font-mono text-tx2 hover:bg-s2 transition-colors disabled:opacity-50 whitespace-nowrap shrink-0"
          >
            {actionLoading ? '…' : actionLabel}
          </button>
        )}
      </div>
      {hint && <p className="text-[10px] text-tx3 font-mono mt-1">{hint}</p>}
    </div>
  )
}

// ─── Branding Config ──────────────────────────────────────────────────────────

function BrandingConfig() {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [appName,  setAppName]  = useState('')
  const [logoUrl,  setLogoUrl]  = useState('')
  const [preview,  setPreview]  = useState('')
  const [feedback, setFeedback] = useState<{ msg: string; ok: boolean } | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['branding'],
    queryFn: () => api.get('/config/branding').then(r => r.data),
  })

  useEffect(() => {
    if (!data) return
    setAppName(data.app_name ?? '')
    setLogoUrl(data.app_logo_url ?? '')
    setPreview(data.app_logo_url ?? '')
  }, [data])

  const notify = (ok: boolean, msg: string) => {
    setFeedback({ ok, msg })
    setTimeout(() => setFeedback(null), 3000)
  }

  const save = useMutation({
    mutationFn: () => api.patch('/admin/config', { app_name: appName, app_logo_url: logoUrl }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['branding'] })
      notify(true, 'Branding saved — changes are live across the app.')
    },
    onError: () => notify(false, 'Failed to save branding'),
  })

  const uploadLogo = async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await api.post('/admin/config/logo', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setLogoUrl(res.data.app_logo_url)
      setPreview(res.data.app_logo_url)
      qc.invalidateQueries({ queryKey: ['branding'] })
      notify(true, 'Logo uploaded successfully.')
    } catch (e: any) {
      notify(false, e?.response?.data?.detail ?? 'Upload failed')
    }
  }

  if (isLoading) return null

  return (
    <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-tx">Branding</h3>
        <p className="text-xs text-tx3 mt-0.5">App name and logo shown in the sidebar and login page</p>
      </div>

      {feedback && (
        <div className={`flex items-center justify-between px-4 py-3 rounded-xl text-xs font-mono ${feedback.ok ? 'bg-cy/5 border border-cy/20 text-cy' : 'bg-rd/5 border border-rd/20 text-rd'}`}>
          <span>{feedback.ok ? '✓' : '✗'} {feedback.msg}</span>
          <button onClick={() => setFeedback(null)} className="opacity-50 hover:opacity-100 ml-4">✕</button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

        {/* App name */}
        <div>
          <label className="block text-[10px] font-mono text-tx3 uppercase tracking-widest mb-1.5">App Name</label>
          <input
            value={appName}
            onChange={e => setAppName(e.target.value)}
            placeholder="Traxovia AI"
            className="w-full bg-s2 border border-s3 rounded-lg px-3 py-2 text-sm text-tx font-mono focus:outline-none focus:border-cy/50 transition-colors"
          />
          <p className="text-[10px] text-tx3 font-mono mt-1">Displayed in sidebar and login page.</p>
        </div>

        {/* Logo */}
        <div>
          <label className="block text-[10px] font-mono text-tx3 uppercase tracking-widest mb-1.5">Logo</label>
          <div className="flex items-center gap-3">

            {/* Preview */}
            <div className="w-12 h-12 rounded-xl flex items-center justify-center shrink-0"
              style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
              {preview
                ? <img src={preview} alt="logo" className="w-10 h-10 object-contain rounded-lg" />
                : <span className="text-tx3 text-xl">⬛</span>
              }
            </div>

            <div className="flex-1 space-y-2">
              {/* Upload file */}
              <button
                onClick={() => fileRef.current?.click()}
                className="w-full px-3 py-2 rounded-lg text-xs font-mono text-tx2 transition-colors text-left"
                style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
                📁 Upload image (PNG/SVG/JPG, max 2 MB)
              </button>
              <input
                ref={fileRef} type="file" accept="image/*" className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) uploadLogo(f) }}
              />
              {/* Or paste URL */}
              <input
                value={logoUrl.startsWith('data:') ? '' : logoUrl}
                onChange={e => { setLogoUrl(e.target.value); setPreview(e.target.value) }}
                placeholder="…or paste image URL"
                className="w-full bg-s2 border border-s3 rounded-lg px-3 py-2 text-xs text-tx font-mono focus:outline-none focus:border-cy/50 transition-colors"
              />
            </div>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3 pt-1">
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="px-5 py-2.5 rounded-lg bg-cy text-bg text-xs font-bold tracking-widest hover:bg-cy/90 transition-colors disabled:opacity-50"
        >
          {save.isPending ? 'Saving…' : 'Save Branding'}
        </button>
        {preview && (
          <button
            onClick={() => { setLogoUrl(''); setPreview('') }}
            className="text-xs font-mono text-rd/60 hover:text-rd transition-colors"
          >
            Remove logo
          </button>
        )}
      </div>
    </div>
  )
}

// ─── Telegram Config ──────────────────────────────────────────────────────────

function TelegramConfig() {
  const qc = useQueryClient()
  const [form, setForm]       = useState<Partial<BotConfig>>({})
  const [botInfo, setBotInfo] = useState<{ username: string; display_name: string } | null>(null)
  const [feedback, setFeedback] = useState<{ msg: string; ok: boolean } | null>(null)
  const [testingChannel, setTestingChannel] = useState<string | null>(null)
  const [testingBot, setTestingBot] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['admin-config'],
    queryFn: () => api.get('/admin/config').then(r => r.data as BotConfig),
  })

  useEffect(() => {
    if (data) setForm(data)
  }, [data])

  const save = useMutation({
    mutationFn: () => api.patch('/admin/config', form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-config'] })
      setFeedback({ msg: 'Configuration saved.', ok: true })
      setTimeout(() => setFeedback(null), 3000)
    },
    onError: (e: any) => setFeedback({ msg: e?.response?.data?.detail ?? 'Save failed.', ok: false }),
  })

  async function testBot() {
    setTestingBot(true)
    setBotInfo(null)
    setFeedback(null)
    try {
      const res = await api.post('/admin/config/test-telegram')
      setBotInfo(res.data)
      setFeedback({ msg: `Connected as @${res.data.username}`, ok: true })
    } catch (e: any) {
      setFeedback({ msg: e?.response?.data?.detail ?? 'Connection failed.', ok: false })
    } finally {
      setTestingBot(false)
    }
  }

  async function testChannel(channel: string) {
    setTestingChannel(channel)
    setFeedback(null)
    try {
      await api.post('/admin/config/test-message', { channel })
      setFeedback({ msg: `Test message sent to ${channel} channel.`, ok: true })
    } catch (e: any) {
      setFeedback({ msg: e?.response?.data?.detail ?? 'Failed to send test message.', ok: false })
    } finally {
      setTestingChannel(null)
    }
  }

  const set = (key: keyof BotConfig) => (v: any) => setForm(p => ({ ...p, [key]: v }))

  if (isLoading) return <p className="text-tx2 text-sm animate-pulse">Loading config…</p>

  return (
    <div className="space-y-4">

      {/* Feedback banner */}
      {feedback && (
        <div className={`flex items-center justify-between px-4 py-3 rounded-xl text-sm font-mono ${feedback.ok ? 'bg-cy/5 border border-cy/20 text-cy' : 'bg-rd/5 border border-rd/20 text-rd'}`}>
          <span>{feedback.ok ? '✓' : '✗'} {feedback.msg}</span>
          <button onClick={() => setFeedback(null)} className="opacity-50 hover:opacity-100 ml-4">✕</button>
        </div>
      )}

      {/* Two-column grid: config left, guide + toggles right */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Left column */}
        <div className="space-y-4">

          {/* Bot Token */}
          <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-tx">Telegram Bot</h3>
                <p className="text-xs text-tx3 mt-0.5">Create a bot via @BotFather and paste the token below</p>
              </div>
              {botInfo && (
                <div className="text-right">
                  <div className="text-xs font-mono text-cy">@{botInfo.username}</div>
                  <div className="text-[10px] text-tx3">{botInfo.display_name}</div>
                </div>
              )}
              {data?.telegram_bot_token_set && !botInfo && (
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cy/10 text-cy border border-cy/20">TOKEN SET</span>
              )}
            </div>

            <ConfigInput
              label="Bot Token"
              type="password"
              value={form.telegram_bot_token ?? ''}
              onChange={set('telegram_bot_token')}
              placeholder="7123456789:AAF••••••••••••••••••••"
              hint="Get this from @BotFather → /newbot. Leave unchanged to keep the existing token."
              action={testBot}
              actionLabel="Test Connection"
              actionLoading={testingBot}
            />
          </div>

          {/* Channel IDs */}
          <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-4">
            <div>
              <h3 className="text-sm font-semibold text-tx">Channel & Chat IDs</h3>
              <p className="text-xs text-tx3 mt-0.5">Add the bot as admin of each channel, then paste the chat ID here</p>
            </div>

            <ConfigInput
              label="Signals Channel ID"
              value={form.telegram_signals_channel ?? ''}
              onChange={set('telegram_signals_channel')}
              placeholder="-1001234567890"
              hint="Used for live signal drops (new trades). Bot must be admin."
              action={() => testChannel('signals')}
              actionLabel="Send Test"
              actionLoading={testingChannel === 'signals'}
            />
            <ConfigInput
              label="Community / Results Channel ID"
              value={form.telegram_community_channel ?? ''}
              onChange={set('telegram_community_channel')}
              placeholder="-1009876543210"
              hint="Used for trade result drops (wins/losses). Can be same channel or different."
              action={() => testChannel('community')}
              actionLabel="Send Test"
              actionLoading={testingChannel === 'community'}
            />
            <ConfigInput
              label="Admin Personal Chat ID"
              value={form.telegram_admin_chat_id ?? ''}
              onChange={set('telegram_admin_chat_id')}
              placeholder="123456789"
              hint="Your personal chat ID for critical alerts (bridge offline, errors). Message @userinfobot to get it."
              action={() => testChannel('admin')}
              actionLabel="Send Test"
              actionLoading={testingChannel === 'admin'}
            />
          </div>

        </div>

        {/* Right column */}
        <div className="space-y-4">

          {/* Broadcast toggles */}
          <div className="bg-s1 border border-s3 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-tx mb-3">Broadcast Settings</h3>
            <div className="divide-y divide-s3">
              <Toggle value={!!form.signals_drop_enabled}  onChange={set('signals_drop_enabled')}  label="Signal Drops"         sub="Post new signals to the Signals channel" />
              <Toggle value={!!form.results_drop_enabled}  onChange={set('results_drop_enabled')}  label="Result Drops"         sub="Post trade closes (win/loss) to the Community channel" />
              <Toggle value={!!form.notify_on_approve}     onChange={set('notify_on_approve')}     label="Notify on Approve"    sub="Notify users when a signal is approved" />
              <Toggle value={!!form.notify_on_reject}      onChange={set('notify_on_reject')}      label="Notify on Reject"     sub="Notify users when a signal is rejected" />
              <Toggle value={!!form.bridge_alerts_enabled} onChange={set('bridge_alerts_enabled')} label="Bridge Offline Alerts" sub="Send critical alerts to admin when MT5 bridge goes offline" />
            </div>
          </div>

          {/* Setup guide */}
          <div className="bg-s1 border border-s3 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-tx mb-3">Setup Guide</h3>
            <ol className="space-y-2 text-xs text-tx2 font-mono">
              {[
                'Open Telegram → search @BotFather → send /newbot',
                'Give your bot a name and username (e.g. tradingai_bot)',
                'Copy the token and paste it above → click Test Connection',
                'Create a channel or group in Telegram',
                'Add your bot as Admin with "Post Messages" permission',
                'Send a message in the channel, then run: curl "https://api.telegram.org/bot<TOKEN>/getUpdates" to get the chat ID',
                'Paste the chat ID above → click Send Test to verify',
                'Enable the broadcasts you want and click Save',
              ].map((step, i) => (
                <li key={i} className="flex gap-3">
                  <span className="text-cy shrink-0">{i + 1}.</span>
                  <span>{step}</span>
                </li>
              ))}
            </ol>
          </div>

        </div>
      </div>

      {/* Save */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="px-5 py-2.5 rounded-lg bg-cy text-bg text-xs font-bold tracking-widest hover:bg-cy/90 transition-colors disabled:opacity-50"
        >
          {save.isPending ? 'Saving…' : 'Save Configuration'}
        </button>
        {data?.updated_at && (
          <span className="text-[10px] text-tx3 font-mono">
            Last saved: {new Date(data.updated_at).toLocaleString()}
          </span>
        )}
      </div>
    </div>
  )
}

// ─── Backup Tab ───────────────────────────────────────────────────────────────

interface BackupFile {
  filename:   string
  size:       number
  created_at: string
}

function fmtBytes(b: number): string {
  if (b > 1e9) return (b / 1e9).toFixed(2) + ' GB'
  if (b > 1e6) return (b / 1e6).toFixed(2) + ' MB'
  if (b > 1e3) return (b / 1e3).toFixed(1) + ' KB'
  return b + ' B'
}

function BackupTab() {
  const qc = useQueryClient()
  const [creating,  setCreating]  = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [scope,     setScope]     = useState('trading_data')
  const [confirmTx, setConfirmTx] = useState('')
  const [clearing,  setClearing]  = useState(false)
  const [feedback,  setFeedback]  = useState<{ ok: boolean; msg: string } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const notify = (ok: boolean, msg: string) => {
    setFeedback({ ok, msg })
    setTimeout(() => setFeedback(null), 5000)
  }

  const { data: backups, isLoading } = useQuery({
    queryKey: ['admin-backups'],
    queryFn: () => api.get('/admin/backup/list').then(r => r.data as BackupFile[]),
  })

  async function createBackup() {
    setCreating(true)
    try {
      const res = await api.post('/admin/backup/create')
      qc.invalidateQueries({ queryKey: ['admin-backups'] })
      notify(true, `Backup created: ${res.data.filename} (${fmtBytes(res.data.size)})`)
    } catch (e: any) {
      notify(false, e?.response?.data?.detail ?? 'Backup failed')
    } finally {
      setCreating(false)
    }
  }

  async function deleteBackup(filename: string) {
    if (!confirm(`Delete backup "${filename}"?`)) return
    try {
      await api.delete(`/admin/backup/${filename}`)
      qc.invalidateQueries({ queryKey: ['admin-backups'] })
      notify(true, 'Backup deleted')
    } catch (e: any) {
      notify(false, e?.response?.data?.detail ?? 'Delete failed')
    }
  }

  async function restoreFile(file: File) {
    if (!confirm(`Restore from "${file.name}"? This will overwrite existing data.`)) return
    setRestoring(true)
    try {
      const form = new FormData()
      form.append('file', file)
      await api.post('/admin/backup/restore', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      notify(true, `Restore from "${file.name}" completed.`)
    } catch (e: any) {
      notify(false, e?.response?.data?.detail ?? 'Restore failed')
    } finally {
      setRestoring(false)
    }
  }

  async function clearData() {
    if (confirmTx !== 'CONFIRM') return
    setClearing(true)
    try {
      const res = await api.post('/admin/backup/clear', { scope, confirm: 'CONFIRM' })
      notify(true, `Cleared: ${res.data.tables.join(', ')}`)
      setConfirmTx('')
    } catch (e: any) {
      notify(false, e?.response?.data?.detail ?? 'Clear failed')
    } finally {
      setClearing(false)
    }
  }

  const scopeLabels: Record<string, string> = {
    trading_data: 'Trading Data (trades + signals)',
    audit_log:    'Audit Log only',
    all_data:     'All Data (trades + signals + audit log)',
  }

  return (
    <div className="space-y-5">
      {feedback && (
        <div className={`flex items-center justify-between px-4 py-3 rounded-xl text-sm font-mono ${feedback.ok ? 'bg-cy/5 border border-cy/20 text-cy' : 'bg-rd/5 border border-rd/20 text-rd'}`}>
          <span>{feedback.ok ? '✓' : '✗'} {feedback.msg}</span>
          <button onClick={() => setFeedback(null)} className="opacity-50 hover:opacity-100 ml-4">✕</button>
        </div>
      )}

      {/* Create backup */}
      <div className="bg-s1 border border-s3 rounded-xl p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-sm font-semibold text-tx">Create Backup</h3>
            <p className="text-xs text-tx3 mt-0.5">Runs pg_dump and saves a .sql file on the server</p>
          </div>
          <button
            onClick={createBackup}
            disabled={creating}
            className="px-4 py-2 rounded-lg bg-cy text-bg text-xs font-bold tracking-widest hover:bg-cy/90 transition-colors disabled:opacity-50"
          >
            {creating ? 'Creating…' : '↓ Create Backup'}
          </button>
        </div>
        <div className="text-[10px] font-mono text-tx3 px-3 py-2 rounded-lg bg-s3">
          Backups stored in: <span className="text-tx2">./backups/</span> on the server.
          Download files from the list below.
        </div>
      </div>

      {/* Backup list */}
      <div className="bg-s1 border border-s3 rounded-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-s3">
          <span className="text-[10px] font-mono text-tx3 uppercase tracking-widest">Saved Backups</span>
          <span className="text-[10px] font-mono text-tx3">{backups?.length ?? 0} files</span>
        </div>
        {isLoading && <p className="px-5 py-4 text-tx2 text-sm animate-pulse">Loading…</p>}
        {!isLoading && (!backups || backups.length === 0) && (
          <p className="px-5 py-6 text-center text-tx3 text-sm">No backups yet — create one above.</p>
        )}
        {backups?.map(b => (
          <div key={b.filename} className="flex items-center gap-3 px-5 py-3 border-b border-s3 last:border-0 hover:bg-s2/50 transition-colors">
            <div className="flex-1 min-w-0">
              <p className="text-sm text-tx font-mono truncate">{b.filename}</p>
              <p className="text-[11px] text-tx3 mt-0.5">
                {fmtBytes(b.size)} · {new Date(b.created_at).toLocaleString()}
              </p>
            </div>
            <a
              href={`/api/admin/backup/download/${b.filename}`}
              download={b.filename}
              className="px-3 py-1.5 rounded-lg border border-s3 text-xs font-mono text-cy hover:bg-s3 transition-colors"
            >
              ↓ Download
            </a>
            <button
              onClick={() => deleteBackup(b.filename)}
              className="px-3 py-1.5 rounded-lg border border-rd/20 text-xs font-mono text-rd/60 hover:text-rd hover:bg-rd/5 transition-colors"
            >
              Delete
            </button>
          </div>
        ))}
      </div>

      {/* Restore */}
      <div className="bg-s1 border border-s3 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-tx mb-1">Restore from File</h3>
        <p className="text-xs text-tx3 mb-4">Upload a .sql file previously exported by pg_dump. This pipes it through psql — existing data may be overwritten.</p>
        <input
          ref={fileRef} type="file" accept=".sql" className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) restoreFile(f) }}
        />
        <button
          onClick={() => fileRef.current?.click()}
          disabled={restoring}
          className="px-4 py-2 rounded-lg border border-gd/30 text-gd text-xs font-mono hover:bg-gd/5 transition-colors disabled:opacity-50"
        >
          {restoring ? 'Restoring…' : '↑ Upload & Restore .sql'}
        </button>
      </div>

      {/* Clear database */}
      <div className="bg-s1 border border-rd/20 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-rd text-sm">⚠</span>
          <h3 className="text-sm font-semibold text-rd">Clear Database</h3>
        </div>
        <p className="text-xs text-tx3 mb-4">
          Permanently truncate selected tables. <strong className="text-tx">Users, config, and billing are never touched.</strong> Always create a backup first.
        </p>
        <div className="space-y-3">
          <div>
            <label className="text-[10px] font-mono text-tx3 uppercase tracking-widest block mb-1.5">Scope</label>
            <select
              value={scope}
              onChange={e => setScope(e.target.value)}
              className="w-full bg-s2 border border-s3 rounded-lg px-3 py-2 text-sm text-tx focus:outline-none focus:border-rd/40 transition-colors"
            >
              {Object.entries(scopeLabels).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[10px] font-mono text-tx3 uppercase tracking-widest block mb-1.5">
              Type CONFIRM to unlock
            </label>
            <input
              value={confirmTx}
              onChange={e => setConfirmTx(e.target.value)}
              placeholder="CONFIRM"
              className="w-full bg-s2 border border-s3 rounded-lg px-3 py-2 text-sm text-tx font-mono focus:outline-none focus:border-rd/40 transition-colors"
            />
          </div>
          <button
            onClick={clearData}
            disabled={clearing || confirmTx !== 'CONFIRM'}
            className="px-4 py-2 rounded-lg bg-rd text-white text-xs font-bold tracking-widest hover:bg-rd/80 transition-colors disabled:opacity-40"
          >
            {clearing ? 'Clearing…' : 'Clear Selected Data'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Info / Maintenance Tab ───────────────────────────────────────────────────

interface SystemInfo {
  python:       string
  platform:     string
  postgres:     string
  db_name:      string
  db_size:      string
  db_size_bytes: number
  tables:       { name: string; pretty_size: string; size_bytes: number }[]
  row_counts:   Record<string, number>
  disk:         { total_gb: number; used_gb: number; free_gb: number; used_pct: number }
  backups:      { count: number; size_mb: number }
}

function InfoBar({ pct, color = 'var(--color-cy)' }: { pct: number; color?: string }) {
  return (
    <div className="h-1.5 rounded-full overflow-hidden mt-1" style={{ background: 'var(--color-s3)' }}>
      <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, pct)}%`, background: color }} />
    </div>
  )
}

function InfoTab() {
  const [vacuuming,   setVacuuming]   = useState(false)
  const [reindexing,  setReindexing]  = useState(false)
  const [feedback,    setFeedback]    = useState<{ ok: boolean; msg: string } | null>(null)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['admin-system-info'],
    queryFn: () => api.get('/admin/system/info').then(r => r.data as SystemInfo),
    refetchInterval: 60_000,
  })

  const notify = (ok: boolean, msg: string) => {
    setFeedback({ ok, msg })
    setTimeout(() => setFeedback(null), 5000)
  }

  async function runVacuum() {
    setVacuuming(true)
    try {
      const res = await api.post('/admin/system/vacuum')
      notify(true, res.data.message)
    } catch (e: any) {
      notify(false, e?.response?.data?.detail ?? 'Vacuum failed')
    } finally {
      setVacuuming(false)
    }
  }

  async function runReindex() {
    setReindexing(true)
    try {
      const res = await api.post('/admin/system/reindex')
      notify(true, `Reindexed ${res.data.reindexed?.length ?? 0} tables`)
    } catch (e: any) {
      notify(false, e?.response?.data?.detail ?? 'Reindex failed')
    } finally {
      setReindexing(false)
    }
  }

  if (isLoading) return <p className="text-tx2 text-sm animate-pulse">Loading system info…</p>
  if (!data)     return <p className="text-rd text-sm">Failed to load system info.</p>

  const diskColor = data.disk.used_pct > 85 ? '#e8544f' : data.disk.used_pct > 65 ? '#f0b429' : 'var(--color-cy)'

  return (
    <div className="space-y-5">
      {feedback && (
        <div className={`flex items-center justify-between px-4 py-3 rounded-xl text-sm font-mono ${feedback.ok ? 'bg-cy/5 border border-cy/20 text-cy' : 'bg-rd/5 border border-rd/20 text-rd'}`}>
          <span>{feedback.ok ? '✓' : '✗'} {feedback.msg}</span>
          <button onClick={() => setFeedback(null)} className="opacity-50 hover:opacity-100 ml-4">✕</button>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">

        {/* System + DB info */}
        <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-tx">System</h3>
            <button onClick={() => refetch()} className="text-[10px] font-mono text-tx3 hover:text-tx2 transition-colors">↻ Refresh</button>
          </div>

          {[
            { label: 'Python',     value: data.python },
            { label: 'Platform',   value: data.platform },
            { label: 'PostgreSQL', value: data.postgres },
            { label: 'Database',   value: data.db_name },
            { label: 'DB Size',    value: data.db_size },
          ].map(row => (
            <div key={row.label} className="flex items-center justify-between py-2 border-b border-s3 last:border-0">
              <span className="text-xs text-tx2">{row.label}</span>
              <span className="text-xs font-mono text-tx">{row.value}</span>
            </div>
          ))}
        </div>

        {/* Disk + Backups */}
        <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-semibold text-tx">Disk & Backups</h3>

          <div>
            <div className="flex justify-between text-xs mb-1">
              <span className="text-tx2">Disk Used</span>
              <span className="font-mono" style={{ color: diskColor }}>
                {data.disk.used_gb} GB / {data.disk.total_gb} GB ({data.disk.used_pct}%)
              </span>
            </div>
            <InfoBar pct={data.disk.used_pct} color={diskColor} />
            <p className="text-[10px] text-tx3 font-mono mt-1">{data.disk.free_gb} GB free</p>
          </div>

          <div className="flex items-center justify-between py-2 border-t border-s3">
            <span className="text-xs text-tx2">Saved Backups</span>
            <span className="text-xs font-mono text-tx">{data.backups.count} files · {data.backups.size_mb} MB</span>
          </div>

          <div className="space-y-1 pt-1 border-t border-s3">
            <p className="text-[10px] font-mono text-tx3 uppercase tracking-widest mb-2">Key Row Counts</p>
            {Object.entries(data.row_counts).map(([tbl, cnt]) => (
              <div key={tbl} className="flex justify-between text-xs">
                <span className="text-tx2 font-mono">{tbl}</span>
                <span className="text-tx font-mono">{cnt >= 0 ? cnt.toLocaleString() : '—'}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Table sizes */}
      <div className="bg-s1 border border-s3 rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-s3">
          <span className="text-[10px] font-mono text-tx3 uppercase tracking-widest">Table Sizes</span>
        </div>
        <div className="divide-y divide-s3">
          {data.tables.map(t => {
            const pct = data.db_size_bytes > 0 ? (t.size_bytes / data.db_size_bytes) * 100 : 0
            return (
              <div key={t.name} className="px-5 py-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-mono text-tx">{t.name}</span>
                  <span className="text-[11px] font-mono text-tx2">{t.pretty_size}</span>
                </div>
                <InfoBar pct={pct} />
              </div>
            )
          })}
        </div>
      </div>

      {/* Maintenance */}
      <div className="bg-s1 border border-s3 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-tx mb-1">Maintenance</h3>
        <p className="text-xs text-tx3 mb-4">Run these periodically to keep the database healthy. VACUUM reclaims space; REINDEX rebuilds bloated indexes.</p>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={runVacuum}
            disabled={vacuuming}
            className="px-4 py-2 rounded-lg border border-cy/30 text-cy text-xs font-mono hover:bg-cy/5 transition-colors disabled:opacity-50"
          >
            {vacuuming ? 'Running…' : '⟳ VACUUM ANALYZE'}
          </button>
          <button
            onClick={runReindex}
            disabled={reindexing}
            className="px-4 py-2 rounded-lg border border-s3 text-tx2 text-xs font-mono hover:bg-s2 transition-colors disabled:opacity-50"
          >
            {reindexing ? 'Running…' : '⟳ REINDEX All Tables'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main AdminPanel ──────────────────────────────────────────────────────────

type Tab = 'overview' | 'users' | 'plans' | 'audit' | 'config' | 'backup' | 'info'

export default function AdminPanel() {
  const [tab, setTab] = useState<Tab>('overview')


  const { data: stats } = useQuery({
    queryKey: ['admin-stats'],
    queryFn: () => api.get('/admin/stats').then(r => r.data as Stats),
    refetchInterval: 60_000,
  })

  const { data: plans } = useQuery({
    queryKey: ['admin-plans'],
    queryFn: () => api.get('/admin/plans').then(r => r.data as PlanConfig[]),
  })

  const planColorMap = Object.fromEntries((plans ?? []).map(p => [p.plan_id, p.color]))

  const tabs: { key: Tab; icon: string; label: string; short: string }[] = [
    { key: 'overview', icon: '◈', label: 'Overview',    short: 'Overview' },
    { key: 'users',    icon: '◉', label: 'Users',       short: 'Users'    },
    { key: 'plans',    icon: '◇', label: 'Plans',       short: 'Plans'    },
    { key: 'audit',    icon: '≡', label: 'Audit Log',   short: 'Audit'    },
    { key: 'config',   icon: '⚙', label: 'Config',      short: 'Config'   },
    { key: 'backup',   icon: '↓', label: 'Backup',      short: 'Backup'   },
    { key: 'info',     icon: 'ℹ', label: 'System Info', short: 'System'   },
  ]

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 text-lg"
          style={{ background: 'rgba(212,168,83,0.12)', border: '1px solid rgba(212,168,83,0.25)', color: 'var(--color-cy)' }}>
          ◈
        </div>
        <div className="min-w-0">
          <h1 className="text-xl font-bold text-tx font-head flex items-center gap-2 flex-wrap">
            Admin Panel
            <span className="px-2 py-0.5 rounded text-[11px] font-bold uppercase tracking-wide bg-cy/15 text-cy border border-cy/30">
              superuser
            </span>
          </h1>
          <p className="text-tx2 text-sm mt-0.5">Platform management and monitoring</p>
        </div>
      </div>

      {/* Tab bar */}
      <div className="bg-s1 border border-s3 rounded-xl p-1">
        {/* Mobile: icon-only scrollable row */}
        <div className="flex sm:hidden gap-1 overflow-x-auto">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              title={t.label}
              className={`shrink-0 flex flex-col items-center gap-0.5 px-3 py-2 rounded-lg transition-colors ${
                tab === t.key ? 'bg-cy text-bg' : 'text-tx2 hover:text-tx hover:bg-s2'
              }`}
            >
              <span className="text-base leading-none">{t.icon}</span>
              <span className="text-[9px] font-bold tracking-wide whitespace-nowrap">{t.short}</span>
            </button>
          ))}
        </div>
        {/* sm+: full label row */}
        <div className="hidden sm:flex gap-1">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold transition-colors ${
                tab === t.key ? 'bg-cy text-bg' : 'text-tx2 hover:text-tx hover:bg-s2'
              }`}
            >
              <span className="text-sm leading-none">{t.icon}</span>
              <span>{t.short}</span>
            </button>
          ))}
        </div>
      </div>

      {/* ── Overview ── */}
      {tab === 'overview' && stats && (
        <div className="space-y-6">
          {/* User stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard label="Total Users"    value={stats.users.total_users} />
            <StatCard label="New This Week"  value={stats.users.new_this_week} />
            <StatCard label="New This Month" value={stats.users.new_this_month} />
            <StatCard label="Admin Accounts" value={stats.users.admin_count} />
          </div>

          {/* Revenue + Trades */}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <StatCard
              label="Monthly Recurring Revenue"
              value={`$${stats.revenue?.mrr?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '0.00'}`}
              sub="sum of active paid plans"
            />
            <StatCard label="Total Trades"  value={stats.trades?.total_trades ?? 0} />
            <StatCard label="Open Trades"   value={stats.trades?.open_trades  ?? 0} />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Plan distribution */}
            <div className="bg-s1 border border-s3 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-tx mb-4">Plan Distribution</h3>
              <div className="space-y-2">
                {stats.plan_distribution.map(d => {
                  const pct   = stats.users.total_users > 0
                    ? Math.round((Number(d.count) / stats.users.total_users) * 100)
                    : 0
                  const color = planColorMap[d.plan] ?? '#8899b4'
                  return (
                    <div key={d.plan} className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="capitalize text-tx">{d.plan}</span>
                        <span className="text-tx2">{d.count} ({pct}%)</span>
                      </div>
                      <div className="h-1.5 bg-s3 rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{ width: `${pct}%`, background: color }}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Signal stats */}
            <div className="bg-s1 border border-s3 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-tx mb-4">Signal Statistics</h3>
              <div className="grid grid-cols-2 gap-3">
                <StatCard label="Total"    value={stats.signals.total_signals} />
                <StatCard label="Pending"  value={stats.signals.pending} />
                <StatCard label="Approved" value={stats.signals.approved} />
                <StatCard label="Rejected" value={stats.signals.rejected} />
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'users'    && <UsersTable />}
      {tab === 'plans'    && <PlansEditor />}
      {tab === 'audit'    && <AuditLog />}
      {tab === 'config'   && (
        <div className="space-y-6">
          <FeatureFlagsPanel />
          <BrandingConfig />
          <TelegramConfig />
          <FinnhubConfig />
          <div className="border-t border-s3 pt-6">
            <div className="mb-4">
              <h2 className="text-base font-bold text-tx font-head">Email Configuration</h2>
              <p className="text-xs text-tx3 mt-0.5">SMTP settings for transactional emails</p>
            </div>
            <EmailConfig />
          </div>
          <div className="border-t border-s3 pt-6">
            <div className="mb-4">
              <h2 className="text-base font-bold text-tx font-head">Payment Gateway</h2>
              <p className="text-xs text-tx3 mt-0.5">Stripe or Paystack — switch at any time, keys are stored securely in the database</p>
            </div>
            <PaymentConfig />
          </div>
        </div>
      )}
      {tab === 'backup' && <BackupTab />}
      {tab === 'info'   && <InfoTab />}
    </div>
  )
}
