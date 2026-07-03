import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { Session } from '@/api/types'

const TOKEN_KEY = 'pyrepress.authorToken'
const SESSION_KEY = 'pyrepress.session'

// Two independent identities:
//  - authorToken: the bearer token gating compose/edit/moderate (Phase A).
//  - session: a signed-in commenter identity (Phase C, may be stubbed).
export const useAuthStore = defineStore('auth', () => {
  const authorToken = ref<string>(localStorage.getItem(TOKEN_KEY) ?? '')

  const session = ref<Session | null>(readSession())

  const isAuthor = computed(() => authorToken.value.trim().length > 0)
  const isSignedIn = computed(() => session.value !== null)

  function setAuthorToken(token: string) {
    authorToken.value = token.trim()
    if (authorToken.value) localStorage.setItem(TOKEN_KEY, authorToken.value)
    else localStorage.removeItem(TOKEN_KEY)
  }

  function clearAuthorToken() {
    setAuthorToken('')
  }

  function setSession(s: Session | null) {
    session.value = s
    if (s) localStorage.setItem(SESSION_KEY, JSON.stringify(s))
    else localStorage.removeItem(SESSION_KEY)
  }

  function signOut() {
    setSession(null)
  }

  function readSession(): Session | null {
    try {
      const raw = localStorage.getItem(SESSION_KEY)
      return raw ? (JSON.parse(raw) as Session) : null
    } catch {
      return null
    }
  }

  return {
    authorToken,
    session,
    isAuthor,
    isSignedIn,
    setAuthorToken,
    clearAuthorToken,
    setSession,
    signOut,
  }
})
