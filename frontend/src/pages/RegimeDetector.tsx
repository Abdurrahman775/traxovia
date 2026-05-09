import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

interface RegimeData {
  regime:      'trending' | 'ranging' | 'volatile' | 'unknown' | 'bridge_offline'
  adx:         number
  atr_ratio:   number
  signal_gate: 'open' | 'blocked' | 'reduced'
}

interface RegimeResponse {
  pairs:         Record<string, RegimeData>
  bridge_online: boolean
}

function formatPair(raw: string): string {
  // EURUSD → EUR/USD, XAUUSD → XAU/USD, already-slashed pass through
  if (raw.includes('/')) return raw
  if (raw.length === 6) return `${raw.slice(0, 3)}/${raw.slice(3)}`
  return raw
}

function regimeMeta(regime: string) {
  switch (regime) {
    case 'trending':      return { label: 'TRENDING',      color: 'var(--color-cy)',  bg: 'rgba(0,229,204,0.08)',  border: 'rgba(0,229,204,0.2)' }
    case 'volatile':      return { label: 'VOLATILE',      color: '#f0b429',           bg: 'rgba(240,180,41,0.08)', border: 'rgba(240,180,41,0.2)' }
    case 'ranging':       return { label: 'RANGING',        color: '#ff3d5a',           bg: 'rgba(255,61,90,0.08)',  border: 'rgba(255,61,90,0.2)' }
    case 'bridge_offline':return { label: 'BRIDGE OFFLINE', color: 'var(--color-tx3)', bg: 'transparent',           border: 'var(--color-s3)' }
    default:              return { label: 'UNKNOWN',        color: 'var(--color-tx3)', bg: 'transparent',           border: 'var(--color-s3)' }
  }
}

function gateMeta(gate: string) {
  if (gate === 'open')    return { label: 'OPEN',         color: 'var(--color-cy)' }
  if (gate === 'reduced') return { label: 'OPEN (0.5×)',  color: '#f0b429' }
  return                         { label: 'BLOCKED',      color: '#ff3d5a' }
}

function adxColor(adx: number) {
  if (adx > 25) return 'var(--color-cy)'
  if (adx > 20) return '#f0b429'
  return '#ff3d5a'
}

function MiniBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--color-s3)' }}>
      <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, pct)}%`, background: color }} />
    </div>
  )
}

export default function RegimeDetector() {
  const { data, isLoading, isError, isFetching, refetch, dataUpdatedAt } = useQuery({
    queryKey: ['regime-current'],
    queryFn: () => api.get('/regime/current').then(r => r.data as RegimeResponse),
    refetchInterval: 30_000,
    retry: 1,
  })

  const pairs   = data?.pairs   ?? {}
  const entries = Object.entries(pairs).map(([k, v]) => ({ key: k, display: formatPair(k), ...v }))

  const trendingCount = entries.filter(e => e.regime === 'trending').length
  const rangingCount  = entries.filter(e => e.regime === 'ranging').length
  const volatileCount = entries.filter(e => e.regime === 'volatile').length
  const blockedCount  = entries.filter(e => e.signal_gate === 'blocked').length

  const lastUpdated = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : null

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-tx font-head">Regime Detector</h1>
          <p className="text-tx2 text-sm mt-0.5">Live market condition classification per pair</p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="font-mono text-[10px] text-tx3">updated {lastUpdated}</span>
          )}
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="px-3 py-1.5 rounded-lg border border-s3 text-tx2 text-xs font-mono hover:bg-s2 transition-colors disabled:opacity-50"
          >
            {isFetching ? '↻ Refreshing…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {/* Bridge offline warning */}
      {data && !data.bridge_online && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl font-mono text-xs"
          style={{ background: 'rgba(255,61,90,0.06)', border: '1px solid rgba(255,61,90,0.2)', color: '#ff3d5a' }}>
          ✗ MT5 bridge unreachable — showing last known regime state. All signals blocked.
        </div>
      )}

      {/* Active filter notice */}
      {(!data || data.bridge_online) && (
        <div className="px-4 py-3 rounded-xl font-mono text-[11px]"
          style={{ background: 'rgba(240,180,41,0.06)', border: '1px solid rgba(240,180,41,0.2)', color: '#f0b429' }}>
          REGIME FILTER ACTIVE — Signals suppressed when ADX &lt; 20. Only price-action signals pass in trending/volatile markets.
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Trending',        value: trendingCount,  color: 'var(--color-cy)' },
          { label: 'Ranging',         value: rangingCount,   color: '#ff3d5a' },
          { label: 'Volatile',        value: volatileCount,  color: '#f0b429' },
          { label: 'Signals Blocked', value: blockedCount,   color: 'var(--color-tx2)' },
        ].map(c => (
          <div key={c.label} className="bg-s1 border border-s3 rounded-xl p-4">
            <div className="text-[10px] font-mono text-tx3 uppercase tracking-widest mb-1">{c.label}</div>
            <div className="text-3xl font-bold font-head" style={{ color: c.color }}>
              {isLoading ? '—' : c.value}
            </div>
          </div>
        ))}
      </div>

      {/* Per-pair table */}
      <div className="bg-s1 border border-s3 rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-s3">
          <span className="text-[10px] font-mono text-tx3 uppercase tracking-widest">Per-Pair Analysis</span>
        </div>

        {isLoading && (
          <div className="px-5 py-8 text-center text-tx2 text-sm animate-pulse">Classifying regimes…</div>
        )}
        {isError && (
          <div className="px-5 py-8 text-center font-mono text-xs" style={{ color: '#ff3d5a' }}>
            Failed to load regime data. Check API connection.
          </div>
        )}

        {!isLoading && !isError && entries.map(e => {
          const rm   = regimeMeta(e.regime)
          const gm   = gateMeta(e.signal_gate)
          const adc  = adxColor(e.adx)
          const atrColor = e.atr_ratio > 2 ? '#f0b429' : 'var(--color-cy)'
          const offline  = e.regime === 'bridge_offline' || e.regime === 'unknown'

          return (
            <div key={e.key} className="px-5 py-4 border-b border-s3 last:border-0"
              style={{ opacity: offline ? 0.5 : 1 }}>

              {/* Row header */}
              <div className="flex items-center gap-3 mb-4">
                <span className="font-mono font-bold text-sm text-tx">{e.display}</span>
                <span className="px-2 py-0.5 rounded-full text-[11px] font-mono font-bold"
                  style={{ background: rm.bg, color: rm.color, border: `1px solid ${rm.border}` }}>
                  {rm.label}
                </span>
                <span className="px-2 py-0.5 rounded text-[11px] font-mono font-semibold"
                  style={{ color: gm.color }}>
                  {gm.label}
                </span>
              </div>

              {/* Metrics */}
              {!offline && (
                <div className="grid grid-cols-3 gap-5">
                  {/* ADX */}
                  <div>
                    <div className="text-[10px] font-mono text-tx3 uppercase tracking-widest mb-1">ADX</div>
                    <div className="font-mono text-lg font-bold" style={{ color: adc }}>{e.adx.toFixed(1)}</div>
                    <MiniBar pct={(e.adx / 60) * 100} color={adc} />
                    <div className="text-[10px] text-tx3 font-mono mt-1">&lt;20 = ranging</div>
                  </div>

                  {/* ATR Ratio */}
                  <div>
                    <div className="text-[10px] font-mono text-tx3 uppercase tracking-widest mb-1">ATR Ratio</div>
                    <div className="font-mono text-lg font-bold" style={{ color: atrColor }}>
                      {e.atr_ratio.toFixed(2)}
                    </div>
                    <MiniBar pct={(e.atr_ratio / 4) * 100} color={atrColor} />
                    <div className="text-[10px] text-tx3 font-mono mt-1">&gt;2.0 = volatile</div>
                  </div>

                  {/* Signal Gate */}
                  <div>
                    <div className="text-[10px] font-mono text-tx3 uppercase tracking-widest mb-1">Signal Gate</div>
                    <div className="font-mono text-base font-bold mt-1" style={{ color: gm.color }}>
                      {gm.label}
                    </div>
                    <div className="text-[10px] text-tx3 font-mono mt-1">
                      {e.signal_gate === 'open'    ? 'full position size' :
                       e.signal_gate === 'reduced' ? 'half position size' :
                       'no new signals'}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
