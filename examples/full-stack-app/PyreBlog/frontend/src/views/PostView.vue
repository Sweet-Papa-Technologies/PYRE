<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Button from 'primevue/button'
import { api } from '@/api/client'
import { ApiError, type PostDetail } from '@/api/types'
import { formatDate, formatCount, readingMinutes } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'
import { useMetaStore } from '@/stores/meta'
import VerifyPanel from '@/components/VerifyPanel.vue'
import CommentsSection from '@/components/CommentsSection.vue'
import EmptyState from '@/components/EmptyState.vue'

const props = defineProps<{ slug: string }>()
const auth = useAuthStore()
const meta = useMetaStore()
const router = useRouter()

const post = ref<PostDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const notFound = ref(false)
const views = ref(0)

async function load() {
  loading.value = true
  error.value = null
  notFound.value = false
  post.value = null
  try {
    const p = await api.getPost(props.slug)
    post.value = p
    views.value = p.views ?? 0
    meta.setCanisterId(p.canister_id)
    document.title = `${p.title} · ${meta.title}`
    // Fire-and-forget view increment (update call; ignore failures).
    api
      .recordView(props.slug)
      .then((r) => {
        if (r && typeof r.views === 'number') views.value = r.views
      })
      .catch(() => {})
  } catch (e) {
    if (e instanceof ApiError && e.notFound) notFound.value = true
    else error.value = e instanceof ApiError ? e.message : 'Failed to load post.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(
  () => props.slug,
  () => load(),
)
</script>

<template>
  <div class="pp-page">
    <div class="pp-container narrow">
      <RouterLink to="/" class="back"><i class="pi pi-arrow-left" /> All posts</RouterLink>

      <!-- Loading -->
      <div v-if="loading" class="load">
        <div class="skeleton line w30" />
        <div class="skeleton line title" />
        <div class="skeleton line title2" />
        <div class="skeleton block" />
        <div class="skeleton line" />
        <div class="skeleton line" />
        <div class="skeleton line w70" />
      </div>

      <!-- Not found -->
      <EmptyState
        v-else-if="notFound"
        icon="pi-question-circle"
        title="Post not found"
        message="This post doesn't exist, or it hasn't been published yet."
      >
        <Button label="Back home" icon="pi pi-home" class="pp-flame" @click="router.push('/')" />
      </EmptyState>

      <!-- Error -->
      <EmptyState
        v-else-if="error"
        icon="pi-exclamation-triangle"
        title="Couldn't load this post"
        :message="error"
      >
        <Button label="Retry" icon="pi pi-refresh" class="pp-flame" @click="load" />
      </EmptyState>

      <!-- Post -->
      <article v-else-if="post">
        <header class="post-head">
          <div class="tags">
            <RouterLink
              v-for="t in post.tags"
              :key="t"
              :to="{ name: 'home', query: { tag: t } }"
              class="pp-chip"
            >
              #{{ t }}
            </RouterLink>
          </div>
          <h1 class="post-title">{{ post.title }}</h1>
          <div class="post-meta">
            <span><i class="pi pi-calendar" /> {{ formatDate(post.published_at_iso || post.published_at) }}</span>
            <span><i class="pi pi-clock" /> {{ readingMinutes(post.html) }} min read</span>
            <span><i class="pi pi-eye" /> {{ formatCount(views) }} views</span>
            <span v-if="post.status && post.status !== 'published'" class="status-draft">
              <i class="pi pi-file-edit" /> {{ post.status }}
            </span>
            <RouterLink
              v-if="auth.isAuthor"
              :to="{ name: 'edit', params: { slug: post.slug } }"
              class="edit-link"
            >
              <i class="pi pi-pencil" /> Edit
            </RouterLink>
          </div>
        </header>

        <VerifyPanel
          :page-url="post.pageUrl"
          :canister-id="post.canister_id"
          :certified="post.certified"
          :cert-header="post.certHeader"
          :updated-at="post.updated_at_iso || post.updated_at"
        />

        <!-- Server-rendered, certified, sanitized HTML from the canister. -->
        <!-- eslint-disable-next-line vue/no-v-html -->
        <div class="prose post-body" v-html="post.html" />

        <CommentsSection :slug="post.slug" />
      </article>
    </div>
  </div>
</template>

<style scoped>
.narrow {
  max-width: var(--pp-read);
}
.back {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--pp-text-dim);
  font-weight: 600;
  font-size: 0.9rem;
  margin-bottom: 1.5rem;
}
.back:hover {
  color: var(--pp-amber);
}
.post-head {
  margin-bottom: 1.5rem;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: 1rem;
}
.post-title {
  font-size: clamp(2rem, 5vw, 2.8rem);
  margin: 0 0 1rem;
}
.post-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 1.2rem;
  color: var(--pp-text-faint);
  font-size: 0.9rem;
  align-items: center;
}
.post-meta i {
  margin-right: 0.3rem;
}
.status-draft {
  color: var(--pp-amber);
  text-transform: capitalize;
}
.edit-link {
  color: var(--pp-cyan-soft);
  font-weight: 600;
}
.post-body {
  margin-top: 2rem;
}
/* skeleton */
.load {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
}
.line {
  height: 14px;
}
.w30 {
  width: 30%;
}
.w70 {
  width: 70%;
}
.line.title {
  height: 32px;
  width: 85%;
}
.line.title2 {
  height: 32px;
  width: 55%;
  margin-bottom: 1rem;
}
.block {
  height: 90px;
  margin: 0.5rem 0 1rem;
}
</style>
