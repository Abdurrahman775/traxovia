import { getToken } from '../api/client'

export function useAdminUser(): { isAdmin: boolean; email: string } {
  try {
    const token = getToken()
    if (!token) return { isAdmin: false, email: '' }
    const payload = JSON.parse(atob(token.split('.')[1]))
    return {
      isAdmin: payload.is_admin === true,
      email:   payload.email ?? '',
    }
  } catch {
    return { isAdmin: false, email: '' }
  }
}
