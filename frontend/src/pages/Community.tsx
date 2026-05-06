import { useState, useEffect } from 'react'
import api from '../api/client'

interface CommunityStats {
  members: number
  signal_drops: number
  result_drops: number
  conversion_rate: number
}

interface ResultDrop {
  id: number
  pair: string
  direction: string
  pnl_r: number
  created_at: string
}

export default function Community() {
  const [stats, setStats] = useState<CommunityStats | null>(null)
  const [drops, setDrops] = useState<ResultDrop[]>([])
  const [dropping, setDropping] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    try {
      const [statsRes, dropsRes] = await Promise.all([
        api.get('/community/stats'),
        api.get('/community/drops'),
      ])
      setStats(statsRes.data)
      setDrops(dropsRes.data)
    } catch (err) {
      console.error(err)
    }
  }

  const dropSignal = async () => {
    setDropping(true)
    try {
      await api.post('/community/drop-signal', {}, {
      })
      setMsg('Signal dropped to community channel')
      fetchData()
    } catch (err) {
      setMsg('Failed to drop signal')
    } finally {
      setDropping(false)
      setTimeout(() => setMsg(''), 3000)
    }
  }

  const dropResult = async () => {
    try {
      await api.post('/community/drop-result', {}, {
      })
      setMsg('Result dropped to community channel')
      fetchData()
    } catch (err) {
      setMsg('Failed to drop result')
    } finally {
      setTimeout(() => setMsg(''), 3000)
    }
  }

  return (
    <div className="space-y-4">
      {msg && (
        <div className="bg-cyan-400/10 border border-cyan-400/20 rounded-lg p-3 font-mono text-xs text-cyan-400">
          {msg}
        </div>
      )}

      <div className="grid grid-cols-4 gap-3">
        {[
          { l: 'Members', v: stats?.members ?? 0 },
          { l: 'Signal Drops', v: stats?.signal_drops ?? 0 },
          { l: 'Result Drops', v: stats?.result_drops ?? 0 },
          { l: 'Conversion', v: stats ? `${stats.conversion_rate}%` : '0%' },
        ].map(m => (
          <div key={m.l} className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
            <div className="text-xs text-gray-500 font-mono mb-2">{m.l.toUpperCase()}</div>
            <div className="text-2xl font-bold text-cyan-400">{m.v}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-3">DROP SIGNAL + RESULT</div>
          <div className="bg-cyan-400/10 border border-cyan-400/20 rounded p-3 mb-3 font-mono text-xs text-cyan-400">
            RESULT DROPS ACTIVE — When a signal closes, result auto-posted to channel.
          </div>
          <div className="bg-slate-900/50 rounded-lg p-3 mb-4 font-mono text-xs text-gray-400 leading-relaxed">
            Signal Drop:<br />
            EUR/USD BUY | Entry: ~1.0840<br />
            Target: ~1.0910 | R:R: 1:1.75<br /><br />
            Result Drop (auto on close):<br />
            EUR/USD BUY | Result: +2.1R | 18h
          </div>
          <div className="flex gap-2">
            <button onClick={dropSignal} disabled={dropping}
              className="px-4 py-2 bg-cyan-400 text-black rounded text-xs font-mono font-bold hover:bg-cyan-300 disabled:opacity-50">
              Drop Signal
            </button>
            <button onClick={dropResult}
              className="px-4 py-2 bg-slate-700/50 border border-slate-600 rounded text-xs font-mono hover:bg-slate-700">
              Drop Result
            </button>
          </div>
        </div>

        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-3">RECENT RESULT DROPS</div>
          {drops.length === 0 ? (
            <div className="text-sm text-gray-500">No drops yet.</div>
          ) : (
            drops.map((d, i) => (
              <div key={d.id ?? i} className="flex justify-between py-2.5 border-b border-slate-700/50 last:border-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-bold">{d.pair}</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-mono ${d.direction === 'BUY' ? 'bg-cyan-400/10 text-cyan-400' : 'bg-red-400/10 text-red-400'}`}>
                    {d.direction}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`font-mono font-bold text-sm ${d.pnl_r > 0 ? 'text-cyan-400' : 'text-red-400'}`}>
                    {d.pnl_r > 0 ? '+' : ''}{d.pnl_r?.toFixed(1)}R
                  </span>
                  <span className="text-xs text-gray-500">{d.created_at}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
