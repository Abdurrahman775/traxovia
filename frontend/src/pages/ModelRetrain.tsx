import { useState, useEffect } from 'react'
import api from '../api/client'

interface ModelVersion {
  version: string
  trained_at: string
  samples: number
  oos_sharpe: number
  oos_wr: number
  is_active: boolean
}

interface ShapFeature {
  feature: string
  importance: number
  delta: string
}

export default function ModelRetrain() {
  const [tab, setTab] = useState<'status' | 'retraining' | 'versions'>('status')
  const [versions, setVersions] = useState<ModelVersion[]>([])
  const [shapFeatures, setShapFeatures] = useState<ShapFeature[]>([])
  const [retrainStatus, setRetrainStatus] = useState<'idle' | 'running' | 'done'>('idle')
  const [retrainProg, setRetrainProg] = useState(0)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    try {
      const [versRes, shapRes] = await Promise.all([
        api.get('/model/versions'),
        api.get('/model/shap'),
      ])
      setVersions(versRes.data)
      setShapFeatures(shapRes.data)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const triggerRetrain = async () => {
    if (retrainStatus === 'running') return
    setRetrainStatus('running')
    setRetrainProg(0)
    try {
      await api.post('/model/retrain', {}, {
      })
    } catch (err) {
      console.error(err)
    }
    // Simulate progress polling
    let p = 0
    const iv = setInterval(() => {
      p += Math.floor(Math.random() * 9) + 3
      if (p >= 100) {
        clearInterval(iv)
        setRetrainStatus('done')
        setRetrainProg(100)
        fetchData()
      } else {
        setRetrainProg(p)
      }
    }, 180)
  }

  const rollback = async (version: string) => {
    try {
      await api.post(`/model/rollback/${version}`, {})
      fetchData()
    } catch (err) {
      console.error(err)
    }
  }

  const activeModel = versions.find(v => v.is_active)

  if (loading) return <div className="text-gray-400">Loading...</div>

  return (
    <div className="space-y-4">
      <div className="flex gap-1 bg-slate-900/50 p-1 rounded-lg">
        {(['status', 'retraining', 'versions'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`flex-1 py-2 text-xs font-mono rounded-md transition-colors ${tab === t ? 'bg-slate-800 text-cyan-400 border border-slate-700' : 'text-gray-500 hover:text-gray-300'}`}>
            {t.toUpperCase()}
          </button>
        ))}
      </div>

      {tab === 'status' && (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-3">
            {[
              { l: 'Active Model', v: activeModel?.version ?? '—' },
              { l: 'Samples', v: activeModel?.samples?.toLocaleString() ?? '—' },
              { l: 'OOS Sharpe', v: activeModel?.oos_sharpe?.toFixed(2) ?? '—' },
              { l: 'OOS WR', v: activeModel ? `${activeModel.oos_wr}%` : '—' },
            ].map(m => (
              <div key={m.l} className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
                <div className="text-xs text-gray-500 font-mono mb-2">{m.l.toUpperCase()}</div>
                <div className="text-xl font-bold text-cyan-400">{m.v}</div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
              <div className="text-xs text-gray-500 font-mono mb-3">AUTO-LABELING FEEDBACK LOOP</div>
              <div className="bg-cyan-400/10 border border-cyan-400/20 rounded p-3 mb-3 font-mono text-xs text-cyan-400">
                ACTIVE — Every trade close writes outcome to feature_store
              </div>
              {[
                ['Next scheduled retrain', 'Weekly Sunday 02:00 UTC'],
                ['Feature drift check', 'Daily SHAP comparison'],
                ['Validation gate', 'OOS Sharpe > 1.2 AND OOS WR > 50%'],
              ].map(([l, v]) => (
                <div key={l} className="flex justify-between py-2 border-b border-slate-700/50 last:border-0">
                  <span className="text-sm text-gray-400">{l}</span>
                  <span className="font-mono text-xs text-gray-200">{v}</span>
                </div>
              ))}
            </div>

            <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
              <div className="text-xs text-gray-500 font-mono mb-3">TOP SHAP FEATURES</div>
              {shapFeatures.slice(0, 6).map((f, i) => (
                <div key={f.feature} className="flex items-center gap-2 py-2 border-b border-slate-700/50 last:border-0">
                  <span className="font-mono text-xs text-gray-200 flex-1">#{i + 1} {f.feature}</span>
                  <div className="w-20 h-1 bg-slate-700 rounded">
                    <div className="h-full bg-cyan-400 rounded" style={{ width: `${Math.min(100, (f.importance / 20) * 100)}%` }} />
                  </div>
                  <span className={`font-mono text-xs w-8 text-right ${f.delta.startsWith('+') || f.delta === 'NEW' ? 'text-cyan-400' : 'text-yellow-400'}`}>
                    {f.delta}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab === 'retraining' && (
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4 space-y-4">
          <div className="text-xs text-gray-500 font-mono mb-2">RETRAIN PIPELINE</div>
          <div className="bg-slate-900/50 rounded-lg p-4">
            <div className="flex justify-between items-center mb-3">
              <span className="font-medium">Walk-Forward Retraining</span>
              <span className={`px-2 py-1 rounded text-xs font-mono ${retrainStatus === 'running' ? 'bg-yellow-400/10 text-yellow-400' : retrainStatus === 'done' ? 'bg-cyan-400/10 text-cyan-400' : 'bg-slate-700 text-gray-400'}`}>
                {retrainStatus.toUpperCase()}
              </span>
            </div>
            {retrainStatus === 'running' && (
              <div className="mb-3">
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-gray-400">Training progress</span>
                  <span className="font-mono text-cyan-400">{Math.round(retrainProg)}%</span>
                </div>
                <div className="h-1.5 bg-slate-700 rounded">
                  <div className="h-full bg-cyan-400 rounded transition-all" style={{ width: `${retrainProg}%` }} />
                </div>
              </div>
            )}
            <div className="flex gap-2">
              <button onClick={triggerRetrain} disabled={retrainStatus === 'running'}
                className={`px-4 py-2 rounded text-xs font-mono font-bold ${retrainStatus === 'running' ? 'bg-slate-700 text-gray-400 cursor-not-allowed' : 'bg-cyan-400 text-black hover:bg-cyan-300'}`}>
                {retrainStatus === 'running' ? 'Training...' : 'Run Retrain Now'}
              </button>
            </div>
          </div>

          {[
            ['Auto-label closed trades', 'On every trade close → outcome to feature_store', 'auto'],
            ['Feature drift check', 'Daily SHAP importance comparison — alert if shift > 0.05', 'auto'],
            ['Walk-forward train', '252-day train / 63-day test / 21-day step', 'scheduled'],
            ['Validation gate', 'OOS Sharpe > 1.2 AND OOS WR > 50% — else do not deploy', 'gate'],
            ['A/B vs current', 'New model must beat current on last 30 days live data', 'gate'],
            ['Deploy if passed', 'Set active=TRUE, archive old version', 'auto'],
            ['Rollback', 'One-click rollback to any previous version', 'manual'],
          ].map(([title, desc, type], i) => (
            <div key={i} className="flex gap-3 py-3 border-b border-slate-700/50 last:border-0">
              <div className="w-8 h-8 rounded bg-cyan-400/10 flex items-center justify-center font-mono text-xs text-cyan-400 shrink-0">{i + 1}</div>
              <div className="flex-1">
                <div className="text-sm font-medium mb-1">{title}</div>
                <div className="text-xs text-gray-400">{desc}</div>
              </div>
              <span className={`px-2 py-1 h-fit rounded text-xs font-mono ${type === 'auto' ? 'bg-cyan-400/10 text-cyan-400' : type === 'gate' ? 'bg-yellow-400/10 text-yellow-400' : 'bg-slate-700 text-gray-400'}`}>
                {type}
              </span>
            </div>
          ))}
        </div>
      )}

      {tab === 'versions' && (
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="text-xs text-gray-500 font-mono mb-4">MODEL VERSION REGISTRY</div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 font-mono border-b border-slate-700">
                {['Version', 'Trained', 'Samples', 'OOS Sharpe', 'OOS WR', 'Status', ''].map(h => (
                  <th key={h} className="text-left py-2 px-3">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {versions.map(v => (
                <tr key={v.version} className="border-b border-slate-700/30 hover:bg-slate-700/20">
                  <td className="py-3 px-3 font-mono font-bold">{v.version}</td>
                  <td className="py-3 px-3 font-mono text-xs text-gray-400">{v.trained_at}</td>
                  <td className="py-3 px-3 font-mono">{v.samples?.toLocaleString()}</td>
                  <td className="py-3 px-3 font-mono text-cyan-400">{v.oos_sharpe?.toFixed(2)}</td>
                  <td className="py-3 px-3 font-mono">{v.oos_wr}%</td>
                  <td className="py-3 px-3">
                    <span className={`px-2 py-1 rounded text-xs font-mono ${v.is_active ? 'bg-cyan-400/10 text-cyan-400' : 'bg-slate-700 text-gray-400'}`}>
                      {v.is_active ? 'ACTIVE' : 'ARCHIVED'}
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    {!v.is_active && (
                      <button onClick={() => rollback(v.version)}
                        className="px-3 py-1 bg-slate-700/50 border border-slate-600 rounded text-xs font-mono hover:bg-slate-700">
                        Rollback
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
