import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

export default function BridgeMonitor() {
  const { data: bridge, refetch } = useQuery({
    queryKey: ['bridge-status'],
    queryFn: () => api.get('/bridge/status').then(r => r.data).catch(() => null),
    refetchInterval: 10000,
  })

  const online = bridge && !bridge.trading_paused

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className={`w-2.5 h-2.5 rounded-full ${online ? 'bg-green-400' : 'bg-red-400'}`} />
        <span className={`font-mono text-sm ${online ? 'text-cyan-400' : 'text-red-400'}`}>
          PRIMARY BRIDGE: {online ? 'ONLINE' : 'OFFLINE'}
        </span>
        <button onClick={() => refetch()}
          className="ml-auto px-3 py-1 bg-slate-700/50 border border-slate-600 rounded text-xs font-mono hover:bg-slate-700">
          ↻ Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-3">BRIDGE STATUS</div>
          {[
            ['Primary URL',    bridge?.primary_url ?? '—'],
            ['Active URL',     bridge?.active_url ?? '—'],
            ['Trading Paused', bridge?.trading_paused ? 'YES' : 'NO'],
            ['Failover Count', bridge?.failover_count ?? 0],
            ['Last Heartbeat', bridge?.last_heartbeat ? new Date(bridge.last_heartbeat).toLocaleTimeString() : '—'],
          ].map(([l, v]) => (
            <div key={l} className="flex justify-between py-2 border-b border-slate-700/50 last:border-0">
              <span className="text-sm text-gray-400">{l}</span>
              <span className={`font-mono text-xs ${l === 'Trading Paused' && v === 'YES' ? 'text-red-400' : 'text-gray-200'}`}>{String(v)}</span>
            </div>
          ))}
        </div>

        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-3">WATCHDOG RULES</div>
          {[
            ['Heartbeat interval',  '60 seconds'],
            ['Pause threshold',     '2 minutes offline'],
            ['Failover threshold',  '5 minutes offline'],
            ['User notification',   'Within 30 seconds'],
            ['Auto-resume',         'When primary OR standby reconnects'],
            ['Both offline',        'Critical alert — all channels'],
          ].map(([l, v]) => (
            <div key={l} className="flex justify-between py-2 border-b border-slate-700/50 last:border-0">
              <span className="text-sm text-gray-400">{l}</span>
              <span className="font-mono text-xs text-gray-200">{v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
