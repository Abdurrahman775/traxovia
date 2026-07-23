import { useState, useEffect } from 'react'
import api from '../api/client'

interface AuditEntry {
  id: number
  created_at: string
  action: string
  detail: string
  ip_address: string
}

export default function AuditLog() {
  const [entries,  setEntries] = useState<AuditEntry[]>([])
  const [loading,  setLoading] = useState(true)
  const [page,     setPage]    = useState(1)
  const [hasMore,  setHasMore] = useState(true)

  useEffect(() => { fetchEntries(1) }, [])

  const fetchEntries = async (p: number) => {
    try {
      const res  = await api.get(`/audit?page=${p}&page_size=20`)
      const data = res.data
      if (p === 1) setEntries(data.entries)
      else setEntries(prev => [...prev, ...data.entries])
      setHasMore(data.page * 20 < data.total)
      setPage(p)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <p className="text-tx2 text-sm animate-pulse">Loading…</p>

  return (
    <div className="space-y-4">

      <div>
        <h1 className="text-xl font-bold text-tx font-head">Audit Log</h1>
        <p className="text-tx2 text-sm mt-0.5">Every action on your account — immutable and read-only</p>
      </div>

      <div className="flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-mono"
        style={{ background: 'rgba(212,168,83,0.06)', border: '1px solid rgba(212,168,83,0.18)', color: 'var(--color-cy)' }}>
        ◈ All entries are permanent and cannot be edited or deleted.
      </div>

      <div className="rounded-xl overflow-hidden" style={{ border: '1px solid var(--color-card-border)' }}>
        <div className="px-4 py-3 text-[10px] font-mono tracking-widest uppercase"
          style={{ background: 'var(--color-s2)', borderBottom: '1px solid var(--color-card-border)', color: 'var(--color-tx3)' }}>
          Account Audit Log
        </div>
        <div style={{ background: 'var(--color-s1)' }} className="tbl-scroll">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] font-mono tracking-wide uppercase"
                style={{ background: 'var(--color-s2)', borderBottom: '1px solid var(--color-card-border)', color: 'var(--color-tx3)' }}>
                {['Timestamp', 'Action', 'Detail', 'IP'].map(h => (
                  <th key={h} className="text-left py-2.5 px-4">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map((e, i) => (
                <tr key={e.id}
                  className="transition-colors"
                  style={{
                    borderBottom: '1px solid var(--color-divider)',
                    background: i % 2 === 0 ? 'transparent' : 'var(--color-hover-bg)',
                  }}
                  onMouseEnter={ev => (ev.currentTarget.style.background = 'var(--color-s2)')}
                  onMouseLeave={ev => (ev.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'var(--color-hover-bg)')}
                >
                  <td className="py-2.5 px-4 font-mono text-xs" style={{ color: 'var(--color-tx3)' }}>
                    {new Date(e.created_at).toLocaleString()}
                  </td>
                  <td className="py-2.5 px-4">
                    <span className="px-2 py-0.5 rounded text-[11px] font-mono font-semibold"
                      style={{ background: 'rgba(212,168,83,0.08)', color: 'var(--color-cy)', border: '1px solid rgba(212,168,83,0.18)' }}>
                      {e.action}
                    </span>
                  </td>
                  <td className="py-2.5 px-4 text-xs" style={{ color: 'var(--color-tx2)' }}>{e.detail || '—'}</td>
                  <td className="py-2.5 px-4 font-mono text-xs" style={{ color: 'var(--color-tx3)' }}>{e.ip_address || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {entries.length === 0 && (
            <div className="py-12 text-center text-tx3 text-sm font-mono">No entries yet</div>
          )}

          {hasMore && (
            <div className="px-4 py-3" style={{ borderTop: '1px solid var(--color-card-border)' }}>
              <button onClick={() => fetchEntries(page + 1)}
                className="w-full py-2 rounded-lg text-xs font-mono transition-colors text-tx2 hover:text-tx"
                style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
                Load more
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
