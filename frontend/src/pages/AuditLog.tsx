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
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(true)

  useEffect(() => { fetchEntries(1) }, [])

  const fetchEntries = async (p: number) => {
    try {
      const res = await api.get(`/audit?page=${p}&page_size=20`)
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

  if (loading) return <div className="text-gray-400">Loading...</div>

  return (
    <div className="space-y-4">
      <div className="bg-cyan-400/10 border border-cyan-400/20 rounded-lg p-3 font-mono text-xs text-cyan-400">
        Every action on your account is logged permanently. Read-only — cannot be altered.
      </div>
      <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
        <div className="text-xs text-gray-500 font-mono mb-4">ACCOUNT AUDIT LOG — IMMUTABLE</div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-gray-500 font-mono border-b border-slate-700">
              {['Timestamp', 'Action', 'Detail', 'IP'].map(h => (
                <th key={h} className="text-left py-2 px-3">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map(e => (
              <tr key={e.id} className="border-b border-slate-700/30 hover:bg-slate-700/20">
                <td className="py-2.5 px-3 font-mono text-xs text-gray-500">{new Date(e.created_at).toLocaleString()}</td>
                <td className="py-2.5 px-3 text-gray-200">{e.action}</td>
                <td className="py-2.5 px-3 text-xs text-gray-400">{e.detail}</td>
                <td className="py-2.5 px-3 font-mono text-xs text-gray-500">{e.ip_address}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {hasMore && (
          <button onClick={() => fetchEntries(page + 1)}
            className="mt-4 w-full py-2 bg-slate-700/50 border border-slate-600 rounded text-xs font-mono hover:bg-slate-700">
            Load More
          </button>
        )}
      </div>
    </div>
  )
}
