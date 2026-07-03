<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useToast } from 'primevue/usetoast'
import Textarea from 'primevue/textarea'
import Button from 'primevue/button'
import { api } from '@/api/client'
import { ApiError, type Comment } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { googleConfigured, renderGoogleButton } from '@/composables/useGoogleAuth'
import { relativeTime } from '@/utils/format'
import EmptyState from './EmptyState.vue'

const props = defineProps<{ slug: string }>()
const auth = useAuthStore()
const toast = useToast()

const comments = ref<Comment[]>([])
const loading = ref(true)
// null = unknown; true = endpoint present; false = not deployed (404)
const commentsEnabled = ref<boolean | null>(null)
const draft = ref('')
const submitting = ref(false)
const googleBtn = ref<HTMLElement | null>(null)
const googleReady = ref(false)

const MAX = 2000

async function loadComments() {
  loading.value = true
  try {
    const res = await api.listComments(props.slug)
    comments.value = res.items ?? []
    commentsEnabled.value = true
  } catch (e) {
    if (e instanceof ApiError && e.notFound) {
      commentsEnabled.value = false
    } else {
      commentsEnabled.value = true // endpoint exists but errored
    }
    comments.value = []
  } finally {
    loading.value = false
  }
}

async function setupSignIn() {
  if (!googleConfigured() || auth.isSignedIn) return
  await new Promise((r) => setTimeout(r, 0))
  if (!googleBtn.value) return
  googleReady.value = await renderGoogleButton(googleBtn.value, onGoogleToken)
}

async function onGoogleToken(idToken: string) {
  try {
    const session = await api.login('google', idToken)
    auth.setSession(session)
    toast.add({ severity: 'success', summary: 'Signed in', life: 2500 })
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : 'Sign-in failed'
    toast.add({ severity: 'error', summary: 'Sign-in failed', detail: msg, life: 4000 })
  }
}

async function submit() {
  const body = draft.value.trim()
  if (!body || !auth.session) return
  submitting.value = true
  try {
    const c = await api.submitComment(props.slug, body, auth.session.session_id)
    draft.value = ''
    // New comments are pending moderation; show an optimistic note.
    if (c.status === 'approved') comments.value = [c, ...comments.value]
    toast.add({
      severity: 'success',
      summary: 'Comment submitted',
      detail: c.status === 'approved' ? 'Published.' : 'Awaiting author moderation.',
      life: 3500,
    })
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : 'Could not submit comment'
    toast.add({ severity: 'error', summary: 'Failed', detail: msg, life: 4000 })
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await loadComments()
  await setupSignIn()
})
</script>

<template>
  <section class="comments">
    <h2 class="ch"><i class="pi pi-comments" /> Comments</h2>

    <!-- Not deployed yet: graceful placeholder -->
    <EmptyState
      v-if="commentsEnabled === false"
      icon="pi-clock"
      title="Comments are coming soon"
      message="This PyrePress instance hasn't enabled the authenticated comments layer yet (Phase C). Certified reading works today; sign-in and discussion light up once the auth spike lands."
    />

    <template v-else>
      <!-- Compose / sign-in -->
      <div class="composer glass">
        <template v-if="auth.isSignedIn">
          <div class="who">
            <img v-if="auth.session?.picture" :src="auth.session.picture" class="avatar" alt="" />
            <span v-else class="avatar fallback"><i class="pi pi-user" /></span>
            <div>
              <strong>{{ auth.session?.name || auth.session?.identity || 'Signed in' }}</strong>
              <button class="signout" @click="auth.signOut()">Sign out</button>
            </div>
          </div>
          <Textarea
            v-model="draft"
            :maxlength="MAX"
            rows="3"
            placeholder="Share a thoughtful comment…"
            class="ta"
            auto-resize
          />
          <div class="composer-foot">
            <small :class="{ warn: draft.length > MAX - 100 }">{{ draft.length }}/{{ MAX }}</small>
            <Button
              label="Post comment"
              icon="pi pi-send"
              class="pp-flame"
              :loading="submitting"
              :disabled="!draft.trim()"
              @click="submit"
            />
          </div>
        </template>

        <template v-else>
          <div class="signin-prompt">
            <div class="prompt-text">
              <strong>Join the conversation</strong>
              <p>Sign in to leave a comment. Your identity is verified and comments are moderated by the author.</p>
            </div>
            <div class="signin-controls">
              <div v-show="googleReady" ref="googleBtn" class="gbtn" />
              <div v-if="!googleReady" class="fallback-signin">
                <Button
                  label="Sign in to comment"
                  icon="pi pi-sign-in"
                  outlined
                  disabled
                />
                <small>
                  Sign-in provider not configured on this instance yet
                  (Google OIDC / Internet Identity — Phase B/C).
                </small>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- List -->
      <div v-if="loading" class="clist">
        <div v-for="i in 2" :key="i" class="comment glass">
          <div class="skeleton line w40" />
          <div class="skeleton line" />
          <div class="skeleton line w70" />
        </div>
      </div>

      <EmptyState
        v-else-if="!comments.length"
        icon="pi-comment"
        title="No comments yet"
        message="Be the first to weigh in."
      />

      <TransitionGroup v-else name="fade" tag="div" class="clist">
        <article v-for="c in comments" :key="c.id" class="comment glass">
          <div class="c-head">
            <span class="c-author">
              <i class="pi pi-user" /> {{ c.author_name || c.author_identity }}
            </span>
            <span class="c-time">{{ relativeTime(c.ts) }}</span>
          </div>
          <p class="c-body">{{ c.body }}</p>
        </article>
      </TransitionGroup>
    </template>
  </section>
</template>

<style scoped>
.comments {
  margin-top: 3.5rem;
}
.ch {
  font-size: 1.4rem;
  margin: 0 0 1.25rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.composer {
  padding: 1.25rem;
  margin-bottom: 1.5rem;
}
.who {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}
.avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid var(--pp-border-strong);
}
.avatar.fallback {
  display: grid;
  place-items: center;
  background: var(--pp-surface-hover);
  color: var(--pp-text-dim);
}
.who div {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.signout {
  align-self: flex-start;
  background: none;
  border: none;
  color: var(--pp-text-faint);
  font-size: 0.78rem;
  cursor: pointer;
  padding: 0;
}
.signout:hover {
  color: var(--pp-ember);
}
.ta {
  width: 100%;
}
.composer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 0.75rem;
}
.composer-foot small {
  color: var(--pp-text-faint);
}
.composer-foot small.warn {
  color: var(--pp-ember);
}
.signin-prompt {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
  flex-wrap: wrap;
}
.prompt-text strong {
  font-size: 1.05rem;
}
.prompt-text p {
  margin: 0.3rem 0 0;
  color: var(--pp-text-dim);
  font-size: 0.9rem;
  max-width: 420px;
}
.signin-controls {
  min-width: 220px;
}
.fallback-signin {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  align-items: flex-start;
}
.fallback-signin small {
  color: var(--pp-text-faint);
  font-size: 0.78rem;
  max-width: 240px;
}
.clist {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.comment {
  padding: 1rem 1.15rem;
}
.c-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.4rem;
}
.c-author {
  font-weight: 700;
  font-size: 0.9rem;
  display: inline-flex;
  gap: 0.4rem;
  align-items: center;
}
.c-time {
  color: var(--pp-text-faint);
  font-size: 0.8rem;
}
.c-body {
  margin: 0;
  color: var(--pp-text-dim);
  white-space: pre-wrap;
  word-wrap: break-word;
}
.line {
  height: 12px;
  margin-bottom: 0.6rem;
}
.w40 {
  width: 40%;
}
.w70 {
  width: 70%;
}
</style>
