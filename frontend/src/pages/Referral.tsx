import { useState, useEffect } from 'react'
import api from '../api/client'

export default function Referral() {
  const [code,        setCode]        = useState('')
  const [referralUrl, setReferralUrl] = useState('')
  const [copied,      setCopied]      = useState(false)

  useEffect(() => {
    api.get('/referral/my-code')
      .then(res => { setCode(res.data.referral_code); setReferralUrl(res.data.referral_url) })
      .catch(console.error)
  }, [])

  const copyLink = () => {
    navigator.clipboard.writeText(referralUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-4">

      <div>
        <h1 className="text-xl font-bold text-tx font-head">Referral</h1>
        <p className="text-tx2 text-sm mt-0.5">Invite friends and earn rewards together</p>
      </div>

      {/* Code card */}
      <div className="bg-s1 border border-s3 rounded-xl p-6 space-y-4">
        <div className="text-[10px] font-mono tracking-widest uppercase text-tx3">Your Referral Code</div>

        <div className="font-head font-bold text-4xl text-cy tracking-widest">
          {code || '—'}
        </div>

        <p className="text-sm text-tx2">
          Share this code with a friend. Both of you get <span className="text-cy font-semibold">1 month Pro free</span> when they subscribe.
        </p>

        {referralUrl && (
          <div className="px-3 py-2 rounded-lg font-mono text-xs text-tx2 break-all"
            style={{ background: 'var(--color-s2)', border: '1px solid var(--color-card-border)' }}>
            {referralUrl}
          </div>
        )}

        <button
          onClick={copyLink}
          disabled={!code}
          className="px-5 py-2.5 rounded-lg font-mono font-bold text-xs tracking-widest transition-colors disabled:opacity-40"
          style={{ background: copied ? 'rgba(0,229,204,0.15)' : '#00e5cc', color: copied ? 'var(--color-cy)' : '#000', border: copied ? '1px solid rgba(0,229,204,0.4)' : 'none' }}
        >
          {copied ? '✓ Copied!' : 'Copy Link'}
        </button>
      </div>

      {/* How it works */}
      <div className="bg-s1 border border-s3 rounded-xl p-5">
        <div className="text-[10px] font-mono tracking-widest uppercase text-tx3 mb-4">How It Works</div>
        <div className="space-y-0">
          {[
            ['Share your code',   'Send your referral link to a friend'],
            ['They sign up',      'They register using your referral code'],
            ['Both get rewarded', '1 month Pro free for you and them when they subscribe'],
          ].map(([title, desc], i) => (
            <div key={title} className="flex gap-4 py-3.5"
              style={{ borderBottom: i < 2 ? '1px solid var(--color-divider)' : 'none' }}>
              <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 font-mono text-xs font-bold text-cy"
                style={{ background: 'rgba(0,229,204,0.1)', border: '1px solid rgba(0,229,204,0.2)' }}>
                {i + 1}
              </div>
              <div>
                <div className="text-sm font-semibold text-tx">{title}</div>
                <div className="text-xs text-tx2 mt-0.5">{desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
