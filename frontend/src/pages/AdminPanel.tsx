import { useState } from 'react'
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
  updated_at: string
  stripe_customer_id: string | null
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

// ─── Plan badge colours ───────────────────────────────────────────────────────

const planColor: Record<string, string> = {
  community: 'bg-s3 text-tx2',
  starter:   'bg-sky-900/40 text-sky-300',
  trader:    'bg-indigo-900/40 text-indigo-300',
  pro:       'bg-violet-900/40 text-violet-300',
  elite:     'bg-amber-900/40 text-amber-300',
  trial:     'bg-green-900/40 text-green-300',
}

function PlanBadge({ plan }: { plan: string }) {
  return (
    <span className={`px-2 py-0.5 rounded text-[11px] font-semibold uppercase tracking-wide ${planColor[plan] ?? 'bg-s3 text-tx2'}`}>
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

// ─── Sub-sections ─────────────────────────────────────────────────────────────

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="bg-s1 border border-s3 rounded-xl p-5 flex flex-col gap-1">
      <p className="text-tx2 text-xs uppercase tracking-widest">{label}</p>
      <p className="text-3xl font-bold text-tx font-head">{value}</p>
      {sub && <p className="text-tx2 text-xs">{sub}</p>}
    </div>
  )
}

// ─── Edit Plan Modal ──────────────────────────────────────────────────────────

const PLANS = ['community', 'starter', 'trader', 'pro', 'elite', 'trial']

function EditUserModal({
  user,
  onClose,
}: {
  user: User
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [plan, setPlan] = useState(user.plan)
  const [isAdmin, setIsAdmin] = useState(user.is_admin)

  const patch = useMutation({
    mutationFn: (body: { plan?: string; is_admin?: boolean }) =>
      api.patch(`/admin/users/${user.id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      onClose()
    },
  })

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
              onChange={e => setPlan(e.target.value)}
              className="w-full bg-s2 border border-s3 rounded-lg px-3 py-2.5 text-sm text-tx focus:outline-none focus:border-cy/50 transition-colors"
            >
              {PLANS.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          <label className="flex items-center gap-3 cursor-pointer select-none">
            <div
              onClick={() => setIsAdmin(v => !v)}
              className={`w-10 h-5 rounded-full transition-colors flex items-center ${isAdmin ? 'bg-cy' : 'bg-s3'}`}
            >
              <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform mx-0.5 ${isAdmin ? 'translate-x-5' : 'translate-x-0'}`} />
            </div>
            <span className="text-sm text-tx">Admin access</span>
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
            onClick={() => patch.mutate({ plan, is_admin: isAdmin })}
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
  const [editUser, setEditUser] = useState<User | null>(null)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin-users'],
    queryFn: () => api.get('/admin/users?limit=100').then(r => r.data as { total: number; users: User[] }),
  })

  if (isLoading) return <p className="text-tx2 text-sm animate-pulse">Loading users…</p>
  if (isError)   return <p className="text-rd text-sm">Failed to load users.</p>

  return (
    <>
      {editUser && <EditUserModal user={editUser} onClose={() => setEditUser(null)} />}
      <div className="overflow-x-auto rounded-xl border border-s3">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-s2 text-tx2 text-xs uppercase tracking-wide">
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Plan</th>
              <th className="text-left px-4 py-3">Role</th>
              <th className="text-left px-4 py-3">Joined</th>
              <th className="text-left px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-s3">
            {data?.users.map(u => (
              <tr key={u.id} className="hover:bg-s2/50 transition-colors">
                <td className="px-4 py-3 text-tx font-mono text-xs">{u.email}</td>
                <td className="px-4 py-3"><PlanBadge plan={u.plan} /></td>
                <td className="px-4 py-3">
                  {u.is_admin ? <AdminBadge /> : <span className="text-tx2 text-xs">user</span>}
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
        <div className="px-4 py-2 bg-s2 text-tx2 text-xs border-t border-s3">
          {data?.total ?? 0} total users
        </div>
      </div>
    </>
  )
}

// ─── Audit Log ────────────────────────────────────────────────────────────────

function AuditLog() {
  const { data, isLoading } = useQuery({
    queryKey: ['admin-audit'],
    queryFn: () => api.get('/admin/audit?limit=50').then(r => r.data as { entries: AuditEntry[] }),
  })

  if (isLoading) return <p className="text-tx2 text-sm animate-pulse">Loading audit log…</p>

  return (
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
              <td className="px-4 py-2.5 text-tx font-mono truncate max-w-[180px]">{e.email}</td>
              <td className="px-4 py-2.5">
                <span className="px-2 py-0.5 rounded bg-s3 text-cy font-semibold">{e.action}</span>
              </td>
              <td className="px-4 py-2.5 text-tx2 truncate max-w-[240px]">{e.detail ?? '—'}</td>
              <td className="px-4 py-2.5 text-tx2 font-mono">{e.ip_address ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── Main AdminPanel page ─────────────────────────────────────────────────────

type Tab = 'overview' | 'users' | 'audit'

export default function AdminPanel() {
  const [tab, setTab] = useState<Tab>('overview')

  const { data: stats } = useQuery({
    queryKey: ['admin-stats'],
    queryFn: () => api.get('/admin/stats').then(r => r.data as Stats),
  })

  const tabs: { key: Tab; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'users',    label: 'Users' },
    { key: 'audit',    label: 'Audit Log' },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div>
          <h1 className="text-xl font-bold text-tx font-head flex items-center gap-2">
            Admin Panel
            <span className="px-2 py-0.5 rounded text-[11px] font-bold uppercase tracking-wide bg-cy/15 text-cy border border-cy/30">
              superuser
            </span>
          </h1>
          <p className="text-tx2 text-sm mt-0.5">Platform management and monitoring</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-s1 border border-s3 rounded-xl p-1 w-fit">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              tab === t.key
                ? 'bg-cy text-bg'
                : 'text-tx2 hover:text-tx hover:bg-s2'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Overview */}
      {tab === 'overview' && stats && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard label="Total Users"    value={stats.users.total_users} />
            <StatCard label="New This Week"  value={stats.users.new_this_week} />
            <StatCard label="New This Month" value={stats.users.new_this_month} />
            <StatCard label="Admin Accounts" value={stats.users.admin_count} />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Plan distribution */}
            <div className="bg-s1 border border-s3 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-tx mb-4">Plan Distribution</h3>
              <div className="space-y-2">
                {stats.plan_distribution.map(d => {
                  const pct = stats.users.total_users > 0
                    ? Math.round((Number(d.count) / stats.users.total_users) * 100)
                    : 0
                  return (
                    <div key={d.plan} className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="capitalize text-tx">{d.plan}</span>
                        <span className="text-tx2">{d.count} ({pct}%)</span>
                      </div>
                      <div className="h-1.5 bg-s3 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-cy rounded-full transition-all"
                          style={{ width: `${pct}%` }}
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

      {/* Users */}
      {tab === 'users' && <UsersTable />}

      {/* Audit Log */}
      {tab === 'audit' && <AuditLog />}
    </div>
  )
}
