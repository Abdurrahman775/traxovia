import { useRef, useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'

type PlanId = 'community' | 'starter' | 'trader' | 'pro' | 'elite'

const PLAN_COLORS: Record<string, string> = {
  community: '#8899b4', starter: '#4f8ef7', trader: '#d4a853', pro: '#f0b429', elite: '#8b5cf6',
}
const PLAN_PRICES: Record<string, number> = {
  community: 0, starter: 29, trader: 79, pro: 149, elite: 299,
}

function PlanBadge({ plan }: { plan: string }) {
  const color = PLAN_COLORS[plan] ?? 'var(--color-tx2)'
  return (
    <span className="inline-flex items-center font-mono text-[9px] font-bold px-2 py-0.5 rounded tracking-widest whitespace-nowrap"
      style={{ background: `${color}22`, color, border: `1px solid ${color}44` }}>
      {plan.toUpperCase()}
    </span>
  )
}

function StatusBanner({ msg, type }: { msg: string; type: 'ok' | 'err' }) {
  const c = type === 'ok' ? '#d4a853' : '#e8544f'
  const bg = type === 'ok' ? 'rgba(212,168,83,0.08)' : 'rgba(232,84,79,0.08)'
  const border = type === 'ok' ? 'rgba(212,168,83,0.2)' : 'rgba(232,84,79,0.2)'
  return (
    <div className="font-mono text-[11px] rounded-lg px-4 py-2.5"
      style={{ background: bg, border: `1px solid ${border}`, color: c }}>
      {type === 'ok' ? '✓' : '✗'} {msg}
    </div>
  )
}

const CARD = { background: 'var(--color-s2)', border: '1px solid var(--color-card-border)', borderRadius: 14, padding: 20 }
const INPUT_STYLE: React.CSSProperties = {
  width: '100%', background: 'var(--color-s3)', border: '1px solid var(--color-input-border)',
  borderRadius: 8, padding: '10px 14px', color: 'var(--color-tx)',
  fontFamily: 'Figtree, sans-serif', fontSize: 13, outline: 'none',
}
const LABEL_STYLE: React.CSSProperties = {
  display: 'block', fontFamily: '"IBM Plex Mono",monospace',
  fontSize: 10, letterSpacing: 1, color: 'var(--color-tx3)', marginBottom: 6, textTransform: 'uppercase',
}

export default function Profile() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)

  const [displayName, setDisplayName] = useState('')
  const [nameMsg,     setNameMsg]     = useState<{ msg: string; type: 'ok' | 'err' } | null>(null)
  const [pwdForm,     setPwdForm]     = useState({ current: '', next: '', confirm: '' })
  const [pwdMsg,      setPwdMsg]      = useState<{ msg: string; type: 'ok' | 'err' } | null>(null)
  const [avatarMsg,   setAvatarMsg]   = useState<{ msg: string; type: 'ok' | 'err' } | null>(null)

  const { data: plansResponse } = useQuery({
    queryKey: ['billing-plans'],
    queryFn: () => api.get('/billing/plans').then(r => r.data).catch(() => null),
    retry: false,
  })
  const currencySymbol: string = plansResponse?.symbol ?? '$'

  const { data: profileRaw, isLoading } = useQuery({
    queryKey: ['profile'],
    queryFn: () => api.get('/profile').then(r => r.data).catch(() => null),
  })
  const profile = profileRaw as any

  useEffect(() => {
    if (profile?.display_name) setDisplayName(profile.display_name)
  }, [profile?.display_name])

  const saveName = useMutation({
    mutationFn: (display_name: string) => api.patch('/profile', { display_name }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['profile'] }); setNameMsg({ msg: 'Name updated', type: 'ok' }); setTimeout(() => setNameMsg(null), 3000) },
    onError:   () => setNameMsg({ msg: 'Failed to save', type: 'err' }),
  })

  const saveAvatar = useMutation({
    mutationFn: (avatar_url: string) => api.patch('/profile', { avatar_url }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['profile'] }); setAvatarMsg({ msg: 'Avatar updated', type: 'ok' }); setTimeout(() => setAvatarMsg(null), 3000) },
    onError:   () => setAvatarMsg({ msg: 'Failed to upload', type: 'err' }),
  })

  const changePwd = useMutation({
    mutationFn: ({ current_password, new_password }: { current_password: string; new_password: string }) =>
      api.post('/profile/change-password', { current_password, new_password }),
    onSuccess: () => { setPwdForm({ current: '', next: '', confirm: '' }); setPwdMsg({ msg: 'Password changed successfully', type: 'ok' }); setTimeout(() => setPwdMsg(null), 3000) },
    onError: (e: any) => setPwdMsg({ msg: e?.response?.data?.detail ?? 'Failed to change password', type: 'err' }),
  })

  const handleAvatarFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 300_000) { setAvatarMsg({ msg: 'Image must be under 300 KB', type: 'err' }); return }
    const reader = new FileReader()
    reader.onload = () => saveAvatar.mutate(reader.result as string)
    reader.readAsDataURL(file)
  }

  const handlePwdSubmit = () => {
    if (pwdForm.next !== pwdForm.confirm) { setPwdMsg({ msg: 'New passwords do not match', type: 'err' }); return }
    if (pwdForm.next.length < 8) { setPwdMsg({ msg: 'Password must be at least 8 characters', type: 'err' }); return }
    changePwd.mutate({ current_password: pwdForm.current, new_password: pwdForm.next })
  }

  const logout = () => {
    localStorage.removeItem('access_token')
    navigate('/login')
  }

  const avatarSrc = profile?.avatar_url
  const initials = (profile?.display_name || profile?.email || '?')
    .split(/[\s@]/).map((p: string) => p[0]).slice(0, 2).join('').toUpperCase()
  const plan = (profile?.plan as PlanId) ?? 'community'
  const planColor = PLAN_COLORS[plan]
  const joinedDate = profile?.created_at
    ? new Date(profile.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
    : '—'

  if (isLoading) return (
    <div className="flex items-center justify-center py-20">
      <span className="font-mono text-[11px]" style={{ color: 'var(--color-tx3)' }}>Loading…</span>
    </div>
  )

  return (
    <div className="space-y-5">

      {/* ── Header card: avatar + identity ── */}
      <div style={CARD}>
        <div className="flex items-center gap-6">

          {/* Avatar */}
          <div style={{ position: 'relative', flexShrink: 0 }}>
            <div style={{
              width: 80, height: 80, borderRadius: '50%', overflow: 'hidden',
              border: `2px solid ${planColor}44`,
              background: avatarSrc ? 'transparent' : `${planColor}22`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              {avatarSrc
                ? <img src={avatarSrc} alt="avatar" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                : <span className="font-head font-bold" style={{ fontSize: 24, color: planColor }}>{initials}</span>
              }
            </div>
            <button
              onClick={() => fileRef.current?.click()}
              title="Upload photo"
              style={{
                position: 'absolute', bottom: 0, right: 0,
                width: 24, height: 24, borderRadius: '50%',
                background: '#d4a853', border: '2px solid var(--color-s2)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                cursor: 'pointer', fontSize: 12,
              }}>
              ✎
            </button>
            <input ref={fileRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handleAvatarFile} />
          </div>

          {/* Identity */}
          <div style={{ flex: 1 }}>
            <div className="font-head font-bold" style={{ fontSize: 20, color: 'var(--color-tx)', marginBottom: 4 }}>
              {profile?.display_name || profile?.email?.split('@')[0] || '—'}
            </div>
            <div className="font-mono text-[11px]" style={{ color: 'var(--color-tx2)', marginBottom: 8 }}>
              {profile?.email}
            </div>
            <div className="flex items-center gap-3">
              <PlanBadge plan={plan} />
              <span className="font-mono text-[10px]" style={{ color: 'var(--color-tx3)' }}>
                {currencySymbol}{PLAN_PRICES[plan] ?? 0}/mo
              </span>
              <span className="font-mono text-[10px]" style={{ color: 'var(--color-tx3)' }}>
                · Member since {joinedDate}
              </span>
            </div>
          </div>
        </div>

        {avatarMsg && <div style={{ marginTop: 12 }}><StatusBanner {...avatarMsg} /></div>}
      </div>

      {/* ── Two-column grid: edit forms left, password + session right ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

        {/* ── Edit profile ── */}
        <div style={CARD}>
          <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
            Profile Details
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={LABEL_STYLE}>Display Name</label>
            <input
              style={INPUT_STYLE}
              value={displayName}
              placeholder="Your name"
              onChange={e => setDisplayName(e.target.value)}
              onFocus={e => (e.target as HTMLInputElement).style.borderColor = '#d4a853'}
              onBlur={e =>  (e.target as HTMLInputElement).style.borderColor = 'var(--color-input-border)'}
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={LABEL_STYLE}>Email Address</label>
            <input
              style={{ ...INPUT_STYLE, opacity: 0.5, cursor: 'not-allowed' }}
              value={profile?.email ?? ''}
              readOnly
            />
            <div className="font-mono text-[10px] mt-1" style={{ color: 'var(--color-tx3)' }}>
              Email cannot be changed. Contact support if needed.
            </div>
          </div>

          {nameMsg && <div style={{ marginBottom: 12 }}><StatusBanner {...nameMsg} /></div>}

          <button
            onClick={() => saveName.mutate(displayName)}
            disabled={saveName.isPending || !displayName.trim()}
            className="font-mono text-[11px] font-bold tracking-widest px-[18px] py-[9px] rounded-lg cursor-pointer transition-all"
            style={{ background: '#d4a853', color: '#000', border: 'none', opacity: saveName.isPending ? 0.7 : 1 }}>
            {saveName.isPending ? 'SAVING…' : 'SAVE CHANGES'}
          </button>
        </div>

        <div className="flex flex-col gap-5">

          {/* ── Change password ── */}
          <div style={CARD}>
            <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: 'var(--color-tx3)' }}>
              Change Password
            </div>

            {[
              { label: 'Current Password',  key: 'current',  placeholder: '••••••••' },
              { label: 'New Password',      key: 'next',     placeholder: 'Min 8 characters' },
              { label: 'Confirm Password',  key: 'confirm',  placeholder: 'Repeat new password' },
            ].map(f => (
              <div key={f.key} style={{ marginBottom: 14 }}>
                <label style={LABEL_STYLE}>{f.label}</label>
                <input
                  type="password"
                  style={INPUT_STYLE}
                  value={pwdForm[f.key as keyof typeof pwdForm]}
                  placeholder={f.placeholder}
                  onChange={e => setPwdForm(p => ({ ...p, [f.key]: e.target.value }))}
                  onFocus={e => (e.target as HTMLInputElement).style.borderColor = '#d4a853'}
                  onBlur={e =>  (e.target as HTMLInputElement).style.borderColor = 'var(--color-input-border)'}
                />
              </div>
            ))}

            {pwdMsg && <div style={{ marginBottom: 12 }}><StatusBanner {...pwdMsg} /></div>}

            <button
              onClick={handlePwdSubmit}
              disabled={changePwd.isPending || !pwdForm.current || !pwdForm.next || !pwdForm.confirm}
              className="font-mono text-[11px] font-bold tracking-widest px-[18px] py-[9px] rounded-lg cursor-pointer transition-all"
              style={{ background: '#d4a853', color: '#000', border: 'none', opacity: changePwd.isPending ? 0.7 : 1 }}>
              {changePwd.isPending ? 'UPDATING…' : 'UPDATE PASSWORD'}
            </button>
          </div>

          {/* ── Danger zone ── */}
          <div style={{ ...CARD, border: '1px solid rgba(232,84,79,0.15)' }}>
            <div className="font-mono text-[10px] tracking-[2px] uppercase mb-[14px]" style={{ color: '#e8544f' }}>
              Session
            </div>

            <div className="flex items-center justify-between">
              <div>
                <div style={{ fontSize: 13, color: 'var(--color-tx2)' }}>Sign out of your account</div>
                <div className="font-mono text-[10px] mt-1" style={{ color: 'var(--color-tx3)' }}>
                  You will be redirected to the login page.
                </div>
              </div>
              <button
                onClick={logout}
                className="font-mono text-[11px] font-bold tracking-widest px-[18px] py-[9px] rounded-lg cursor-pointer transition-all"
                style={{ background: 'rgba(232,84,79,0.1)', color: '#e8544f', border: '1px solid rgba(232,84,79,0.2)' }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(232,84,79,0.18)' }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(232,84,79,0.1)' }}>
                ⏻ SIGN OUT
              </button>
            </div>
          </div>

        </div>
      </div>

    </div>
  )
}
