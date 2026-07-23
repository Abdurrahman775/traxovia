import { Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

const PLAN_ORDER = ['community', 'starter', 'trader', 'pro', 'elite']

const FALLBACK_COLORS: Record<string, string> = {
  community: '#8899b4', starter: '#4f8ef7', trader: '#d4a853', pro: '#f0b429', elite: '#8b5cf6',
}
const FALLBACK_PRICES: Record<string, string> = {
  community: 'Free', starter: '$29/mo', trader: '$79/mo', pro: '$149/mo', elite: '$299/mo',
}

// Feature → minimum plan required
const FEATURE_PLAN: Record<string, string> = {
  dashboard:        'starter',
  signals:          'starter',
  trades:           'starter',
  analytics:        'starter',
  news:             'starter',
  settings:         'starter',
  profile:          'starter',
  billing:          'starter',

  auditlog:         'starter',
  copy_trade:       'trader',
  tg_bot_approve:   'trader',
  auto_execute:     'pro',
  tg_bot_settings:  'pro',
  api_access:       'elite',
  admin:            'elite',
  model:            'elite',
  community:        'elite',
  'data-management':'elite',
}

interface PlanDef {
  plan_id: string
  name: string
  price: number
  color: string
}

function PlanCard({
  planDef, current, currencySymbol,
}: { planDef: PlanDef; current: boolean; currencySymbol: string }) {
  const { plan_id, price, color } = planDef
  const priceLabel = price === 0 ? 'Free' : `${currencySymbol}${price}/mo`
  return (
    <div className="rounded-xl p-4 transition-all"
      style={{
        background: current ? `${color}18` : 'var(--color-s3)',
        border: `1px solid ${current ? color + '55' : 'var(--color-card-border)'}`,
        opacity: current ? 1 : 0.5,
      }}>
      <div className="font-mono text-[9px] tracking-widest uppercase mb-1" style={{ color }}>
        {plan_id}
      </div>
      <div className="font-head font-bold text-sm" style={{ color: 'var(--color-tx)' }}>
        {priceLabel}
      </div>
      {current && (
        <div className="font-mono text-[9px] mt-1" style={{ color }}>REQUIRED</div>
      )}
    </div>
  )
}

interface UpgradeRequiredProps {
  feature?: string
  requiredPlan?: string
}

export default function UpgradeRequired({ feature, requiredPlan }: UpgradeRequiredProps) {
  const { state } = useLocation() as { state?: { feature?: string; requiredPlan?: string } }
  const feat    = feature     ?? state?.feature     ?? ''
  const minPlan = requiredPlan ?? state?.requiredPlan ?? FEATURE_PLAN[feat] ?? 'starter'
  const minIdx  = PLAN_ORDER.indexOf(minPlan)

  const { data: plansResponse } = useQuery({
    queryKey: ['billing-plans'],
    queryFn: () => api.get('/billing/plans').then(r => r.data).catch(() => null),
    staleTime: 5 * 60 * 1000,
  })

  const rawPlans: PlanDef[] = plansResponse?.plans ?? []
  const currencySymbol: string = plansResponse?.symbol ?? '$'

  // Build display list — use API data when available, fallback to static
  const displayPlans = PLAN_ORDER.filter(p => p !== 'community').map(id => {
    const fromApi = rawPlans.find(p => p.plan_id === id)
    return fromApi ?? {
      plan_id: id,
      name: id.charAt(0).toUpperCase() + id.slice(1),
      price: { starter: 29, trader: 79, pro: 149, elite: 299 }[id] ?? 0,
      color: FALLBACK_COLORS[id] ?? '#4f8ef7',
    }
  })

  const minPlanDef = rawPlans.find(p => p.plan_id === minPlan)
  const color = minPlanDef?.color ?? FALLBACK_COLORS[minPlan] ?? '#4f8ef7'

  return (
    <div className="min-h-screen flex items-center justify-center px-4"
      style={{ background: 'var(--color-bg)' }}>
      <div className="w-full max-w-lg text-center">

        <div className="font-mono mb-4" style={{ color: 'var(--color-tx3)', fontSize: 11, letterSpacing: 2 }}>
          ERR_PLAN_INSUFFICIENT
        </div>

        <div className="text-5xl mb-2 select-none">⬡</div>
        <div className="font-head font-bold text-2xl mb-1" style={{ color }}>
          Upgrade Required
        </div>
        <p className="text-sm" style={{ color: 'var(--color-tx2)' }}>
          {feat
            ? <>The <span className="font-mono text-xs px-1.5 py-0.5 rounded"
                style={{ background: 'var(--color-s3)', color: 'var(--color-tx)' }}>{feat}</span> feature requires</>
            : 'This feature requires'} the{' '}
          <span className="font-mono font-bold" style={{ color }}>{minPlan.toUpperCase()}</span> plan or above.
        </p>

        {/* Plan ladder */}
        <div className="grid grid-cols-4 gap-2 mt-6">
          {displayPlans.map((p, i) => (
            <PlanCard
              key={p.plan_id}
              planDef={p}
              current={i + 1 === minIdx}
              currencySymbol={currencySymbol}
            />
          ))}
        </div>

        {/* CTA */}
        <div className="rounded-2xl p-6 mt-5"
          style={{ background: 'var(--color-s2)', border: `1px solid ${color}33` }}>
          <p className="text-xs mb-4" style={{ color: 'var(--color-tx3)' }}>
            Unlock this feature and everything below by upgrading your plan. No lock-in — cancel anytime.
          </p>
          <div className="flex gap-3 justify-center">
            <Link to="/billing"
              className="font-mono text-xs px-5 py-2.5 rounded-lg font-bold transition-all"
              style={{ background: `linear-gradient(135deg, ${color}, #4f8ef7)`, color: '#05080f' }}>
              View Plans →
            </Link>
            <Link to="/dashboard"
              className="font-mono text-xs px-4 py-2.5 rounded-lg"
              style={{ background: 'var(--color-s3)', color: 'var(--color-tx2)', border: '1px solid var(--color-card-border)' }}>
              ← Dashboard
            </Link>
          </div>
        </div>

        <p className="font-mono text-[10px] mt-5" style={{ color: 'var(--color-tx3)' }}>
          TRAXOVIA AI · {minPlan.toUpperCase()} PLAN REQUIRED
        </p>
      </div>
    </div>
  )
}
