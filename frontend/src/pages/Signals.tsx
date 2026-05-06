import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

export default function Signals() {
  const qc = useQueryClient()
  const { data: signals = [], isLoading } = useQuery({
    queryKey: ['signals'],
    queryFn: () => api.get('/signals').then(r => r.data),
    refetchInterval: 15000,
  })

  const update = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.patch(`/signals/${id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['signals'] }),
  })

  const getRegimeColor = (regime: string) => {
    if (regime === 'trending') return 'text-cyan-400 bg-cyan-400/10 border-cyan-400/20'
    if (regime === 'volatile') return 'text-red-400 bg-red-400/10 border-red-400/20'
    return 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20'
  }

  if (isLoading) return <div className="text-gray-400">Loading...</div>

  const blocked = signals.filter((s: any) => s.regime === 'ranging' && s.regime_adx < 20)

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 text-xs font-mono text-gray-500">
        <span>{signals.length} SIGNALS</span>
        <span>·</span>
        <span>{signals.filter((s: any) => s.status === 'pending').length} PENDING</span>
        <span>·</span>
        <span className="text-orange-400">{blocked.length} REGIME BLOCKED</span>
      </div>

      {blocked.length > 0 && (
        <div className="bg-orange-500/10 border border-orange-500/20 rounded-lg p-3 font-mono text-xs text-orange-400">
          {blocked.length} signal(s) blocked — market is ranging (ADX &lt; 20). Signals resume when ADX &gt; 20.
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        {signals.map((s: any) => {
          const isBlocked = s.regime === 'ranging' && s.regime_adx < 20
          return (
            <div key={s.id}
              className={`border rounded-xl p-4 ${isBlocked ? 'bg-red-400/5 border-red-400/15 opacity-70' : 'bg-slate-800/50 border-slate-700/50'}`}>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-sm">{s.pair}</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-mono ${s.direction === 'buy' ? 'bg-cyan-400/10 text-cyan-400' : 'bg-red-400/10 text-red-400'}`}>
                    {s.direction?.toUpperCase()}
                  </span>
                  {s.regime && (
                    <span className={`px-2 py-0.5 rounded-full text-xs font-mono border ${getRegimeColor(s.regime)}`}>
                      {s.regime.toUpperCase()}
                    </span>
                  )}
                </div>
                <span className={`px-2 py-0.5 rounded text-xs font-mono ${isBlocked ? 'bg-red-400/10 text-red-400' : s.status === 'pending' ? 'bg-yellow-400/10 text-yellow-400' : s.status === 'approved' ? 'bg-cyan-400/10 text-cyan-400' : 'bg-slate-700 text-gray-400'}`}>
                  {isBlocked ? 'BLOCKED' : s.status?.toUpperCase()}
                </span>
              </div>

              <div className="grid grid-cols-3 gap-2 mb-3">
                {[['ENTRY', s.entry_price], ['SL', s.stop_loss], ['TP', s.take_profit]].map(([l, v]) => (
                  <div key={l} className="bg-slate-900/50 rounded p-2">
                    <div className="text-xs text-gray-500 font-mono mb-1">{l}</div>
                    <div className="font-mono text-xs text-gray-200">{v ? Number(v).toFixed(5) : '—'}</div>
                  </div>
                ))}
              </div>

              {!isBlocked && s.ai_probability != null && (
                <div className="mb-3">
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-gray-500">AI Confidence</span>
                    <span className={`font-mono ${s.ai_probability > 0.75 ? 'text-cyan-400' : 'text-yellow-400'}`}>
                      {Math.round(s.ai_probability * 100)}%
                    </span>
                  </div>
                  <div className="h-1 bg-slate-700 rounded">
                    <div className={`h-full rounded ${s.ai_probability > 0.75 ? 'bg-cyan-400' : 'bg-yellow-400'}`}
                      style={{ width: `${s.ai_probability * 100}%` }} />
                  </div>
                </div>
              )}

              {isBlocked && (
                <div className="font-mono text-xs text-red-400">
                  Blocked: ranging · ADX {s.regime_adx}
                </div>
              )}

              {s.status === 'pending' && !isBlocked && (
                <div className="flex gap-2 mt-3">
                  <button onClick={() => update.mutate({ id: s.id, status: 'approved' })}
                    className="flex-1 py-1.5 bg-cyan-400 text-black rounded text-xs font-mono font-bold hover:bg-cyan-300">
                    Approve
                  </button>
                  <button onClick={() => update.mutate({ id: s.id, status: 'rejected' })}
                    className="flex-1 py-1.5 bg-slate-700 border border-slate-600 rounded text-xs font-mono hover:bg-slate-600">
                    Reject
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
