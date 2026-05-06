import { useState, useEffect } from 'react'
import api from '../api/client'

const PAIRS = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'XAU/USD', 'US30']
const PAIR_MAP: Record<string, string> = {
  'EURUSD': 'EUR/USD', 'GBPUSD': 'GBP/USD', 'USDJPY': 'USD/JPY',
  'XAUUSD': 'XAU/USD', 'US30': 'US30',
}

interface RegimeData {
  regime: 'trending' | 'ranging' | 'volatile'
  adx: number
  atr_ratio: number
  blocked: boolean
}

export default function RegimeDetector() {
  const [regimes, setRegimes] = useState<Record<string, RegimeData>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchRegimes()
    const iv = setInterval(fetchRegimes, 30000)
    return () => clearInterval(iv)
  }, [])

  const fetchRegimes = async () => {
    try {
      const res = await api.get('/regime/current', {
      })
      // remap MT5 keys (EURUSD) to display keys (EUR/USD)
      const mapped: Record<string, RegimeData> = {}
      for (const [k, v] of Object.entries(res.data as Record<string, RegimeData>)) {
        const display = PAIR_MAP[k] ?? k
        mapped[display] = { ...v, blocked: v.regime === 'ranging' && v.adx < 20 }
      }
      setRegimes(mapped)
      setLoading(false)
    } catch (err) {
      console.error('Failed to fetch regimes:', err)
      setLoading(false)
    }
  }

  const blockedCount = Object.values(regimes).filter(r => r.blocked).length
  const trendingCount = Object.values(regimes).filter(r => r.regime === 'trending').length
  const rangingCount = Object.values(regimes).filter(r => r.regime === 'ranging').length
  const volatileCount = Object.values(regimes).filter(r => r.regime === 'volatile').length

  const getRegimeColor = (regime: string) => {
    if (regime === 'trending') return 'text-cyan-400 bg-cyan-400/10 border-cyan-400/20'
    if (regime === 'ranging') return 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20'
    return 'text-red-400 bg-red-400/10 border-red-400/20'
  }

  const getAdxColor = (adx: number) => {
    if (adx > 25) return 'text-cyan-400'
    if (adx > 20) return 'text-yellow-400'
    return 'text-red-400'
  }

  if (loading) return <div className="text-gray-400">Loading...</div>

  return (
    <div className="space-y-4">
      <div className="bg-orange-500/10 border border-orange-500/20 rounded-lg p-3 font-mono text-xs text-orange-400">
        REGIME FILTER ACTIVE — Signals suppressed when ADX &lt; 20. Only takes price action signals in trending/volatile markets.
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-2">TRENDING PAIRS</div>
          <div className="text-2xl font-bold text-cyan-400">{trendingCount}</div>
        </div>
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-2">RANGING (BLOCKED)</div>
          <div className="text-2xl font-bold text-yellow-400">{rangingCount}</div>
        </div>
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-2">VOLATILE (HALF SIZE)</div>
          <div className="text-2xl font-bold text-red-400">{volatileCount}</div>
        </div>
      </div>

      <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
        <div className="flex justify-between items-center mb-4">
          <div className="text-xs text-gray-500 font-mono">PER-PAIR ANALYSIS</div>
          <button onClick={fetchRegimes} className="px-3 py-1 bg-slate-700/50 border border-slate-600 rounded text-xs font-mono hover:bg-slate-700">
            ↻ REFRESH
          </button>
        </div>

        {PAIRS.map(pair => {
          const reg = regimes[pair]
          if (!reg) return null
          const adxColor = getAdxColor(reg.adx)

          return (
            <div key={pair} className="bg-slate-900/50 rounded-lg p-4 mb-3">
              <div className="flex items-center gap-3 mb-3">
                <span className="font-mono font-bold text-sm">{pair}</span>
                <span className={`px-2 py-1 rounded-full text-xs font-mono border ${getRegimeColor(reg.regime)}`}>
                  {reg.regime.toUpperCase()}
                </span>
                {reg.blocked && (
                  <span className="px-2 py-1 rounded text-xs font-mono bg-red-400/10 text-red-400 border border-red-400/20">
                    SIGNALS BLOCKED
                  </span>
                )}
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <div className="text-xs text-gray-500 font-mono mb-1">ADX</div>
                  <div className={`font-mono text-lg font-bold ${adxColor}`}>{reg.adx}</div>
                  <div className="h-1 bg-slate-700 rounded mt-2">
                    <div className={`h-full rounded ${adxColor.replace('text-', 'bg-')}`} style={{ width: `${Math.min(100, (reg.adx / 60) * 100)}%` }} />
                  </div>
                  <div className="text-xs text-gray-500 mt-1">&lt; 20 = ranging</div>
                </div>

                <div>
                  <div className="text-xs text-gray-500 font-mono mb-1">ATR RATIO</div>
                  <div className={`font-mono text-lg font-bold ${reg.atr_ratio > 1.5 ? 'text-red-400' : 'text-cyan-400'}`}>
                    {reg.atr_ratio.toFixed(2)}
                  </div>
                  <div className="h-1 bg-slate-700 rounded mt-2">
                    <div className={`h-full rounded ${reg.atr_ratio > 1.5 ? 'bg-red-400' : 'bg-cyan-400'}`} style={{ width: `${Math.min(100, (reg.atr_ratio * 50))}%` }} />
                  </div>
                  <div className="text-xs text-gray-500 mt-1">&gt; 2.0 = volatile (half size)</div>
                </div>

                <div>
                  <div className="text-xs text-gray-500 font-mono mb-1">SIGNAL GATE</div>
                  <div className={`font-mono text-sm mt-2 ${reg.blocked ? 'text-red-400' : reg.regime === 'volatile' ? 'text-yellow-400' : 'text-cyan-400'}`}>
                    {reg.blocked ? 'BLOCKED' : 'OPEN' + (reg.regime === 'volatile' ? ' (0.5x size)' : '')}
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
