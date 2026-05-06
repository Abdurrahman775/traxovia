/**
 * Decodes the JWT from localStorage and returns admin status + email.
 * No API call needed — the plan is embedded in the token.
 */
export function useAdminUser(): { isAdmin: boolean; email: string } {
  try {
    const token = localStorage.getItem('access_token')
    if (!token) return { isAdmin: false, email: '' }
    const payload = JSON.parse(atob(token.split('.')[1]))
    return {
      isAdmin: payload.plan === 'elite',
      email:   payload.email ?? '',
    }
  } catch {
    return { isAdmin: false, email: '' }
  }
}
