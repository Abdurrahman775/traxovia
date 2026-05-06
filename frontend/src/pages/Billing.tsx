import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

const PLANS = [
  { id: 'starter', price: 29,  color: '#4f8ef7' },
  { id: 'trader',  price: 79,  color: '#00e5cc' },
  { id: 'pro',     price: 149, color: '#f0b429' },
  { id: 'elite',   price: 299, color: '#8b5cf6' },
]

export default function Billing() {
  const { data: sub } = useQuery({
    queryKey: ['subscription'],
    queryFn: () => api.get('/billing/subscription').then(r => r.data).catch(() => null),
  })

  const currentPlan = sub?.plan ?? 'community'

  const upgrade = async (planId: string) => {
    try {
      const res = await api.post('/billing/create-checkout-session', { plan: planId })
      if (res.data.url) window.location.href = res.data.url
    } catch (err) {
      console.error(err)
    }
  }

  const openPortal = async () => {
    try {
      const res = await api.post('/billing/customer-portal')
      if (res.data.url) window.location.href = res.data.url
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div className="space-y-4">
      <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl p-4 flex justify-between items-center">
        <div>
          <div className="font-mono text-xs text-blue-400 mb-1">14-DAY FREE TRIAL</div>
          <div className="text-sm text-gray-400">Full Trader features · Paper demo account · No credit card needed</div>
        </div>
        <button onClick={() => upgrade('trader')}
          className="px-4 py-2 bg-blue-500 text-white rounded text-xs font-mono font-bold hover:bg-blue-400">
          Start Free Trial
        </button>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {PLANS.map(p => {
          const isCurrent = p.id === currentPlan
          return (
            <div key={p.id} style={{ borderColor: isCurrent ? p.color : undefined }}
              className={`bg-slate-800/50 border rounded-xl p-5 relative ${isCurrent ? 'border-opacity-100' : 'border-slate-700/50'}`}>
              {isCurrent && (
                <div className="absolute top-2 right-2 px-1.5 py-0.5 rounded text-[9px] font-mono font-bold text-black"
                  style={{ background: p.color }}>ACTIVE</div>
              )}
              <span className="px-2 py-0.5 rounded text-xs font-mono font-bold"
                style={{ background: `${p.color}22`, color: p.color, border: `1px solid ${p.color}44` }}>
                {p.id.toUpperCase()}
              </span>
              <div className="text-2xl font-bold mt-3 mb-0.5" style={{ color: p.color }}>${p.price}</div>
              <div className="font-mono text-xs text-gray-500 mb-4">per month</div>
              {!isCurrent && (
                <button onClick={() => upgrade(p.id)}
                  className="w-full py-1.5 bg-slate-700/50 border border-slate-600 rounded text-xs font-mono hover:bg-slate-700">
                  {PLANS.findIndex(x => x.id === p.id) > PLANS.findIndex(x => x.id === currentPlan) ? 'Upgrade' : 'Downgrade'}
                </button>
              )}
            </div>
          )
        })}
      </div>

      {sub?.stripe_customer_id && (
        <div className="text-center">
          <button onClick={openPortal}
            className="px-4 py-2 bg-slate-700/50 border border-slate-600 rounded text-xs font-mono hover:bg-slate-700">
            Manage Subscription →
          </button>
        </div>
      )}
    </div>
  )
}
