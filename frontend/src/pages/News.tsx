import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

interface NewsEvent {
  id:             string
  time:           string
  time_label:     string
  minutes_away:   number | null
  event:          string
  country:        string
  impact:         'high' | 'medium' | 'low'
  estimate:       string
  prev:           string
  actual:         string
  affected_pairs: string[]
}

interface NewsResponse {
  from:           string
  to:             string
  total:          number
  high_impact:    number
  medium_impact:  number
  low_impact:     number
  events:         NewsEvent[]
  message?:       string
}

const PAIRS = ['All Pairs', 'USDJPY', 'XAUUSD']
const IMPACTS = ['all', 'high', 'medium', 'low']

function impactMeta(impact: string) {
  switch (impact) {
    case 'high':   return { label: 'HIGH',   color: '#e8544f', bg: 'rgba(232,84,79,0.08)',   border: 'rgba(232,84,79,0.22)' }
    case 'medium': return { label: 'MED',    color: '#f0b429', bg: 'rgba(240,180,41,0.08)',  border: 'rgba(240,180,41,0.22)' }
    default:       return { label: 'LOW',    color: 'var(--color-tx3)', bg: 'var(--color-s3)', border: 'var(--color-card-border)' }
  }
}

function countryFlag(country: string): string {
  const flags: Record<string, string> = {
    US: '🇺🇸', EU: '🇪🇺', DE: '🇩🇪', FR: '🇫🇷', GB: '🇬🇧', UK: '🇬🇧',
    JP: '🇯🇵', AU: '🇦🇺', NZ: '🇳🇿', CN: '🇨🇳', CA: '🇨🇦', CH: '🇨🇭',
    IT: '🇮🇹', ES: '🇪🇸',
  }
  return flags[country] ?? '🌐'
}

function timingBadge(minutesAway: number | null) {
  if (minutesAway === null) return null
  if (minutesAway < 0)   return { label: 'PAST',       color: 'var(--color-tx3)' }
  if (minutesAway <= 30) return { label: `in ${minutesAway}m`, color: '#e8544f' }
  if (minutesAway <= 60) return { label: `in ${minutesAway}m`, color: '#f0b429' }
  const hrs = Math.floor(minutesAway / 60)
  const min = minutesAway % 60
  return { label: `in ${hrs}h${min > 0 ? ` ${min}m` : ''}`, color: 'var(--color-tx2)' }
}

function PairChip({ pair }: { pair: string }) {
  const colors: Record<string, string> = {
    USDJPY: '#f0b429',
    XAUUSD: '#f59e0b',
  }
  const c = colors[pair] ?? 'var(--color-tx3)'
  return (
    <span className="font-mono text-[10px] px-1.5 py-0.5 rounded"
      style={{ background: `${c}18`, color: c, border: `1px solid ${c}33` }}>
      {pair}
    </span>
  )
}

function UpcomingBanner({ events }: { events: NewsEvent[] }) {
  const soon = events.filter(e => e.minutes_away !== null && e.minutes_away >= 0 && e.minutes_away <= 30 && e.impact === 'high')
  if (!soon.length) return null
  return (
    <div className="flex items-start gap-3 px-4 py-3 rounded-xl font-mono text-xs"
      style={{ background: 'rgba(232,84,79,0.06)', border: '1px solid rgba(232,84,79,0.22)', color: '#e8544f' }}>
      <span className="shrink-0 text-sm mt-0.5">⚠</span>
      <div>
        <span className="font-bold">HIGH-IMPACT EVENT WITHIN 30 MIN — </span>
        {soon.map(e => `${e.country}: ${e.event} (${e.time_label})`).join(' · ')}
        <span className="text-tx3 ml-2">Consider reducing exposure or closing positions.</span>
      </div>
    </div>
  )
}

function LockedState() {
  return (
    <div className="space-y-5 page-enter">
      <div>
        <h1 className="text-xl font-bold text-tx font-head">Economic News</h1>
        <p className="text-tx2 text-sm mt-0.5">High-impact macro events affecting your pairs</p>
      </div>
      <div className="bg-s1 border border-s3 rounded-xl overflow-hidden">
        {/* Blurred preview rows */}
        <div className="relative">
          <div className="px-5 py-3 border-b border-s3">
            <span className="text-[10px] font-mono text-tx3 uppercase tracking-widest">Events Calendar</span>
          </div>
          <div className="select-none pointer-events-none" style={{ filter: 'blur(4px)', opacity: 0.4 }}>
            {[
              { time: '08:30 UTC', country: '🇺🇸', label: 'US', event: 'CPI m/m', impact: 'high',   est: '0.3%', prev: '0.4%' },
              { time: '10:00 UTC', country: '🇪🇺', label: 'EU', event: 'GDP Growth Rate',  impact: 'medium', est: '0.3%', prev: '0.1%' },
              { time: '12:30 UTC', country: '🇬🇧', label: 'GB', event: 'BoE Rate Decision', impact: 'high',   est: '5.0%', prev: '5.25%' },
              { time: '14:00 UTC', country: '🇯🇵', label: 'JP', event: 'Unemployment Rate', impact: 'low',    est: '2.5%', prev: '2.4%' },
            ].map((row, i) => {
              const colors: Record<string, string> = { high: '#e8544f', medium: '#f0b429', low: 'var(--color-tx3)' }
              const c = colors[row.impact]
              return (
                <div key={i} className="px-5 py-4 border-b border-s3 last:border-0 flex items-start gap-4">
                  <div className="shrink-0 w-20 text-right">
                    <div className="font-mono text-sm font-bold text-tx">{row.time}</div>
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span>{row.country}</span>
                      <span className="font-mono text-[10px] text-tx3">{row.label}</span>
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold"
                        style={{ background: `${c}18`, color: c, border: `1px solid ${c}33` }}>
                        {row.impact.toUpperCase()}
                      </span>
                    </div>
                    <div className="font-semibold text-sm text-tx mb-1.5">{row.event}</div>
                    <div className="flex gap-4">
                      <div><div className="text-[9px] font-mono text-tx3 uppercase">Forecast</div><div className="font-mono text-xs text-tx2">{row.est}</div></div>
                      <div><div className="text-[9px] font-mono text-tx3 uppercase">Previous</div><div className="font-mono text-xs text-tx2">{row.prev}</div></div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          {/* Lock overlay */}
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 px-6 text-center"
            style={{ background: 'rgba(var(--color-s1-rgb, 8,13,24), 0.7)', backdropFilter: 'blur(2px)' }}>
            <div className="text-3xl">🔒</div>
            <div>
              <div className="font-head font-bold text-lg text-tx mb-1">Starter Plan Required</div>
              <div className="text-tx2 text-sm max-w-xs">
                Get real-time economic news, impact filters, and Telegram alerts 30 minutes before high-impact events.
              </div>
            </div>
            <a
              href="/billing"
              className="px-5 py-2.5 rounded-xl font-mono text-sm font-bold transition-all hover:opacity-90"
              style={{ background: 'var(--color-cy)', color: '#000' }}
            >
              Upgrade to Starter →
            </a>
            <div className="text-tx3 font-mono text-[10px]">From $29/mo · Cancel anytime</div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function News() {
  const [selectedPair,   setSelectedPair]   = useState('All Pairs')
  const [selectedImpact, setSelectedImpact] = useState('all')
  const [date,           setDate]           = useState(() => new Date().toISOString().slice(0, 10))
  const [locked,         setLocked]         = useState(false)

  const pairParam   = selectedPair === 'All Pairs' ? undefined : selectedPair
  const impactParam = selectedImpact === 'all'     ? undefined : selectedImpact

  const { data, isLoading, isError, isFetching, refetch, dataUpdatedAt } = useQuery({
    queryKey: ['news', date, pairParam, impactParam],
    queryFn: () => {
      const params: Record<string, string> = { date }
      if (pairParam)   params.pair   = pairParam
      if (impactParam) params.impact = impactParam
      return api.get('/news', { params }).catch(err => {
        if (err.response?.status === 403) { setLocked(true) }
        return Promise.reject(err)
      }).then(r => { setLocked(false); return r.data as NewsResponse })
    },
    refetchInterval: 5 * 60_000,
    retry: false,
  })

  if (locked) return <LockedState />

  const events      = data?.events ?? []
  const lastUpdated = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : null

  return (
    <div className="space-y-5 page-enter">

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-tx font-head">Economic News</h1>
          <p className="text-tx2 text-sm mt-0.5">High-impact macro events affecting your pairs</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {lastUpdated && (
            <span className="font-mono text-[10px] text-tx3">updated {lastUpdated}</span>
          )}
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="px-3 py-1.5 rounded-lg border border-s3 text-tx2 text-xs font-mono hover:bg-s2 transition-colors disabled:opacity-50"
          >
            {isFetching ? '↻ Refreshing…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-s1 border border-s3 rounded-xl px-4 py-3 flex flex-wrap gap-4 items-center">
        {/* Date */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-tx3 uppercase tracking-widest">Date</span>
          <input
            type="date"
            value={date}
            onChange={e => setDate(e.target.value)}
            className="font-mono text-xs px-2 py-1 rounded-lg text-tx bg-s2 focus:outline-none"
            style={{ border: '1px solid var(--color-input-border)' }}
          />
        </div>

        {/* Impact */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-tx3 uppercase tracking-widest">Impact</span>
          <div className="flex gap-1">
            {IMPACTS.map(imp => {
              const active = selectedImpact === imp
              const m = imp === 'all' ? null : impactMeta(imp)
              return (
                <button
                  key={imp}
                  onClick={() => setSelectedImpact(imp)}
                  className="px-2.5 py-1 rounded-lg font-mono text-[11px] font-semibold transition-all"
                  style={active
                    ? { background: m ? m.bg : 'rgba(212,168,83,0.10)', color: m ? m.color : 'var(--color-cy)', border: `1px solid ${m ? m.border : 'rgba(212,168,83,0.3)'}` }
                    : { background: 'transparent', color: 'var(--color-tx3)', border: '1px solid transparent' }
                  }
                >
                  {imp.toUpperCase()}
                </button>
              )
            })}
          </div>
        </div>

        {/* Pair */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-tx3 uppercase tracking-widest">Pair</span>
          <div className="flex gap-1 flex-wrap">
            {PAIRS.map(p => {
              const active = selectedPair === p
              return (
                <button
                  key={p}
                  onClick={() => setSelectedPair(p)}
                  className="px-2.5 py-1 rounded-lg font-mono text-[11px] transition-all"
                  style={active
                    ? { background: 'rgba(212,168,83,0.10)', color: 'var(--color-cy)', border: '1px solid rgba(212,168,83,0.3)' }
                    : { background: 'transparent', color: 'var(--color-tx3)', border: '1px solid transparent' }
                  }
                >
                  {p === 'All Pairs' ? 'ALL' : p}
                </button>
              )
            })}
          </div>
        </div>
      </div>

      {/* Upcoming high-impact warning */}
      <UpcomingBanner events={events} />

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Total Events',  value: data?.total          ?? '—', color: 'var(--color-tx)' },
          { label: 'High Impact',   value: data?.high_impact    ?? '—', color: '#e8544f' },
          { label: 'Medium Impact', value: data?.medium_impact  ?? '—', color: '#f0b429' },
          { label: 'Low Impact',    value: data?.low_impact     ?? '—', color: 'var(--color-tx3)' },
        ].map(c => (
          <div key={c.label} className="bg-s1 border border-s3 rounded-xl p-4 card-anim">
            <div className="text-[10px] font-mono text-tx3 uppercase tracking-widest mb-1">{c.label}</div>
            <div className="text-3xl font-bold font-head" style={{ color: c.color }}>
              {isLoading ? '—' : c.value}
            </div>
          </div>
        ))}
      </div>

      {/* Events list */}
      <div className="bg-s1 border border-s3 rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-s3 flex items-center justify-between">
          <span className="text-[10px] font-mono text-tx3 uppercase tracking-widest">Events Calendar</span>
          {data && <span className="text-[10px] font-mono text-tx3">{events.length} events</span>}
        </div>

        {isLoading && (
          <div className="px-5 py-10 text-center text-tx2 text-sm animate-pulse">Fetching economic calendar…</div>
        )}

        {isError && (
          <div className="px-5 py-10 text-center space-y-2">
            <div className="font-mono text-xs" style={{ color: '#e8544f' }}>Failed to load news.</div>
            <div className="text-tx3 text-xs font-mono">Check that the Finnhub API key is set in Admin → Settings.</div>
          </div>
        )}

        {!isLoading && !isError && events.length === 0 && (
          <div className="px-5 py-10 text-center space-y-2">
            {data?.message ? (
              <>
                <div className="font-mono text-xs text-tx2">{data.message}</div>
                <div className="text-tx3 text-xs">Contact admin to upgrade your Finnhub plan for full news features.</div>
              </>
            ) : (
              <div className="text-tx3 font-mono text-xs">No events found for the selected filters.</div>
            )}
          </div>
        )}

        {!isLoading && !isError && events.map((ev, idx) => {
          const im     = impactMeta(ev.impact)
          const timing = timingBadge(ev.minutes_away)
          const isPast = ev.minutes_away !== null && ev.minutes_away < 0

          return (
            <div
              key={ev.id}
              className="px-5 py-4 border-b border-s3 last:border-0 transition-colors hover:bg-s2"
              style={{ opacity: isPast ? 0.55 : 1 }}
            >
              <div className="flex items-start gap-4 flex-wrap">

                {/* Time column */}
                <div className="shrink-0 w-20 text-right">
                  <div className="font-mono text-sm font-bold text-tx">{ev.time_label}</div>
                  {timing && (
                    <div className="font-mono text-[10px] mt-0.5" style={{ color: timing.color }}>
                      {timing.label}
                    </div>
                  )}
                </div>

                {/* Country + event */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-2">
                    <span className="text-base">{countryFlag(ev.country)}</span>
                    <span className="font-mono text-[10px] text-tx3 font-semibold tracking-widest">{ev.country}</span>
                    <span
                      className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold"
                      style={{ background: im.bg, color: im.color, border: `1px solid ${im.border}` }}
                    >
                      {im.label}
                    </span>
                    {ev.actual && (
                      <span className="px-2 py-0.5 rounded font-mono text-[10px] font-bold"
                        style={{ background: 'rgba(212,168,83,0.08)', color: 'var(--color-cy)', border: '1px solid rgba(212,168,83,0.2)' }}>
                        RELEASED
                      </span>
                    )}
                  </div>
                  <div className="font-semibold text-sm text-tx mb-2">{ev.event}</div>

                  {/* Data row */}
                  <div className="flex items-center gap-4 flex-wrap">
                    {ev.actual && (
                      <div>
                        <div className="text-[9px] font-mono text-tx3 uppercase tracking-widest">Actual</div>
                        <div className="font-mono text-xs font-bold" style={{ color: 'var(--color-cy)' }}>{ev.actual}</div>
                      </div>
                    )}
                    {ev.estimate && (
                      <div>
                        <div className="text-[9px] font-mono text-tx3 uppercase tracking-widest">Forecast</div>
                        <div className="font-mono text-xs text-tx2">{ev.estimate}</div>
                      </div>
                    )}
                    {ev.prev && (
                      <div>
                        <div className="text-[9px] font-mono text-tx3 uppercase tracking-widest">Previous</div>
                        <div className="font-mono text-xs text-tx2">{ev.prev}</div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Affected pairs */}
                {ev.affected_pairs.length > 0 && (
                  <div className="shrink-0 flex flex-col items-end gap-1">
                    <div className="text-[9px] font-mono text-tx3 uppercase tracking-widest mb-1">Affects</div>
                    <div className="flex flex-wrap gap-1 justify-end">
                      {ev.affected_pairs.map(p => <PairChip key={p} pair={p} />)}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Telegram notice */}
      <div className="flex items-center gap-3 px-4 py-3 rounded-xl font-mono text-[11px]"
        style={{ background: 'rgba(212,168,83,0.05)', border: '1px solid rgba(212,168,83,0.15)', color: 'var(--color-tx2)' }}>
        <span className="text-cy text-sm shrink-0">✈</span>
        <span>
          <span className="text-cy font-semibold">Telegram alerts active.</span>{' '}
          High-impact events are sent to your Telegram 30 min before release.
          Enable or disable under <span className="text-tx font-semibold">Settings → Notifications → News Reminders</span>.
        </span>
      </div>

    </div>
  )
}
