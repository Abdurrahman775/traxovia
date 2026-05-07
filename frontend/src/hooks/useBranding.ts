import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

interface Branding {
  app_name: string
  app_logo_url: string
}

const FALLBACK: Branding = { app_name: 'Trading AI', app_logo_url: '' }

export function useBranding(): Branding {
  const { data } = useQuery<Branding>({
    queryKey: ['branding'],
    queryFn: () => api.get('/config/branding').then(r => r.data),
    staleTime: 5 * 60_000,
    retry: false,
  })
  return data ?? FALLBACK
}
