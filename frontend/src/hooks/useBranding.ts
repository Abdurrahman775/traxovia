import { useQuery } from '@tanstack/react-query'
import api from '../api/client'
import localLogo from '../logo.webp'

interface Branding {
  app_name: string
  app_logo_url: string
}

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function resolveLogoUrl(url: string | undefined | null): string {
  if (!url) return localLogo
  if (url.startsWith('/')) return `${API_BASE}${url}`
  return url
}

export function useBranding(): Branding {
  const { data } = useQuery<Branding>({
    queryKey: ['branding'],
    queryFn: () => api.get('/config/branding').then(r => r.data),
    staleTime: 5 * 60_000,
    retry: false,
    placeholderData: { app_name: 'Traxovia AI', app_logo_url: localLogo },
  })
  return {
    app_name:     data?.app_name || 'Traxovia AI',
    app_logo_url: resolveLogoUrl(data?.app_logo_url),
  }
}
