import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import localLogo from '../logo.webp'
import { useBranding } from '../hooks/useBranding'
import api from '../api/client'

// Unsplash trading/finance images (free to display)
const IMGS = {
  hero:    'https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=1600&q=80&auto=format&fit=crop',
  charts:  'https://images.unsplash.com/photo-1535320903710-d993d3d77d29?w=900&q=80&auto=format&fit=crop',
  monitor: 'https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=900&q=80&auto=format&fit=crop',
  laptop:  'https://images.unsplash.com/photo-1640340434855-6084b1f4901c?w=900&q=80&auto=format&fit=crop',
}

const G   = '#d4a853'
const BG  = '#05080f'
const S1  = '#0a0e19'
const BD  = 'rgba(255,255,255,0.06)'
const TX  = '#dde4f0'
const TX2 = '#8899b4'
const TX3 = '#445570'
const W: React.CSSProperties = { maxWidth: 1100, margin: '0 auto', padding: '0 24px' }

const TICKER = ['7-Gate Signal Filter','ICT Order Blocks','FVG Detection','Live MT5 Execution','SL→Break-Even','CHoCH Confirmation','XGBoost AI Layer','Session Killzones','SHAP Explainability','Rolling DD Circuit Breaker']

const STATS = [
  { v: '55%+',  l: 'Backtest Win Rate' },
  { v: '+0.22R', l: 'Avg R / Trade' },
  { v: '5',     l: 'Pairs Traded' },
  { v: '7',     l: 'Signal Gates' },
]

const STEPS = [
  { n: '01', t: 'Connect MT5 Account',    b: 'Link your MetaTrader 5 demo or live account. Traxovia requires execution permissions only — it cannot withdraw funds. Enforced at the architecture level, not just policy.', img: 'https://images.unsplash.com/photo-1563986768609-322da13575f3?w=600&q=80&auto=format&fit=crop' },
  { n: '02', t: 'Set Risk Parameters',    b: 'Define base risk %, max trades per day, and drawdown limits. The rolling circuit breaker pauses automatically if drawdown exceeds your threshold.', img: 'https://images.unsplash.com/photo-1535320903710-d993d3d77d29?w=600&q=80&auto=format&fit=crop' },
  { n: '03', t: 'Let the Engine Trade',   b: '24/7 scanning across 5 pairs. ICT structure analysis, signal gating, lot sizing, order execution, SL management, and trade closure — fully automated.', img: 'https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=600&q=80&auto=format&fit=crop' },
]

const GATES = [
  { id: 'G1', l: 'Session Filter',    d: 'London & New York killzone windows only. No signals in low-liquidity markets.' },
  { id: 'G2', l: 'D1 Structure',      d: 'Daily bias confirmed. Break of Structure on D1 required before any entry.' },
  { id: 'G3', l: 'H4 Regime',         d: 'Trending = full size. Volatile = half size. Ranging = all signals blocked.' },
  { id: 'G4', l: 'Order Block + FVG', d: 'Price must tap a valid institutional order block with fair value gap on M15.' },
  { id: 'G5', l: 'CHoCH Entry',       d: 'Change of Character confirmation on M15 timeframe before execution.' },
  { id: 'G6', l: 'News Filter',       d: 'High-impact Finnhub events within 30 min block all signals on affected pairs.' },
  { id: 'G7', l: 'AI Confidence',     d: 'XGBoost model must score ≥ 60% probability. SHAP analysis logged per trade.' },
]

const FEATURE_LABELS: Record<string, string> = {
  dashboard:        'Web Dashboard',
  signals_web:      'Signal Viewing',
  signals_tg_drops: 'Telegram Signal Drops',
  news_feed:        'Economic News Feed',
  tg_bot_approve:   'Telegram Approve/Reject',
  tg_bot_settings:  'Telegram Settings Control',
  auto_execute:     'Auto-Execute Mode',
  copy_trade:       'Copy Trade',
  mobile_app:       'Mobile App',
  api_access:       'API Access',
  priority_support: 'Priority Support',
}

const TESTIMONIALS = [
  { q: 'The 7-gate filter is genuinely institutional. I stopped overtrading the moment I saw how strict the session and regime gates are.', name: 'James O.', loc: 'Lagos, Nigeria · Trader Plan' },
  { q: 'Paper trading gate before going live is brilliant. I watched 50 trades complete before risking real capital. That confidence is priceless.', name: 'Amara K.', loc: 'Nairobi, Kenya · Pro Plan' },
  { q: "CHoCH + order block detection on M15 is the exact ICT entry model I trade manually. Having it automated with SL→BE management saves hours daily.", name: 'Tariq M.', loc: 'Dubai, UAE · Trader Plan' },
]

// ── components ──────────────────────────────────────────────────────────────

function Ticker() {
  const all = [...TICKER, ...TICKER]
  return (
    <div style={{ background: S1, borderBottom: `1px solid ${BD}`, overflow: 'hidden', padding: '9px 0' }}>
      <style>{`@keyframes mscroll{from{transform:translateX(0)}to{transform:translateX(-50%)}}`}</style>
      <div style={{ display: 'inline-flex', animation: 'mscroll 36s linear infinite', whiteSpace: 'nowrap' }}>
        {all.map((t, i) => (
          <span key={i} style={{ fontFamily: 'IBM Plex Mono,monospace', fontSize: 10, color: TX3, letterSpacing: 1.5, textTransform: 'uppercase', padding: '0 28px' }}>
            <span style={{ color: G, marginRight: 10 }}>◆</span>{t}
          </span>
        ))}
      </div>
    </div>
  )
}

function SectionLabel({ children }: { children: string }) {
  return (
    <div style={{ display: 'inline-block', fontFamily: 'IBM Plex Mono,monospace', fontSize: 10, letterSpacing: 3, color: G, textTransform: 'uppercase', marginBottom: 16, padding: '4px 12px', border: `1px solid rgba(212,168,83,0.2)`, borderRadius: 20, background: 'rgba(212,168,83,0.05)' }}>
      {children}
    </div>
  )
}

export default function Landing() {
  const { app_name, app_logo_url } = useBranding()
  const { data: plansRes } = useQuery({
    queryKey: ['billing-plans'],
    queryFn: () => api.get('/billing/plans').then(r => r.data),
    retry: false,
    staleTime: 5 * 60_000,
  })
  const plans: any[] = plansRes?.plans ?? []
  const symbol: string = plansRes?.symbol ?? '₦'

  return (
    <div style={{ background: BG, color: TX, minHeight: '100vh', fontFamily: 'Figtree,sans-serif', overflowX: 'hidden' }}>

      {/* ── NAV ── */}
      <nav style={{ borderBottom: `1px solid ${BD}`, background: 'rgba(5,8,15,0.92)', backdropFilter: 'blur(16px)', position: 'sticky', top: 0, zIndex: 50 }}>
        <div style={{ ...W, height: 64, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <img src={app_logo_url} alt="logo" style={{ width: 32, height: 32, borderRadius: 8, objectFit: 'contain' }} onError={e => { (e.currentTarget as HTMLImageElement).src = localLogo }} />
            <span style={{ fontWeight: 800, fontSize: 18, color: G }}>{app_name}</span>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <Link to="/login" style={{ fontSize: 13, fontWeight: 600, color: TX2, textDecoration: 'none', padding: '7px 16px', borderRadius: 8, border: `1px solid ${BD}` }}>Sign In</Link>
            <Link to="/register" style={{ fontSize: 13, fontWeight: 700, color: '#000', background: G, textDecoration: 'none', padding: '8px 20px', borderRadius: 8, fontFamily: 'IBM Plex Mono,monospace' }}>Start Free Trial</Link>
          </div>
        </div>
      </nav>

      <Ticker />

      {/* ── HERO ── */}
      <section style={{ position: 'relative', overflow: 'hidden', padding: '110px 24px 90px', textAlign: 'center' }}>
        {/* trading chart background image */}
        <div style={{ position: 'absolute', inset: 0, backgroundImage: `url(${IMGS.hero})`, backgroundSize: 'cover', backgroundPosition: 'center', opacity: 0.07 }} />
        <div style={{ position: 'absolute', inset: 0, background: 'radial-gradient(ellipse 70% 50% at 50% 0%, rgba(212,168,83,0.09) 0%, transparent 65%)' }} />
        <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(180deg, transparent 40%, ${BG} 100%)` }} />
        <div style={{ position: 'relative', maxWidth: 800, margin: '0 auto' }}>
          <SectionLabel>ICT-Powered Algorithmic Forex Trading</SectionLabel>
          <h1 style={{ fontSize: 'clamp(38px, 6vw, 68px)', fontWeight: 800, lineHeight: 1.08, marginBottom: 24, letterSpacing: -1.5, color: TX }}>
            Trade With<br />
            <span style={{ background: `linear-gradient(135deg, ${G} 0%, #4f8ef7 100%)`, WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              Institutional Precision
            </span>
          </h1>
          <p style={{ fontSize: 18, lineHeight: 1.75, color: TX2, maxWidth: 580, margin: '0 auto 44px' }}>
            Traxovia runs a 7-gate ICT strategy engine — order blocks, fair value gaps, CHoCH confirmation and an XGBoost AI layer — executing automated trades on MT5 across 5 major forex pairs.
          </p>
          <div style={{ display: 'flex', gap: 14, justifyContent: 'center', flexWrap: 'wrap', marginBottom: 48 }}>
            <Link to="/register" style={{ padding: '14px 36px', borderRadius: 12, fontSize: 14, fontWeight: 700, fontFamily: 'IBM Plex Mono,monospace', background: G, color: '#000', textDecoration: 'none', letterSpacing: 0.5 }}>
              Start Free Trial
            </Link>
            <Link to="/login" style={{ padding: '14px 36px', borderRadius: 12, fontSize: 14, fontWeight: 600, fontFamily: 'IBM Plex Mono,monospace', border: `1px solid rgba(255,255,255,0.1)`, color: TX, textDecoration: 'none' }}>
              Sign In →
            </Link>
          </div>
          <div style={{ display: 'flex', gap: 20, justifyContent: 'center', flexWrap: 'wrap' }}>
            {['Paper→Live Gate','No Emotions','7-Gate Filter','MT5 Native'].map(t => (
              <span key={t} style={{ fontFamily: 'IBM Plex Mono,monospace', fontSize: 11, color: TX3, letterSpacing: 1 }}>
                <span style={{ color: G, marginRight: 6 }}>✓</span>{t}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ── STATS BAR ── */}
      <section style={{ borderTop: `1px solid ${BD}`, borderBottom: `1px solid ${BD}`, background: S1 }}>
        <div style={{ ...W, padding: '0 24px', display: 'grid', gridTemplateColumns: 'repeat(4,1fr)' }}>
          {STATS.map((s, i) => (
            <div key={i} style={{ textAlign: 'center', padding: '28px 0', borderRight: i < 3 ? `1px solid ${BD}` : 'none' }}>
              <div style={{ fontSize: 32, fontWeight: 800, color: G, fontFamily: 'IBM Plex Mono,monospace', lineHeight: 1 }}>{s.v}</div>
              <div style={{ fontSize: 11, color: TX3, marginTop: 6, letterSpacing: 2, textTransform: 'uppercase', fontFamily: 'IBM Plex Mono,monospace' }}>{s.l}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── DASHBOARD PREVIEW ── */}
      <section style={{ padding: '72px 24px' }}>
        <div style={{ ...W }}>
          <div style={{ borderRadius: 20, overflow: 'hidden', border: `1px solid rgba(212,168,83,0.15)`, boxShadow: '0 40px 100px rgba(0,0,0,0.7)', position: 'relative' }}>
            {/* fake browser chrome */}
            <div style={{ background: '#0d1117', borderBottom: `1px solid ${BD}`, padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#e8544f', display: 'inline-block' }} />
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#f0b429', display: 'inline-block' }} />
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#3dce8e', display: 'inline-block' }} />
              <span style={{ fontFamily: 'IBM Plex Mono,monospace', fontSize: 11, color: TX3, marginLeft: 12 }}>app.traxovia.ai — Live Dashboard</span>
            </div>
            <img src={IMGS.monitor} alt="Trading dashboard" style={{ width: '100%', display: 'block', maxHeight: 460, objectFit: 'cover', objectPosition: 'top' }} />
            <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: '40%', background: `linear-gradient(to top, ${BG}, transparent)` }} />
          </div>
        </div>
      </section>

      {/* ── HOW IT WORKS ── */}
      <section style={{ padding: '96px 24px' }}>
        <div style={{ ...W }}>
          <div style={{ textAlign: 'center', marginBottom: 64 }}>
            <SectionLabel>How It Works</SectionLabel>
            <h2 style={{ fontSize: 'clamp(26px,4vw,40px)', fontWeight: 700, color: TX, marginBottom: 12 }}>Three Steps. Five Minutes Setup.</h2>
            <p style={{ color: TX2, fontSize: 15, maxWidth: 460, margin: '0 auto' }}>Then it runs itself, around the clock, every trading day.</p>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 20 }}>
            {STEPS.map(s => (
              <div key={s.n} style={{ borderRadius: 16, background: S1, border: `1px solid ${BD}`, position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                <div style={{ height: 160, overflow: 'hidden', position: 'relative' }}>
                  <img src={s.img} alt={s.t} style={{ width: '100%', height: '100%', objectFit: 'cover', opacity: 0.6 }} />
                  <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(to bottom, transparent 30%, ${S1} 100%)` }} />
                  <div style={{ position: 'absolute', top: 12, left: 16, fontFamily: 'IBM Plex Mono,monospace', fontSize: 10, color: G, letterSpacing: 2, textTransform: 'uppercase', background: 'rgba(10,14,25,0.7)', padding: '3px 8px', borderRadius: 4, backdropFilter: 'blur(4px)' }}>Step {s.n}</div>
                </div>
                <div style={{ padding: '20px 28px 28px' }}>
                  <div style={{ position: 'absolute', top: 20, right: 24, fontFamily: 'IBM Plex Mono,monospace', fontSize: 52, fontWeight: 800, color: 'rgba(212,168,83,0.05)', lineHeight: 1 }}>{s.n}</div>
                  <h3 style={{ fontSize: 18, fontWeight: 700, color: TX, marginBottom: 10 }}>{s.t}</h3>
                  <p style={{ fontSize: 14, color: TX2, lineHeight: 1.7 }}>{s.b}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>


      {/* ── 7-GATE SIGNAL ENGINE ── */}
      <section style={{ padding: '0 24px 96px' }}>
        <div style={{ ...W }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 48, alignItems: 'start' }}>
            <div>
              <SectionLabel>Signal Intelligence</SectionLabel>
              <h2 style={{ fontSize: 'clamp(24px,3.5vw,36px)', fontWeight: 700, color: TX, marginBottom: 16 }}>7-Gate Signal Filter</h2>
              <p style={{ fontSize: 15, color: TX2, lineHeight: 1.7, marginBottom: 20 }}>
                Every candidate signal passes through 7 independent gates before a single order is placed. One gate failure = no trade. No exceptions.
              </p>
              <div style={{ borderRadius: 12, overflow: 'hidden', marginBottom: 20, border: `1px solid ${BD}` }}>
                <img src={IMGS.charts} alt="Trading charts analysis" style={{ width: '100%', height: 200, objectFit: 'cover', display: 'block', opacity: 0.75 }} />
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {['EURUSD','GBPUSD','USDJPY','XAUUSD','AUDUSD'].map(p => (
                  <span key={p} style={{ fontFamily: 'IBM Plex Mono,monospace', fontSize: 11, color: G, border: `1px solid rgba(212,168,83,0.25)`, borderRadius: 6, padding: '4px 10px', background: 'rgba(212,168,83,0.06)' }}>{p}</span>
                ))}
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {GATES.map((g, i) => (
                <div key={g.id} style={{ display: 'flex', gap: 14, padding: '14px 16px', borderRadius: 10, background: S1, border: `1px solid ${BD}`, alignItems: 'flex-start' }}>
                  <div style={{ flexShrink: 0, width: 28, height: 28, borderRadius: 8, background: `rgba(212,168,83,${0.06 + i * 0.015})`, border: `1px solid rgba(212,168,83,0.2)`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'IBM Plex Mono,monospace', fontSize: 10, color: G, fontWeight: 700 }}>{g.id}</div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: TX, marginBottom: 3 }}>{g.l}</div>
                    <div style={{ fontSize: 12, color: TX2, lineHeight: 1.5 }}>{g.d}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── PRICING ── */}
      <section style={{ padding: '0 24px 96px', background: `linear-gradient(180deg, ${BG} 0%, ${S1} 100%)` }}>
        <div style={{ ...W }}>
          <div style={{ textAlign: 'center', marginBottom: 56 }}>
            <SectionLabel>Pricing</SectionLabel>
            <h2 style={{ fontSize: 'clamp(26px,4vw,38px)', fontWeight: 700, color: TX, marginBottom: 12 }}>Simple, Transparent Pricing</h2>
            <p style={{ color: TX2, fontSize: 15 }}>Start free during paper trading. Upgrade when you go live.</p>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 16 }}>
            {plans.map((p: any) => {
              const feats = p.features ?? {}
              const featKeys = Object.keys(FEATURE_LABELS).filter(k => feats[k])
              const missingCount = Math.max(0, 6 - featKeys.length)
              return (
                <div key={p.plan_id} style={{ padding: '28px 24px', borderRadius: 16, background: p.popular ? 'rgba(212,168,83,0.04)' : S1, border: `1px solid ${p.popular ? 'rgba(212,168,83,0.3)' : BD}`, position: 'relative', display: 'flex', flexDirection: 'column' }}>
                  {p.popular && (
                    <div style={{ position: 'absolute', top: -1, left: '50%', transform: 'translateX(-50%)', background: G, color: '#000', fontFamily: 'IBM Plex Mono,monospace', fontSize: 9, fontWeight: 700, letterSpacing: 1.5, padding: '3px 12px', borderRadius: '0 0 8px 8px' }}>MOST POPULAR</div>
                  )}
                  <div style={{ fontFamily: 'IBM Plex Mono,monospace', fontSize: 11, color: p.color, letterSpacing: 2, textTransform: 'uppercase', marginBottom: 8 }}>{p.name}</div>
                  <div style={{ fontSize: 34, fontWeight: 800, color: TX, marginBottom: 4, lineHeight: 1 }}>{p.price === 0 ? 'FREE' : `${symbol}${Number(p.price).toLocaleString()}`}</div>
                  <div style={{ fontSize: 12, color: TX3, fontFamily: 'IBM Plex Mono,monospace', marginBottom: 24 }}>/month</div>
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 9, marginBottom: 24 }}>
                    {featKeys.slice(0, 6).map(k => (
                      <div key={k} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, color: TX2 }}>
                        <span style={{ color: G, flexShrink: 0 }}>✓</span>{FEATURE_LABELS[k]}
                      </div>
                    ))}
                    {Array.from({ length: missingCount }).map((_, i) => (
                      <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, color: TX3 }}>
                        <span style={{ color: TX3, flexShrink: 0 }}>—</span><span style={{ opacity: 0.4 }}>—</span>
                      </div>
                    ))}
                  </div>
                  <Link to="/register" style={{ display: 'block', textAlign: 'center', padding: '10px 0', borderRadius: 8, fontFamily: 'IBM Plex Mono,monospace', fontSize: 12, fontWeight: 700, textDecoration: 'none', background: p.popular ? G : 'transparent', color: p.popular ? '#000' : p.color, border: p.popular ? 'none' : `1px solid ${p.color}44` }}>
                    {p.price === 0 ? 'Get Started Free' : `Get ${p.name}`}
                  </Link>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      {/* ── TESTIMONIALS ── */}
      <section style={{ padding: '0 24px 96px' }}>
        <div style={{ ...W }}>
          <div style={{ textAlign: 'center', marginBottom: 52 }}>
            <SectionLabel>Traders Say</SectionLabel>
            <h2 style={{ fontSize: 'clamp(24px,3.5vw,36px)', fontWeight: 700, color: TX }}>What Early Users Are Saying</h2>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 16 }}>
            {TESTIMONIALS.map((t, i) => (
              <div key={i} style={{ padding: '28px', borderRadius: 14, background: S1, border: `1px solid ${BD}` }}>
                <div style={{ fontSize: 32, color: G, lineHeight: 1, marginBottom: 16, opacity: 0.5 }}>"</div>
                <p style={{ fontSize: 14, color: TX2, lineHeight: 1.75, marginBottom: 20, fontStyle: 'italic' }}>{t.q}</p>
                <div style={{ fontWeight: 700, fontSize: 13, color: TX }}>{t.name}</div>
                <div style={{ fontFamily: 'IBM Plex Mono,monospace', fontSize: 10, color: TX3, marginTop: 3 }}>{t.loc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section style={{ padding: '0 24px 100px', textAlign: 'center', position: 'relative' }}>
        <div style={{ position: 'absolute', inset: 0, backgroundImage: `url(${IMGS.laptop})`, backgroundSize: 'cover', backgroundPosition: 'center', opacity: 0.04 }} />
        <div style={{ maxWidth: 560, margin: '0 auto', padding: '56px 40px', borderRadius: 24, background: S1, border: `1px solid rgba(212,168,83,0.15)`, boxShadow: '0 0 80px rgba(212,168,83,0.05)' }}>
          <SectionLabel>Get Started Today</SectionLabel>
          <h2 style={{ fontSize: 30, fontWeight: 800, color: TX, marginBottom: 12 }}>Start Trading Smarter.</h2>
          <p style={{ fontSize: 15, color: TX2, lineHeight: 1.7, marginBottom: 32 }}>
            Free during the paper trading phase. 50-trade validation gate. No credit card required until you go live.
          </p>
          <Link to="/register" style={{ display: 'inline-block', padding: '14px 40px', borderRadius: 12, fontSize: 14, fontWeight: 700, fontFamily: 'IBM Plex Mono,monospace', background: G, color: '#000', textDecoration: 'none', marginBottom: 16 }}>
            Create Free Account
          </Link>
          <div style={{ fontSize: 12, color: TX3, fontFamily: 'IBM Plex Mono,monospace' }}>
            Already have an account?{' '}
            <Link to="/login" style={{ color: G, textDecoration: 'none' }}>Sign in →</Link>
          </div>
        </div>
      </section>

      {/* ── FOOTER ── */}
      <footer style={{ borderTop: `1px solid ${BD}`, background: S1, padding: '48px 24px 32px' }}>
        <div style={{ ...W }}>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr', gap: 40, marginBottom: 40 }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                <img src={app_logo_url} alt="logo" style={{ width: 28, height: 28, borderRadius: 6, objectFit: 'contain' }} onError={e => { (e.currentTarget as HTMLImageElement).src = localLogo }} />
                <span style={{ fontWeight: 800, fontSize: 16, color: G }}>{app_name}</span>
              </div>
              <p style={{ fontSize: 13, color: TX3, lineHeight: 1.65, maxWidth: 260 }}>Institutional-grade ICT forex automation. Paper→live validation gate. No emotion, pure data.</p>
              <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
                {['7-Gate Filter','MT5 Native','ICT Strategy'].map(t => (
                  <span key={t} style={{ fontFamily: 'IBM Plex Mono,monospace', fontSize: 9, color: TX3, border: `1px solid ${BD}`, borderRadius: 4, padding: '3px 8px' }}>{t}</span>
                ))}
              </div>
            </div>
            {[
              { h: 'Platform', links: ['Dashboard','Signals','Analytics','Regime Detector'] },
              { h: 'Account',  links: ['Sign In','Register','Billing','Settings'] },
              { h: 'Support',  links: ['Documentation','Telegram Bot','Paper Trading','FAQ'] },
            ].map(col => (
              <div key={col.h}>
                <div style={{ fontFamily: 'IBM Plex Mono,monospace', fontSize: 10, color: TX3, letterSpacing: 2, textTransform: 'uppercase', marginBottom: 14 }}>{col.h}</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {col.links.map(l => (
                    <Link key={l} to="/login" style={{ fontSize: 13, color: TX2, textDecoration: 'none' }}>{l}</Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div style={{ borderTop: `1px solid ${BD}`, paddingTop: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <span style={{ fontFamily: 'IBM Plex Mono,monospace', fontSize: 11, color: TX3 }}>© 2026 TRAXOVIA AI · All rights reserved</span>
            <span style={{ fontFamily: 'IBM Plex Mono,monospace', fontSize: 11, color: TX3 }}>Past performance does not guarantee future results. Trade responsibly.</span>
          </div>
        </div>
      </footer>

    </div>
  )
}
