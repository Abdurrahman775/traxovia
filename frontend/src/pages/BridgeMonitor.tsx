import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

interface BridgeStatus {
  primary_url:     string
  standby_url:     string
  active_url:      string
  primary_healthy: boolean
  standby_healthy: boolean
  trading_paused:  boolean
  failover_count:  number
  last_heartbeat:  string | null
  offline_since:   string | null
  source?:         string
}

export default function BridgeMonitor() {
  const { data: bridge, refetch, isLoading } = useQuery({
    queryKey: ['bridge-status'],
    queryFn: () => api.get('/bridge/status').then(r => r.data as BridgeStatus).catch(() => null),
    refetchInterval: 10_000,
  })

  // primary_healthy is derived from heartbeat recency + trading_paused in the backend
  const online = bridge?.primary_healthy === true

  function heartbeatAge() {
    if (!bridge?.last_heartbeat) return null
    const secs = Math.floor((Date.now() - new Date(bridge.last_heartbeat).getTime()) / 1000)
    if (secs < 60) return `${secs}s ago`
    return `${Math.floor(secs / 60)}m ${secs % 60}s ago`
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div>
          <h1 className="text-xl font-bold text-tx font-head">Bridge Monitor</h1>
          <p className="text-tx2 text-sm mt-0.5">MT5 execution bridge health and failover status</p>
        </div>
      </div>

      {/* Status banner */}
      <div className={`flex items-center gap-4 px-5 py-4 rounded-xl border ${
        isLoading
          ? 'bg-s1 border-s3'
          : online
          ? 'bg-gd/5 border-gd/30'
          : 'bg-rd/5 border-rd/30'
      }`}>
        <div className={`w-3 h-3 rounded-full shrink-0 ${
          isLoading ? 'bg-tx3' : online ? 'bg-gd animate-pulse' : 'bg-rd'
        }`} />
        <div className="flex-1">
          <span className={`font-mono font-bold text-sm tracking-widest ${
            isLoading ? 'text-tx2' : online ? 'text-gd' : 'text-rd'
          }`}>
            PRIMARY BRIDGE: {isLoading ? 'CHECKING…' : online ? 'ONLINE' : 'OFFLINE'}
          </span>
          {bridge?.last_heartbeat && (
            <span className="ml-4 text-xs text-tx2 font-mono">
              last heartbeat {heartbeatAge()}
            </span>
          )}
          {!bridge?.last_heartbeat && !isLoading && (
            <span className="ml-4 text-xs text-tx3 font-mono">no heartbeat recorded yet</span>
          )}
        </div>
        {bridge?.trading_paused && (
          <span className="px-2 py-0.5 rounded text-[11px] font-bold uppercase tracking-wide bg-rd/10 text-rd border border-rd/30">
            TRADING PAUSED
          </span>
        )}
        <button
          onClick={() => refetch()}
          className="shrink-0 px-3 py-1.5 rounded-lg border border-s3 text-tx2 text-xs font-mono hover:bg-s2 transition-colors"
        >
          ↻ Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Bridge Status */}
        <div className="bg-s1 border border-s3 rounded-xl p-5">
          <div className="text-[10px] font-mono text-tx3 uppercase tracking-widest mb-4">Bridge Status</div>
          <div className="space-y-0 divide-y divide-s3">
            {[
              ['Primary URL',    bridge?.primary_url    ?? '—'],
              ['Active URL',     bridge?.active_url     ?? '—'],
              ['Standby URL',    bridge?.standby_url    ?? '—'],
              ['Trading Paused', bridge?.trading_paused ? 'YES' : 'NO'],
              ['Failover Count', String(bridge?.failover_count ?? 0)],
              ['Last Heartbeat', bridge?.last_heartbeat
                ? new Date(bridge.last_heartbeat).toLocaleTimeString()
                : '—'],
              ['Offline Since',  bridge?.offline_since
                ? new Date(bridge.offline_since).toLocaleString()
                : '—'],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between py-2.5">
                <span className="text-sm text-tx2">{label}</span>
                <span className={`font-mono text-xs ${
                  label === 'Trading Paused' && value === 'YES' ? 'text-rd font-bold' : 'text-tx'
                }`}>
                  {value}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Watchdog Rules */}
        <div className="bg-s1 border border-s3 rounded-xl p-5">
          <div className="text-[10px] font-mono text-tx3 uppercase tracking-widest mb-4">Watchdog Rules</div>
          <div className="space-y-0 divide-y divide-s3">
            {[
              ['Heartbeat interval',  '60 seconds'],
              ['Pause threshold',     '2 minutes offline'],
              ['Failover threshold',  '5 minutes offline'],
              ['Stale threshold',     '3 minutes (shown as offline)'],
              ['User notification',   'Within 30 seconds'],
              ['Auto-resume',         'When primary OR standby reconnects'],
              ['Both offline',        'Critical alert — all channels'],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between py-2.5">
                <span className="text-sm text-tx2">{label}</span>
                <span className="font-mono text-xs text-tx">{value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
