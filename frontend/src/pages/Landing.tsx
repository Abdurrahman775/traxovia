import { Link } from 'react-router-dom'
import localLogo from '../logo.webp'
import bgImage from '../bg-image.webp'
import tradeImage from '../trade.webp'
import { useBranding } from '../hooks/useBranding'

const FEATURES = [
  { icon: '⬡', title: 'ICT Strategy Engine', desc: 'Order blocks, FVGs, BOS/CHoCH across D1 → M15 timeframes.' },
  { icon: '◈', title: '5-Pair Coverage', desc: 'EURUSD, GBPUSD, USDJPY, XAUUSD, AUDUSD — session-filtered killzones.' },
  { icon: '⬟', title: 'Live MT5 Execution', desc: 'Automated order placement with SL→BE management and lot sizing.' },
  { icon: '◉', title: 'Risk Circuit Breakers', desc: 'Rolling drawdown brake, daily loss cap, and correlated-pair filter.' },
  { icon: '⬡', title: 'Real-Time Dashboard', desc: 'Signal feed, trade history, analytics, and Telegram alerts.' },
  { icon: '◈', title: 'Paper → Live Pipeline', desc: 'Paper campaign with 50-trade validation gate before going live.' },
]

const STATS = [
  { value: '55%+', label: 'Win Rate' },
  { value: '+0.17R', label: 'Avg R/Trade' },
  { value: '5', label: 'Pairs Traded' },
  { value: '7-Gate', label: 'Signal Filter' },
]

export default function Landing() {
  const { app_name, app_logo_url } = useBranding()

  return (
    <div style={{ background: '#05080f', color: '#dde4f0', minHeight: '100vh', fontFamily: 'Figtree, sans-serif' }}>

      {/* ── Navbar ── */}
      <nav style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', background: 'rgba(5,8,15,0.85)', backdropFilter: 'blur(12px)', position: 'sticky', top: 0, zIndex: 50 }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 24px', height: 60, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <img src={app_logo_url} alt="logo" style={{ width: 32, height: 32, borderRadius: 8, objectFit: 'contain' }}
              onError={e => { (e.currentTarget as HTMLImageElement).src = localLogo }} />
            <span style={{ fontWeight: 700, fontSize: 16, color: '#00e5cc', letterSpacing: 0.5 }}>{app_name}</span>
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <Link to="/login" style={{ padding: '7px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600, fontFamily: 'monospace', color: '#8899b4', border: '1px solid rgba(255,255,255,0.08)', textDecoration: 'none', transition: 'color 0.15s' }}>
              Sign In
            </Link>
            <Link to="/register" style={{ padding: '7px 18px', borderRadius: 8, fontSize: 13, fontWeight: 700, fontFamily: 'monospace', background: '#00e5cc', color: '#000', textDecoration: 'none' }}>
              Get Started
            </Link>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section style={{ position: 'relative', overflow: 'hidden', padding: '100px 24px 80px' }}>
        <div style={{ position: 'absolute', inset: 0, backgroundImage: `url(${bgImage})`, backgroundSize: 'cover', backgroundPosition: 'center', opacity: 0.12 }} />
        <div style={{ position: 'absolute', inset: 0, background: 'radial-gradient(ellipse 80% 60% at 50% 0%, rgba(0,229,204,0.08) 0%, transparent 70%)' }} />
        <div style={{ position: 'relative', maxWidth: 760, margin: '0 auto', textAlign: 'center' }}>
          <div style={{ display: 'inline-block', padding: '4px 14px', borderRadius: 20, border: '1px solid rgba(0,229,204,0.25)', background: 'rgba(0,229,204,0.06)', fontSize: 11, fontFamily: 'monospace', letterSpacing: 2, color: '#00e5cc', marginBottom: 28, textTransform: 'uppercase' }}>
            ICT-Powered Algorithmic Trading
          </div>
          <h1 style={{ fontSize: 'clamp(36px, 6vw, 64px)', fontWeight: 800, lineHeight: 1.1, marginBottom: 24, letterSpacing: -1 }}>
            Institutional-Grade
            <br />
            <span style={{ background: 'linear-gradient(135deg, #00e5cc 0%, #4f8ef7 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text' }}>
              Forex Automation
            </span>
          </h1>
          <p style={{ fontSize: 17, lineHeight: 1.7, color: '#8899b4', maxWidth: 560, margin: '0 auto 40px' }}>
            Traxovia runs a 7-gate ICT strategy engine — order blocks, fair value gaps, and CHoCH confirmation — executing live trades on MT5 across 5 major pairs.
          </p>
          <div style={{ display: 'flex', gap: 14, justifyContent: 'center', flexWrap: 'wrap' }}>
            <Link to="/register" style={{ padding: '13px 32px', borderRadius: 12, fontSize: 14, fontWeight: 700, fontFamily: 'monospace', background: '#00e5cc', color: '#000', textDecoration: 'none', letterSpacing: 1 }}>
              START FREE TRIAL
            </Link>
            <Link to="/login" style={{ padding: '13px 32px', borderRadius: 12, fontSize: 14, fontWeight: 600, fontFamily: 'monospace', border: '1px solid rgba(255,255,255,0.12)', color: '#dde4f0', textDecoration: 'none' }}>
              SIGN IN
            </Link>
          </div>
        </div>
      </section>

      {/* ── Stats bar ── */}
      <section style={{ borderTop: '1px solid rgba(255,255,255,0.05)', borderBottom: '1px solid rgba(255,255,255,0.05)', background: '#080d18' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 24px', display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 0 }}>
          {STATS.map((s, i) => (
            <div key={i} style={{ textAlign: 'center', padding: '12px 0', borderRight: i < 3 ? '1px solid rgba(255,255,255,0.05)' : 'none' }}>
              <div style={{ fontSize: 28, fontWeight: 800, color: '#00e5cc', fontFamily: 'monospace', lineHeight: 1 }}>{s.value}</div>
              <div style={{ fontSize: 11, color: '#445570', marginTop: 6, letterSpacing: 1.5, textTransform: 'uppercase', fontFamily: 'monospace' }}>{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Screenshot ── */}
      <section style={{ padding: '80px 24px', maxWidth: 1100, margin: '0 auto' }}>
        <div style={{ borderRadius: 16, overflow: 'hidden', border: '1px solid rgba(255,255,255,0.07)', boxShadow: '0 40px 80px rgba(0,0,0,0.6)' }}>
          <img src={tradeImage} alt="Dashboard preview" style={{ width: '100%', display: 'block', objectFit: 'cover', maxHeight: 420 }} />
        </div>
      </section>

      {/* ── Features ── */}
      <section style={{ padding: '60px 24px 80px', maxWidth: 1100, margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: 52 }}>
          <div style={{ fontSize: 11, fontFamily: 'monospace', letterSpacing: 3, color: '#00e5cc', textTransform: 'uppercase', marginBottom: 14 }}>What's Inside</div>
          <h2 style={{ fontSize: 'clamp(24px, 4vw, 36px)', fontWeight: 700, color: '#dde4f0' }}>Built for Serious Traders</h2>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
          {FEATURES.map((f, i) => (
            <div key={i} style={{ padding: '24px 26px', borderRadius: 14, background: '#0c1220', border: '1px solid rgba(255,255,255,0.06)', transition: 'border-color 0.2s' }}>
              <div style={{ fontSize: 22, marginBottom: 14, color: '#00e5cc' }}>{f.icon}</div>
              <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 8, color: '#dde4f0' }}>{f.title}</div>
              <div style={{ fontSize: 13, color: '#8899b4', lineHeight: 1.6 }}>{f.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── CTA ── */}
      <section style={{ padding: '60px 24px 100px', textAlign: 'center' }}>
        <div style={{ maxWidth: 500, margin: '0 auto', padding: '48px 40px', borderRadius: 20, background: '#0c1220', border: '1px solid rgba(0,229,204,0.12)', boxShadow: '0 0 60px rgba(0,229,204,0.04)' }}>
          <h2 style={{ fontSize: 26, fontWeight: 700, marginBottom: 12 }}>Ready to automate?</h2>
          <p style={{ fontSize: 14, color: '#8899b4', marginBottom: 28, lineHeight: 1.6 }}>Start your free trial. No credit card required during the paper trading phase.</p>
          <Link to="/register" style={{ display: 'inline-block', padding: '12px 36px', borderRadius: 10, fontSize: 13, fontWeight: 700, fontFamily: 'monospace', background: '#00e5cc', color: '#000', textDecoration: 'none', letterSpacing: 1 }}>
            CREATE ACCOUNT
          </Link>
          <div style={{ marginTop: 18, fontSize: 12, color: '#445570', fontFamily: 'monospace' }}>
            Already have an account?{' '}
            <Link to="/login" style={{ color: '#00e5cc', textDecoration: 'none' }}>Sign in →</Link>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer style={{ borderTop: '1px solid rgba(255,255,255,0.05)', padding: '24px', textAlign: 'center' }}>
        <p style={{ fontSize: 12, color: '#445570', fontFamily: 'monospace' }}>
          © 2026 TRAXOVIA AI · All rights reserved
        </p>
      </footer>
    </div>
  )
}
