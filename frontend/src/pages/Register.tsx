import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'

export default function Register() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await api.post('/auth/register', { email, password })
      const res = await api.post('/auth/login', { email, password })
      localStorage.setItem('access_token', res.data.access_token)
      navigate('/dashboard')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center">
      <div className="w-full max-w-sm bg-slate-800/50 border border-slate-700 rounded-xl p-8">
        <div className="font-bold text-cyan-400 text-xl mb-6 font-mono">CREATE ACCOUNT</div>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="text-xs text-gray-400 font-mono">EMAIL</label>
            <input value={email} onChange={e => setEmail(e.target.value)}
              type="email" required autoFocus
              className="w-full mt-1 px-3 py-2 bg-slate-900 border border-slate-600 rounded text-sm text-gray-200 focus:outline-none focus:border-cyan-400" />
          </div>
          <div>
            <label className="text-xs text-gray-400 font-mono">PASSWORD</label>
            <input value={password} onChange={e => setPassword(e.target.value)}
              type="password" required minLength={8}
              className="w-full mt-1 px-3 py-2 bg-slate-900 border border-slate-600 rounded text-sm text-gray-200 focus:outline-none focus:border-cyan-400" />
          </div>
          {error && <div className="text-xs text-red-400 font-mono">{error}</div>}
          <button type="submit" disabled={loading}
            className="w-full py-2.5 bg-cyan-400 text-black font-bold font-mono text-sm rounded hover:bg-cyan-300 disabled:opacity-50">
            {loading ? 'CREATING...' : 'CREATE ACCOUNT'}
          </button>
        </form>
        <div className="mt-4 text-center text-xs text-gray-500">
          Have an account?{' '}
          <a href="/login" className="text-cyan-400 hover:underline">Sign in</a>
        </div>
      </div>
    </div>
  )
}
