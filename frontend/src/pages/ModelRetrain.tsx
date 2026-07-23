import { useState, useEffect } from 'react'
import api from '../api/client'

interface ModelVersion {
  version:    string
  trained_at: string
  samples:    number
  oos_sharpe: number
  oos_wr:     number
  is_active:  boolean
}

interface ShapFeature {
  feature:    string
  importance: number
  delta:      string
}

export default function ModelRetrain() {
  const [tab,           setTab]           = useState<'status' | 'retraining' | 'versions'>('status')
  const [versions,      setVersions]      = useState<ModelVersion[]>([])
  const [shapFeatures,  setShapFeatures]  = useState<ShapFeature[]>([])
  const [retrainStatus, setRetrainStatus] = useState<'idle' | 'running' | 'done'>('idle')
  const [retrainProg,   setRetrainProg]   = useState(0)
  const [loading,       setLoading]       = useState(true)

  useEffect(() => { fetchData() }, [])

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
      await api.post('/model/retrain', {})
    } catch (err) {
      console.error(err)
    }
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

  if (loading) return <p className="text-tx2 text-sm animate-pulse">Loading…</p>

  const TABS = ['status', 'retraining', 'versions'] as const

  return (
    <div className="space-y-4">

      <div>
        <h1 className="text-xl font-bold text-tx font-head">Model & Retrain</h1>
        <p className="text-tx2 text-sm mt-0.5">Walk-forward ML model status, retraining pipeline and version registry</p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-s1 border border-s3 rounded-xl p-1">
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`flex-1 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              tab === t ? 'bg-cy text-bg' : 'text-tx2 hover:text-tx hover:bg-s2'
            }`}>
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* ── Status ── */}
      {tab === 'status' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { l: 'Active Model', v: activeModel?.version ?? '—' },
              { l: 'Samples',      v: activeModel?.samples?.toLocaleString() ?? '—' },
              { l: 'OOS Sharpe',   v: activeModel?.oos_sharpe?.toFixed(2) ?? '—' },
              { l: 'OOS Win Rate', v: activeModel ? `${activeModel.oos_wr}%` : '—' },
            ].map(m => (
              <div key={m.l} className="bg-s1 border border-s3 rounded-xl p-4">
                <div className="text-[10px] font-mono tracking-widest uppercase text-tx3 mb-2">{m.l}</div>
                <div className="text-2xl font-bold text-cy font-head">{m.v}</div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-s1 border border-s3 rounded-xl p-5">
              <div className="text-[10px] font-mono tracking-widest uppercase text-tx3 mb-3">Auto-Labeling Feedback Loop</div>
              <div className="px-3 py-2 rounded-lg text-xs font-mono mb-4"
                style={{ background: 'rgba(212,168,83,0.06)', border: '1px solid rgba(212,168,83,0.18)', color: 'var(--color-cy)' }}>
                ACTIVE — Every trade close writes outcome to feature_store
              </div>
              <div className="space-y-0 divide-y divide-s3">
                {[
                  ['Next scheduled retrain', 'Weekly Sunday 02:00 UTC'],
                  ['Feature drift check',    'Daily SHAP comparison'],
                  ['Validation gate',        'OOS Sharpe > 1.2 AND OOS WR > 50%'],
                ].map(([l, v]) => (
                  <div key={l} className="flex justify-between py-2.5">
                    <span className="text-sm text-tx2">{l}</span>
                    <span className="font-mono text-xs text-tx">{v}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-s1 border border-s3 rounded-xl p-5">
              <div className="text-[10px] font-mono tracking-widest uppercase text-tx3 mb-3">Top SHAP Features</div>
              <div className="space-y-0 divide-y divide-s3">
                {shapFeatures.slice(0, 6).map((f, i) => (
                  <div key={f.feature} className="flex items-center gap-3 py-2.5">
                    <span className="font-mono text-xs text-tx flex-1">#{i + 1} {f.feature}</span>
                    <div className="w-20 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--color-s3)' }}>
                      <div className="h-full rounded-full bg-cy"
                        style={{ width: `${Math.min(100, (f.importance / 20) * 100)}%` }} />
                    </div>
                    <span className={`font-mono text-xs w-8 text-right ${f.delta.startsWith('+') || f.delta === 'NEW' ? 'text-cy' : 'text-gd'}`}>
                      {f.delta}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Retraining ── */}
      {tab === 'retraining' && (
        <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-4">
          <div className="text-[10px] font-mono tracking-widest uppercase text-tx3">Retrain Pipeline</div>

          {/* Trigger */}
          <div className="bg-s2 border border-s3 rounded-xl p-4">
            <div className="flex justify-between items-center mb-3">
              <span className="text-sm font-semibold text-tx">Walk-Forward Retraining</span>
              <span className={`px-2 py-1 rounded text-xs font-mono ${
                retrainStatus === 'running' ? 'bg-gd/10 text-gd border border-gd/20' :
                retrainStatus === 'done'    ? 'bg-cy/10 text-cy border border-cy/20' :
                'bg-s3 text-tx2'
              }`}>
                {retrainStatus.toUpperCase()}
              </span>
            </div>
            {retrainStatus === 'running' && (
              <div className="mb-3">
                <div className="flex justify-between text-xs mb-1.5">
                  <span className="text-tx2">Training progress</span>
                  <span className="font-mono text-cy">{Math.round(retrainProg)}%</span>
                </div>
                <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--color-s3)' }}>
                  <div className="h-full bg-cy rounded-full transition-all" style={{ width: `${retrainProg}%` }} />
                </div>
              </div>
            )}
            <button
              onClick={triggerRetrain}
              disabled={retrainStatus === 'running'}
              className={`px-4 py-2 rounded-lg text-xs font-mono font-bold transition-colors ${
                retrainStatus === 'running'
                  ? 'bg-s3 text-tx3 cursor-not-allowed'
                  : 'bg-cy text-bg hover:bg-cy/90'
              }`}>
              {retrainStatus === 'running' ? 'Training…' : 'Run Retrain Now'}
            </button>
          </div>

          {/* Pipeline steps */}
          <div className="divide-y divide-s3">
            {[
              ['Auto-label closed trades', 'On every trade close → outcome to feature_store',            'auto'],
              ['Feature drift check',      'Daily SHAP importance comparison — alert if shift > 0.05',   'auto'],
              ['Walk-forward train',       '252-day train / 63-day test / 21-day step',                  'scheduled'],
              ['Validation gate',          'OOS Sharpe > 1.2 AND OOS WR > 50% — else do not deploy',    'gate'],
              ['A/B vs current',           'New model must beat current on last 30 days live data',      'gate'],
              ['Deploy if passed',         'Set active=TRUE, archive old version',                       'auto'],
              ['Rollback',                 'One-click rollback to any previous version',                 'manual'],
            ].map(([title, desc, type], i) => (
              <div key={i} className="flex gap-3 py-3.5">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center font-mono text-xs font-bold text-cy shrink-0"
                  style={{ background: 'rgba(212,168,83,0.1)', border: '1px solid rgba(212,168,83,0.2)' }}>
                  {i + 1}
                </div>
                <div className="flex-1">
                  <div className="text-sm font-semibold text-tx">{title}</div>
                  <div className="text-xs text-tx2 mt-0.5">{desc}</div>
                </div>
                <span className={`px-2 py-1 h-fit rounded text-xs font-mono ${
                  type === 'auto'     ? 'bg-cy/10 text-cy border border-cy/20' :
                  type === 'gate'     ? 'bg-gd/10 text-gd border border-gd/20' :
                  type === 'scheduled'? 'bg-bl/10 text-bl border border-bl/20' :
                  'bg-s3 text-tx2'
                }`}>
                  {type}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Versions ── */}
      {tab === 'versions' && (
        <div className="bg-s1 border border-s3 rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-s3">
            <div className="text-[10px] font-mono tracking-widest uppercase text-tx3">Model Version Registry</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-s2 text-[10px] font-mono tracking-wide uppercase text-tx3">
                  {['Version', 'Trained', 'Samples', 'OOS Sharpe', 'OOS WR', 'Status', ''].map(h => (
                    <th key={h} className="text-left py-2.5 px-4">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-s3">
                {versions.map(v => (
                  <tr key={v.version} className="hover:bg-s2 transition-colors">
                    <td className="py-3 px-4 font-mono font-bold text-tx">{v.version}</td>
                    <td className="py-3 px-4 font-mono text-xs text-tx2">{v.trained_at}</td>
                    <td className="py-3 px-4 font-mono text-tx">{v.samples?.toLocaleString()}</td>
                    <td className="py-3 px-4 font-mono text-cy">{v.oos_sharpe?.toFixed(2)}</td>
                    <td className="py-3 px-4 font-mono text-tx">{v.oos_wr}%</td>
                    <td className="py-3 px-4">
                      <span className={`px-2 py-0.5 rounded text-[11px] font-mono font-semibold ${
                        v.is_active
                          ? 'bg-cy/10 text-cy border border-cy/20'
                          : 'bg-s3 text-tx2'
                      }`}>
                        {v.is_active ? 'ACTIVE' : 'ARCHIVED'}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      {!v.is_active && (
                        <button onClick={() => rollback(v.version)}
                          className="px-3 py-1 rounded-lg text-xs font-mono text-tx2 hover:text-tx transition-colors"
                          style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
                          Rollback
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {versions.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-10 text-center text-tx3 text-sm font-mono">No model versions yet</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
