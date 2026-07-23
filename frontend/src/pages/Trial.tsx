import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'

interface TrialStatus {
  plan: string
  trial_active: boolean
  trial_expires_at: string | null
}

const TRIAL_FEATURES = [
  'Full web dashboard access',
  'Live signal viewing + approvals',
  'Telegram bot commands (Trader tier)',
  'Economic news feed',
  'MT5 account binding (1 account)',
  'Paper trading mode (no real money)',
  'Analytics & performance tracking',
]

function daysLeft(iso: string): number {
  const diff = new Date(iso).getTime() - Date.now()
  return Math.max(0, Math.ceil(diff / 86_400_000))
}

export default function Trial() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [startError, setStartError] = useState<string | null>(null)

  const { data: status, isLoading } = useQuery<TrialStatus>({
    queryKey: ['trial-status'],
    queryFn: () => api.get('/trial/status').then(r => r.data),
    retry: 1,
  })

  const startMutation = useMutation({
    mutationFn: () => api.post('/trial/start').then(r => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trial-status'] })
      queryClient.invalidateQueries({ queryKey: ['subscription'] })
      setStartError(null)
    },
    onError: (err: any) => {
      setStartError(err?.response?.data?.detail || 'Failed to start trial. Please try again.')
    },
  })

  const isActive   = status?.trial_active
  const isExpired  = !isActive && status?.plan === 'trial'
  const canStart   = !isActive && !isExpired && status?.plan === 'community'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 560, margin: '0 auto' }}>

      {/* Header */}
      <div
        className="rounded-[14px] p-6"
        style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}
      >
        <div className="font-mono text-[10px] tracking-[2px] uppercase mb-2" style={{ color: 'var(--color-tx3)' }}>
          Free Trial
        </div>
        <div className="font-head text-[26px] font-bold mb-1" style={{ color: '#d4a853' }}>
          14-Day Trial
        </div>
        <p className="font-mono text-[12px]" style={{ color: 'var(--color-tx2)' }}>
          Try Traxovia AI at Trader-tier level — paper trading, no real money at risk.
        </p>
      </div>

      {/* Status banner */}
      {!isLoading && (
        <>
          {isActive && status?.trial_expires_at && (
            <div
              className="flex items-center gap-3 rounded-[10px] px-4 py-3"
              style={{ background: 'rgba(212,168,83,0.08)', border: '1px solid rgba(212,168,83,0.25)' }}
            >
              <span style={{ color: '#d4a853', fontSize: 18 }}>✓</span>
              <div>
                <div className="font-mono text-[11px] font-bold" style={{ color: '#d4a853' }}>
                  Trial Active — {daysLeft(status.trial_expires_at)} day{daysLeft(status.trial_expires_at) !== 1 ? 's' : ''} remaining
                </div>
                <div className="font-mono text-[10px] mt-0.5" style={{ color: 'var(--color-tx3)' }}>
                  Expires {new Date(status.trial_expires_at).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
                </div>
              </div>
            </div>
          )}

          {isExpired && (
            <div
              className="flex items-center gap-3 rounded-[10px] px-4 py-3"
              style={{ background: 'rgba(255,107,122,0.08)', border: '1px solid rgba(255,107,122,0.25)' }}
            >
              <span style={{ color: '#ff6b7a', fontSize: 18 }}>✗</span>
              <div>
                <div className="font-mono text-[11px] font-bold" style={{ color: '#ff6b7a' }}>
                  Trial Expired
                </div>
                <div className="font-mono text-[10px] mt-0.5" style={{ color: 'var(--color-tx3)' }}>
                  Upgrade to a paid plan to continue full access.
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {/* Start error */}
      {startError && (
        <div
          className="rounded-[10px] px-4 py-3 font-mono text-[11px]"
          style={{ background: 'rgba(255,107,122,0.08)', border: '1px solid rgba(255,107,122,0.25)', color: '#ff6b7a' }}
        >
          {startError}
        </div>
      )}

      {/* Features list */}
      <div
        className="rounded-[14px] p-5"
        style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}
      >
        <div className="font-mono text-[10px] tracking-[2px] uppercase mb-4" style={{ color: 'var(--color-tx3)' }}>
          What's Included
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {TRIAL_FEATURES.map(f => (
            <div key={f} className="flex items-center gap-3 font-mono text-[12px]" style={{ color: 'var(--color-tx2)' }}>
              <span style={{ color: '#d4a853', flexShrink: 0 }}>✓</span>
              {f}
            </div>
          ))}
        </div>
      </div>

      {/* CTA */}
      {canStart && (
        <button
          onClick={() => startMutation.mutate()}
          disabled={startMutation.isPending}
          className="font-mono text-[12px] font-bold tracking-widest px-6 py-3 rounded-[10px] transition-all"
          style={{
            background: startMutation.isPending ? 'rgba(212,168,83,0.15)' : '#d4a853',
            color: startMutation.isPending ? '#d4a853' : '#000',
            border: '1px solid rgba(212,168,83,0.4)',
            cursor: startMutation.isPending ? 'not-allowed' : 'pointer',
          }}
        >
          {startMutation.isPending ? '⏳ Starting…' : 'Start Free 14-Day Trial →'}
        </button>
      )}

      {(isActive || isExpired) && (
        <button
          onClick={() => navigate('/billing')}
          className="font-mono text-[12px] font-bold tracking-widest px-6 py-3 rounded-[10px] transition-all"
          style={{
            background: 'var(--color-divider)',
            color: 'var(--color-tx2)',
            border: '1px solid var(--color-card-border)',
            cursor: 'pointer',
          }}
          onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.09)' }}
          onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'var(--color-divider)' }}
        >
          {isExpired ? 'Upgrade to a Paid Plan →' : 'View Paid Plans →'}
        </button>
      )}

      {/* Note */}
      <p className="font-mono text-[10px] text-center" style={{ color: 'var(--color-tx3)' }}>
        Trial runs in <strong>paper mode</strong> — no real trades are executed. One trial per account.
      </p>

    </div>
  )
}
