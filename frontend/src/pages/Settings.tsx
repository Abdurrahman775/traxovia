import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import api from '../api/client'

export default function Settings() {
  const [tab, setTab] = useState<'trading' | 'risk' | 'mt5'>('trading')
  const { data: settings, refetch } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings').then(r => r.data).catch(() => ({})),
  })

  const save = useMutation({
    mutationFn: (body: object) => api.patch('/settings', body),
    onSuccess: () => refetch(),
  })

  return (
    <div className="space-y-4">
      <div className="flex gap-1 bg-slate-900/50 p-1 rounded-lg">
        {(['trading', 'risk', 'mt5'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`flex-1 py-2 text-xs font-mono rounded-md transition-colors ${tab === t ? 'bg-slate-800 text-cyan-400 border border-slate-700' : 'text-gray-500 hover:text-gray-300'}`}>
            {t.toUpperCase()}
          </button>
        ))}
      </div>

      {tab === 'trading' && (
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4 space-y-0">
          <div className="text-xs text-gray-500 font-mono mb-3">TRADING CONFIGURATION</div>
          {[
            { l: 'Paper Trading Mode', key: 'is_paper_mode', type: 'toggle' },
            { l: 'Regime Filter (always active)', key: null, type: 'toggle-locked' },
            { l: 'Weekly Confluence (W1 + H4)', key: 'weekly_confluence_enabled', type: 'toggle' },
          ].map(row => (
            <div key={row.l} className="flex justify-between items-center py-3 border-b border-slate-700/50 last:border-0">
              <span className="text-sm text-gray-200">{row.l}</span>
              {row.type === 'toggle-locked' ? (
                <div className="w-9 h-5 bg-cyan-400 rounded-full opacity-60 cursor-not-allowed" />
              ) : (
                <button
                  onClick={() => row.key && save.mutate({ [row.key as string]: !(settings as any)?.[row.key as string] })}
                  className={`w-9 h-5 rounded-full transition-colors ${row.key && (settings as any)?.[row.key] ? 'bg-cyan-400' : 'bg-slate-600'}`}>
                  <div className={`w-3.5 h-3.5 bg-white rounded-full mx-0.5 transition-transform ${row.key && (settings as any)?.[row.key] ? 'translate-x-4' : ''}`} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {tab === 'risk' && (
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-2">RISK PARAMETERS</div>
          <div className="bg-orange-500/10 border border-orange-500/20 rounded p-3 mb-4 font-mono text-xs text-orange-400">
            3-STAGE DD PROTOCOL: 10% = Stage 1 (risk 0.5%) · 12% = Stage 2 (risk 0.25%) · 15% = Full pause
          </div>
          <div className="py-3 border-b border-slate-700/50">
            <div className="flex justify-between mb-2">
              <span className="text-sm text-gray-200">Base Risk %</span>
              <span className="font-mono text-xs text-cyan-400">{((settings?.base_risk_pct ?? 0.01) * 100).toFixed(1)}%</span>
            </div>
            <input type="range" min={0.25} max={2} step={0.25}
              defaultValue={(settings?.base_risk_pct ?? 0.01) * 100}
              onMouseUp={(e) => save.mutate({ base_risk_pct: Number((e.target as HTMLInputElement).value) / 100 })}
              className="w-full accent-cyan-400" />
          </div>
          <div className="py-3">
            <div className="flex justify-between mb-2">
              <span className="text-sm text-gray-200">Max Trades Per Day</span>
              <span className="font-mono text-xs text-cyan-400">{settings?.max_trades_per_day ?? 3}</span>
            </div>
            <input type="range" min={1} max={10} step={1}
              defaultValue={settings?.max_trades_per_day ?? 3}
              onMouseUp={(e) => save.mutate({ max_trades_per_day: Number((e.target as HTMLInputElement).value) })}
              className="w-full accent-cyan-400" />
          </div>
        </div>
      )}

      {tab === 'mt5' && (
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-3">BOUND MT5 ACCOUNTS</div>
          <div className="bg-red-400/10 border border-red-400/20 rounded p-3 mb-4 font-mono text-xs text-red-400">
            SECURITY: MT5 accounts can ONLY be bound/unbound via this web or mobile app. Never via Telegram.
          </div>
          <div className="text-sm text-gray-500">MT5 account binding is managed via the bridge setup process.</div>
        </div>
      )}
    </div>
  )
}
