import { useState, useEffect } from 'react'
import api from '../api/client'

export default function Referral() {
  const [code, setCode] = useState('')
  const [referralUrl, setReferralUrl] = useState('')
  const [copied, setCopied] = useState(false)

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
      <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-6">
        <div className="text-xs text-gray-500 font-mono mb-2">YOUR REFERRAL CODE</div>
        <div className="font-mono text-3xl font-bold text-cyan-400 mb-3">{code || '—'}</div>
        <div className="text-sm text-gray-400 mb-4">
          Share this code. Both you and the referred user get 1 month Pro free when they subscribe.
        </div>
        {referralUrl && (
          <div className="font-mono text-xs text-gray-500 bg-slate-900/50 rounded p-2 mb-4 break-all">{referralUrl}</div>
        )}
        <button onClick={copyLink} disabled={!code}
          className="px-4 py-2 bg-cyan-400 text-black rounded text-xs font-mono font-bold hover:bg-cyan-300 disabled:opacity-40">
          {copied ? '✓ Copied!' : 'Copy Link'}
        </button>
      </div>

      <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
        <div className="text-xs text-gray-500 font-mono mb-3">HOW IT WORKS</div>
        {[
          ['Share your code',   'Send your referral link to a friend'],
          ['They sign up',      'They use your code when registering'],
          ['Both get rewarded', '1 month Pro free for you and them when they subscribe'],
        ].map(([title, desc]) => (
          <div key={title} className="flex gap-3 py-3 border-b border-slate-700/50 last:border-0">
            <div className="w-2 h-2 rounded-full bg-cyan-400 mt-1.5 shrink-0" />
            <div>
              <div className="text-sm font-medium text-gray-200">{title}</div>
              <div className="text-xs text-gray-400">{desc}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
