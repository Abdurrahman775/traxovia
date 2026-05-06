import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

export default function Dashboard() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const { data: stats } = useQuery({ queryKey: ['dashboard'], queryFn: () => api.get('/analytics/summary').then(r => r.data).catch(() => null), refetchInterval: 30000 })
  const { data: bridge } = useQuery({ queryKey: ['bridge-status'], queryFn: () => api.get('/bridge/status').then(r => r.data).catch(() => null), refetchInterval: 10000 })
  const { data: regimes } = useQuery({ queryKey: ['regime'], queryFn: () => api.get('/regime/current').then(r => r.data).catch(() => null), refetchInterval: 30000 })

  const bridgeOnline = bridge?.status === 'online'
  const blockedCount = regimes ? Object.values(regimes as Record<string, any>).filter((r: any) => r.regime === 'ranging' && r.adx < 20).length : 0

  useEffect(() => {
    const cv = canvasRef.current
    if (!cv) return
    const ctx = cv.getContext('2d')!
    const W = cv.width, H = cv.height
    ctx.clearRect(0, 0, W, H)
    // Simple placeholder equity curve
    const vals = Array.from({ length: 40 }, (_, i) => 1000 + i * 8 + (Math.random() - 0.4) * 25)
    const mn = Math.min(...vals) - 10, mx = Math.max(...vals) + 10
    const tx = (i: number) => (i / (vals.length - 1)) * (W - 40) + 20
    const ty = (v: number) => H - 18 - ((v - mn) / (mx - mn)) * (H - 32)
    const g = ctx.createLinearGradient(0, 0, 0, H)
    g.addColorStop(0, 'rgba(0,229,204,0.2)')
    g.addColorStop(1, 'rgba(0,229,204,0)')
    ctx.beginPath()
    vals.forEach((v, i) => i ? ctx.lineTo(tx(i), ty(v)) : ctx.moveTo(tx(i), ty(v)))
    ctx.lineTo(tx(vals.length - 1), H - 18)
    ctx.lineTo(tx(0), H - 18)
    ctx.closePath()
    ctx.fillStyle = g
    ctx.fill()
    ctx.beginPath()
    ctx.strokeStyle = '#00e5cc'
    ctx.lineWidth = 2
    ctx.lineJoin = 'round'
    vals.forEach((v, i) => i ? ctx.lineTo(tx(i), ty(v)) : ctx.moveTo(tx(i), ty(v)))
    ctx.stroke()
  }, [stats])

  const metrics = [
    { t: 'Win Rate',      v: stats?.win_rate ? `${stats.win_rate}%` : '—',   c: 'text-cyan-400' },
    { t: 'Net P&L',       v: stats?.net_pnl_r ? `${stats.net_pnl_r > 0 ? '+' : ''}${stats.net_pnl_r}R` : '—', c: stats?.net_pnl_r >= 0 ? 'text-cyan-400' : 'text-red-400' },
    { t: 'Total Trades',  v: stats?.total_trades ?? '—', c: 'text-gray-200' },
    { t: 'Regime Blocks', v: blockedCount, c: 'text-orange-400' },
  ]

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-3">
        {metrics.map(m => (
          <div key={m.t} className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
            <div className="text-xs text-gray-500 font-mono mb-2">{m.t.toUpperCase()}</div>
            <div className={`text-2xl font-bold ${m.c}`}>{m.v}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-3">EQUITY CURVE</div>
          <canvas ref={canvasRef} width={440} height={150} style={{ width: '100%', height: 150 }} />
        </div>

        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="flex justify-between items-center mb-3">
            <div className="text-xs text-gray-500 font-mono">BRIDGE WATCHDOG</div>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${bridgeOnline ? 'bg-green-400' : 'bg-red-400'}`} />
              <span className={`font-mono text-xs ${bridgeOnline ? 'text-cyan-400' : 'text-red-400'}`}>
                {bridge?.status?.toUpperCase() ?? 'UNKNOWN'}
              </span>
            </div>
          </div>
          {[
            ['Heartbeat interval', '60 seconds'],
            ['Auto-pause', '2 minutes offline'],
            ['Standby bridge', 'Hot standby ready'],
            ['Auto-failover', '5 minutes → promote standby'],
          ].map(([l, v]) => (
            <div key={l} className="flex justify-between py-2 border-b border-slate-700/50 last:border-0">
              <span className="text-sm text-gray-400">{l}</span>
              <span className="font-mono text-xs text-gray-200">{v}</span>
            </div>
          ))}
        </div>
      </div>

      {regimes && (
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-3">LIVE REGIME — ALL PAIRS</div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 font-mono border-b border-slate-700">
                {['Pair', 'Regime', 'ADX', 'Gate'].map(h => <th key={h} className="text-left py-2 px-3">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {Object.entries(regimes as Record<string, any>).map(([pair, reg]) => {
                const blocked = reg.regime === 'ranging' && reg.adx < 20
                return (
                  <tr key={pair} className="border-b border-slate-700/30">
                    <td className="py-2 px-3 font-mono font-bold">{pair}</td>
                    <td className="py-2 px-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-mono border ${reg.regime === 'trending' ? 'text-cyan-400 bg-cyan-400/10 border-cyan-400/20' : reg.regime === 'volatile' ? 'text-red-400 bg-red-400/10 border-red-400/20' : 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20'}`}>
                        {reg.regime?.toUpperCase()}
                      </span>
                    </td>
                    <td className={`py-2 px-3 font-mono ${reg.adx > 25 ? 'text-cyan-400' : reg.adx > 20 ? 'text-yellow-400' : 'text-red-400'}`}>{reg.adx}</td>
                    <td className="py-2 px-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-mono ${blocked ? 'bg-red-400/10 text-red-400' : 'bg-green-400/10 text-green-400'}`}>
                        {blocked ? 'BLOCKED' : 'OPEN'}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
