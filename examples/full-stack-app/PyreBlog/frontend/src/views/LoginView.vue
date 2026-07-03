<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import Password from 'primevue/password'
import Button from 'primevue/button'
import { api } from '@/api/client'
import { ApiError } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import FlameLogo from '@/components/FlameLogo.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const toast = useToast()

const token = ref('')
const verifying = ref(false)

async function submit() {
  const t = token.value.trim()
  if (!t) return
  auth.setAuthorToken(t)
  verifying.value = true
  // Probe the token against the Phase A author endpoint (bearer-gated,
  // always deployed) so bad tokens are rejected with real feedback.
  try {
    await api.adminListPosts(t)
    ok()
  } catch (e) {
    if (e instanceof ApiError && e.unauthorized) {
      auth.clearAuthorToken()
      toast.add({ severity: 'error', summary: 'Token rejected', detail: 'That author token is not valid.', life: 4000 })
    } else {
      // Endpoint unreachable (network/older deployment) — accept the token;
      // Phase A writes will validate it on first use.
      ok()
    }
  } finally {
    verifying.value = false
  }
}

function ok() {
  toast.add({ severity: 'success', summary: 'Signed in', detail: 'Author tools unlocked.', life: 2500 })
  const redirect = (route.query.redirect as string) || '/compose'
  router.push(redirect)
}
</script>

<template>
  <div class="pp-page">
    <div class="login-wrap">
      <div class="login-card glass">
        <FlameLogo :size="56" />
        <h1>Author sign-in</h1>
        <p class="sub">
          PyrePress gates writing with a <strong>bearer token</strong> (Phase A). Paste your author
          token to unlock compose, edit, and moderation. It's stored only in this browser and sent
          as <code>Authorization: Bearer</code>.
        </p>

        <form @submit.prevent="submit">
          <label class="lbl" for="tok">Author token</label>
          <Password
            input-id="tok"
            v-model="token"
            :feedback="false"
            toggle-mask
            placeholder="Paste bearer token"
            class="pw"
            fluid
          />
          <Button
            type="submit"
            label="Unlock author tools"
            icon="pi pi-key"
            class="pp-flame submit"
            :loading="verifying"
            :disabled="!token.trim()"
          />
        </form>

        <div class="oidc-note">
          <i class="pi pi-info-circle" />
          <span>
            Reader sign-in for <strong>comments</strong> uses Google OIDC / Internet Identity and
            appears on each post (Phase B/C). This screen is only the author's bearer token.
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: 70vh;
  display: grid;
  place-items: center;
  padding: 2rem 1.25rem;
}
.login-card {
  max-width: 440px;
  width: 100%;
  padding: 2.5rem 2rem;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  box-shadow: var(--pp-shadow);
}
h1 {
  margin: 0.25rem 0 0;
  font-size: 1.6rem;
}
.sub {
  color: var(--pp-text-dim);
  font-size: 0.92rem;
  margin: 0 0 0.5rem;
}
form {
  width: 100%;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  margin-top: 0.5rem;
}
.lbl {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--pp-text-dim);
}
.pw {
  width: 100%;
}
.submit {
  margin-top: 0.5rem;
  justify-content: center;
}
.oidc-note {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
  text-align: left;
  margin-top: 1rem;
  padding: 0.75rem 0.9rem;
  border-radius: var(--pp-radius-sm);
  background: rgba(90, 209, 255, 0.06);
  border: 1px solid var(--pp-border);
  font-size: 0.82rem;
  color: var(--pp-text-dim);
}
.oidc-note i {
  color: var(--pp-cyan);
  margin-top: 2px;
}
</style>
