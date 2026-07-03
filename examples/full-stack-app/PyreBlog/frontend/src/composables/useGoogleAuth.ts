// Thin loader for Google Identity Services (GIS). Only used when a public
// VITE_GOOGLE_CLIENT_ID is configured. If absent, the caller shows a graceful
// "sign in to comment" placeholder instead (Phase B/C may not have landed).

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? ''
const GIS_SRC = 'https://accounts.google.com/gsi/client'

let loaded: Promise<boolean> | null = null

export const googleConfigured = () => CLIENT_ID.trim().length > 0

function loadScript(): Promise<boolean> {
  if (!googleConfigured()) return Promise.resolve(false)
  if (loaded) return loaded
  loaded = new Promise<boolean>((resolve) => {
    if ((window as unknown as { google?: unknown }).google) return resolve(true)
    const s = document.createElement('script')
    s.src = GIS_SRC
    s.async = true
    s.defer = true
    s.onload = () => resolve(true)
    s.onerror = () => resolve(false)
    document.head.appendChild(s)
  })
  return loaded
}

// Render the Google button into `el`; `onToken` receives the ID token (JWT)
// which the frontend forwards to POST /auth/login for in-canister RS256 verify.
export async function renderGoogleButton(
  el: HTMLElement,
  onToken: (idToken: string) => void,
): Promise<boolean> {
  const ok = await loadScript()
  if (!ok) return false
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const g = (window as any).google
  if (!g?.accounts?.id) return false
  g.accounts.id.initialize({
    client_id: CLIENT_ID,
    callback: (resp: { credential: string }) => onToken(resp.credential),
  })
  g.accounts.id.renderButton(el, {
    theme: 'filled_black',
    size: 'large',
    shape: 'pill',
    text: 'signin_with',
  })
  return true
}
