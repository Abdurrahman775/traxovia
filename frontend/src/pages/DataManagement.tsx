import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const TIMEFRAMES = ['M5', 'M15', 'M30', 'H1', 'H4', 'W1']
const ACTIVE_TFS = new Set(['M5', 'M15', 'H4'])

interface CoverageInfo {
  timeframes: Record<string, Record<string, number>>
}

interface UploadResult {
  pair:          string
  timeframe:     string
  rows_read:     number
  rows_inserted: number
  already_in_db: number
  bad_rows:      number
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}

function CoverageTable({ data, pairs }: { data: CoverageInfo; pairs: string[] }) {
  return (
    <div className="overflow-x-auto space-y-3">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-s3">
            <th className="text-left py-2.5 pr-6 text-[10px] font-mono text-tx2 uppercase tracking-widest">Pair</th>
            {TIMEFRAMES.map(tf => (
              <th key={tf} className="text-center py-2.5 px-4 text-[10px] font-mono uppercase tracking-widest">
                <span className={ACTIVE_TFS.has(tf) ? 'text-cy' : 'text-tx2 opacity-50'}>{tf}</span>
                {ACTIVE_TFS.has(tf) && (
                  <span className="block text-[8px] text-cy/50 tracking-normal normal-case mt-0.5">active</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {pairs.map((pair, i) => (
            <tr key={pair} className={`border-b border-s3/50 ${i % 2 === 0 ? '' : 'bg-s2/30'}`}>
              <td className="py-2.5 pr-6 font-mono text-sm text-cy font-medium">{pair}</td>
              {TIMEFRAMES.map(tf => {
                const count  = data.timeframes[tf]?.[pair] ?? 0
                const good   = count > 10_000
                const some   = count > 0 && !good
                const isUsed = ACTIVE_TFS.has(tf)
                return (
                  <td key={tf} className="text-center py-2.5 px-4 font-mono text-xs">
                    {count < 0
                      ? <span className="text-rd">err</span>
                      : count === 0
                        ? <span className={isUsed ? 'text-yellow-400/70' : 'text-tx2 opacity-25'}>
                            {isUsed ? 'none' : '—'}
                          </span>
                        : <span className={good ? 'text-green-400' : some ? 'text-yellow-400' : 'text-tx2'}>
                            {fmt(count)}
                          </span>
                    }
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <div className="flex flex-wrap items-center gap-4 text-[10px] font-mono text-tx2">
        <span><span className="text-green-400">■</span> &gt;10k rows (good)</span>
        <span><span className="text-yellow-400">■</span> partial</span>
        <span><span className="text-tx2 opacity-30">—</span> not used by strategy</span>
        <span><span className="text-yellow-400/70">none</span> missing — upload needed</span>
      </div>

      <div className="rounded-lg bg-s2 border border-s3/60 px-4 py-3 text-[11px] font-mono text-tx2 space-y-1">
        <p><span className="text-cy">M15 + H4</span> — core strategy timeframes (CHOCH entry + H4 bias). All 5 pairs populated via yfinance refresh.</p>
        <p><span className="text-cy">M5</span> — used for tight SL placement. Available for USDJPY &amp; XAUUSD (Dukascopy export). Upload MT5 M5 CSV for other pairs.</p>
        <p><span className="text-tx2 opacity-50">M30 / H1 / W1</span> — not read by the current strategy pipeline. Kept for reference / future use.</p>
      </div>
    </div>
  )
}

export default function DataManagement() {
  const qc = useQueryClient()

  const { data: info, isLoading: infoLoading, isError: infoError } = useQuery<CoverageInfo>({
    queryKey: ['data-info'],
    queryFn:  () => api.get('/admin/data/info').then((r: any) => r.data),
    retry: false,
  })

  // Fetch active pairs dynamically from managed_pairs
  const { data: managedPairs = [] } = useQuery<{ symbol: string }[]>({
    queryKey: ['managed-pairs'],
    queryFn:  () => api.get('/admin/pairs').then(r => r.data),
    retry: false,
  })
  const activePairs = managedPairs.map(p => p.symbol).sort()
  const pairs = activePairs.length > 0 ? activePairs : ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'XAUUSD']

  const [pair,      setPair]      = useState('')
  const selectedPair = pair || pairs[0] || ''
  const [timeframe, setTimeframe] = useState(TIMEFRAMES[0])
  const [file,      setFile]      = useState<File | null>(null)
  const [result,    setResult]    = useState<UploadResult | null>(null)
  const [error,     setError]     = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('No file selected')
      const form = new FormData()
      form.append('pair',      selectedPair)
      form.append('timeframe', timeframe)
      form.append('file',      file)
      const res = await api.post('/admin/data/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return res.data as UploadResult
    },
    onSuccess: (data) => {
      setResult(data)
      setError(null)
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      qc.invalidateQueries({ queryKey: ['data-info'] })
    },
    onError: (err: any) => {
      setError(err?.response?.data?.detail ?? err.message ?? 'Upload failed')
      setResult(null)
    },
  })

  const fileSizeMB = file ? (file.size / 1024 / 1024).toFixed(1) : null

  const selectCls = "w-full bg-s2 border border-s3 rounded-lg px-3 py-2.5 text-sm text-tx focus:outline-none focus:border-cy/50 transition-colors appearance-none"

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 space-y-6">

      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-tx">Data Management</h1>
        <p className="text-sm text-tx2 mt-0.5">
          Load historical OHLC data into TimescaleDB — use the CLI for bulk loads, the upload panel for small additions.
        </p>
      </div>

      {/* Coverage */}
      <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-tx">Database Coverage</h2>
          <button
            onClick={() => qc.invalidateQueries({ queryKey: ['data-info'] })}
            className="text-[10px] font-mono text-tx2 hover:text-cy transition-colors px-2 py-1 rounded border border-s3 hover:border-cy/40"
          >
            ↻ refresh
          </button>
        </div>

        {infoLoading && (
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-8 bg-s2 rounded animate-pulse" />
            ))}
          </div>
        )}
        {infoError && (
          <p className="text-sm text-rd">Failed to load coverage — API error</p>
        )}
        {info && <CoverageTable data={info} pairs={pairs} />}
      </div>

      {/* Upload panel */}
      <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-5">
        <div>
          <h2 className="text-sm font-semibold text-tx">Upload CSV</h2>
          <p className="text-xs text-tx2 mt-0.5">
            MT5 export format · Max 150 MB · Duplicates skipped automatically
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-[10px] font-mono text-tx2 uppercase tracking-widest block">Pair</label>
            <div className="relative">
              <select value={selectedPair} onChange={e => setPair(e.target.value)} className={selectCls}>
                {pairs.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-tx2 text-xs">▾</span>
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-[10px] font-mono text-tx2 uppercase tracking-widest block">Timeframe</label>
            <div className="relative">
              <select value={timeframe} onChange={e => setTimeframe(e.target.value)} className={selectCls}>
                {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
              </select>
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-tx2 text-xs">▾</span>
            </div>
          </div>
        </div>

        {/* File picker */}
        <div className="space-y-1.5">
          <label className="text-[10px] font-mono text-tx2 uppercase tracking-widest block">CSV File</label>
          <div
            onClick={() => fileRef.current?.click()}
            className={`w-full border border-dashed rounded-lg px-4 py-5 text-center cursor-pointer transition-colors
              ${file ? 'border-cy/50 bg-cy/5' : 'border-s3 bg-s2/50 hover:border-cy/30 hover:bg-s2'}`}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={e => {
                setFile(e.target.files?.[0] ?? null)
                setResult(null)
                setError(null)
              }}
            />
            {file ? (
              <div className="space-y-1">
                <p className="text-sm font-medium text-cy">{file.name}</p>
                <p className="text-xs text-tx2">{fileSizeMB} MB</p>
              </div>
            ) : (
              <div className="space-y-1">
                <p className="text-sm text-tx2">Click to choose a CSV file</p>
                <p className="text-xs text-tx2 opacity-50">MT5 exported format — up to 150 MB</p>
              </div>
            )}
          </div>
        </div>

        <button
          onClick={() => upload.mutate()}
          disabled={!file || upload.isPending}
          className="w-full py-2.5 rounded-lg text-sm font-semibold transition-colors
                     bg-cy text-bg hover:bg-cy/90 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {upload.isPending ? 'Importing...' : 'Upload & Import'}
        </button>

        {upload.isPending && (
          <div className="space-y-1.5">
            <div className="h-1 bg-s2 rounded-full overflow-hidden">
              <div className="h-full bg-cy animate-pulse" style={{ width: '100%' }} />
            </div>
            <p className="text-xs text-tx2">Processing rows — large files may take a minute...</p>
          </div>
        )}

        {result && (
          <div className="rounded-lg bg-green-500/10 border border-green-500/20 p-4 space-y-3">
            <p className="text-sm font-semibold text-green-400">Import complete</p>
            <div className="grid grid-cols-2 gap-x-8 gap-y-1.5 text-xs font-mono">
              <span className="text-tx2">Pair / Timeframe</span>
              <span className="text-tx">{result.pair} {result.timeframe}</span>
              <span className="text-tx2">Rows read</span>
              <span className="text-tx">{result.rows_read.toLocaleString()}</span>
              <span className="text-tx2">Rows inserted</span>
              <span className="text-green-400 font-semibold">{result.rows_inserted.toLocaleString()}</span>
              <span className="text-tx2">Already in DB</span>
              <span className="text-tx">{result.already_in_db.toLocaleString()}</span>
              {result.bad_rows > 0 && (
                <>
                  <span className="text-tx2">Skipped (bad rows)</span>
                  <span className="text-yellow-400">{result.bad_rows.toLocaleString()}</span>
                </>
              )}
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-lg bg-rd/10 border border-rd/20 p-4 space-y-1">
            <p className="text-sm font-semibold text-rd">Upload failed</p>
            <p className="text-xs text-rd/80">{error}</p>
          </div>
        )}
      </div>

      {/* CLI reference */}
      <div className="bg-s1 border border-s3 rounded-xl p-5 space-y-3">
        <h2 className="text-sm font-semibold text-tx">Bulk Load via CLI</h2>
        <p className="text-xs text-tx2">
          For initial 5-year historical data (20+ files), run the loader directly on the VPS. No size limits, faster, and resumable if a file fails.
        </p>
        <div className="bg-s2 border border-s3 rounded-lg p-4 space-y-3 font-mono text-xs">
          <div>
            <p className="text-tx2 opacity-50 mb-1"># Name files like this and drop into data/historical_csvs/</p>
            <p className="text-tx">USDJPY_M5.csv &nbsp;USDJPY_M15.csv &nbsp;XAUUSD_H4.csv</p>
          </div>
          <div>
            <p className="text-tx2 opacity-50 mb-1"># Load all files in the directory</p>
            <p className="text-cy">python -m data_engine.csv_loader</p>
          </div>
          <div>
            <p className="text-tx2 opacity-50 mb-1"># Load a single file</p>
            <p className="text-cy">python -m data_engine.csv_loader --file EURUSD_M15.csv</p>
          </div>
          <div>
            <p className="text-tx2 opacity-50 mb-1"># Load and trigger model retrain when done</p>
            <p className="text-cy">python -m data_engine.csv_loader --retrain</p>
          </div>
        </div>
      </div>

    </div>
  )
}
