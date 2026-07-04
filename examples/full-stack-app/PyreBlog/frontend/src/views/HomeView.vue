<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Button from 'primevue/button'
import { usePostsStore } from '@/stores/posts'
import { apiUrl } from '@/api/client'
import { SITE, PYRE_FEATURES } from '@/config/site'
import { RSS_SVG } from '@/utils/icons'
import FlameLogo from '@/components/FlameLogo.vue'
import PostCard from '@/components/PostCard.vue'
import PostCardSkeleton from '@/components/PostCardSkeleton.vue'
import TagFilter from '@/components/TagFilter.vue'
import EmptyState from '@/components/EmptyState.vue'

const posts = usePostsStore()
const route = useRoute()
const router = useRouter()
const feedUrl = apiUrl('/feed.xml')

// Client-side search over the loaded posts (title / excerpt / tags). Works
// alongside the server-side tag filter; empty query shows everything.
const search = ref('')
const searching = computed(() => search.value.trim().length > 0)
const visibleItems = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return posts.items
  return posts.items.filter((p) => {
    const hay = `${p.title} ${p.excerpt ?? ''} ${(p.tags ?? []).join(' ')}`.toLowerCase()
    return hay.includes(q)
  })
})

const copied = ref(false)
let copyTimer: ReturnType<typeof setTimeout> | undefined

async function copyInstall() {
  try {
    await navigator.clipboard.writeText(SITE.pyre.install)
    copied.value = true
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => (copied.value = false), 1600)
  } catch {
    /* clipboard unavailable — no-op */
  }
}

function selectTag(tag: string | null) {
  router.replace({ name: 'home', query: tag ? { tag } : {} })
  posts.load(tag)
}

function currentTag(): string | null {
  const t = route.query.tag
  return typeof t === 'string' && t ? t : null
}

onMounted(() => {
  const tag = currentTag()
  if (!posts.items.length || posts.activeTag !== tag) posts.load(tag)
})

watch(
  () => route.query.tag,
  (t) => {
    const tag = typeof t === 'string' && t ? t : null
    if (posts.activeTag !== tag) posts.load(tag)
  },
)
</script>

<template>
  <div class="pp-page">
    <!-- Hero -->
    <section class="hero pp-container">
      <div class="hero-glow" />
      <div class="embers" aria-hidden="true">
        <span v-for="i in 8" :key="i" class="ember" />
      </div>
      <div class="hero-in d0"><FlameLogo :size="76" /></div>
      <h1 class="hero-title hero-in d1">
        Certified writing,<br />
        <span class="gradient-text">unforgeable by design.</span>
      </h1>
      <p class="hero-sub hero-in d2">
        PyrePress is a certified, tamper-proof blog that runs entirely inside an Internet Computer
        canister — every post is cryptographically verifiable, with no servers or middlemen. And it
        is itself built with <strong>PYRE</strong>, a Python framework for the Internet Computer.
      </p>
      <div class="hero-badges hero-in d3">
        <span class="hb"><i class="pi pi-verified" /> Cryptographically certified</span>
        <span class="hb"><i class="pi pi-server" /> On-chain, no backend</span>
        <span class="hb"><i class="pi pi-bolt" /> Powered by PYRE</span>
      </div>
      <div class="hero-cta hero-in d4">
        <a :href="SITE.pyre.github" target="_blank" rel="noopener">
          <Button label="Get PYRE" icon="pi pi-github" class="pp-flame" />
        </a>
        <a :href="SITE.pyre.docs" target="_blank" rel="noopener">
          <Button label="Read the docs" icon="pi pi-book" outlined />
        </a>
      </div>
    </section>

    <!-- Built with PYRE -->
    <section class="pp-container band">
      <div class="band-head">
        <span class="band-eyebrow"><i class="pi pi-bolt" /> Built with PYRE</span>
        <h2 class="band-title">This whole site is a <span class="gradient-text">PYRE app</span></h2>
        <p class="band-pitch">{{ SITE.pyre.pitch }}</p>
      </div>

      <div class="install">
        <code class="install-cmd">{{ SITE.pyre.install }}</code>
        <button
          type="button"
          class="install-copy"
          :aria-label="copied ? 'Copied' : 'Copy install command'"
          @click="copyInstall"
        >
          <i :class="copied ? 'pi pi-check' : 'pi pi-copy'" />
          <span>{{ copied ? 'Copied' : 'Copy' }}</span>
        </button>
      </div>

      <div class="band-grid">
        <div v-for="f in PYRE_FEATURES" :key="f.title" class="feature glass">
          <div class="feature-icon"><i :class="`pi ${f.icon}`" /></div>
          <h3 class="feature-title">{{ f.title }}</h3>
          <p class="feature-body">{{ f.body }}</p>
        </div>
      </div>

      <div class="band-links">
        <a :href="SITE.pyre.github" target="_blank" rel="noopener">
          <i class="pi pi-github" /> View on GitHub
        </a>
        <a :href="SITE.pyre.pypi" target="_blank" rel="noopener">
          <i class="pi pi-box" /> PyPI
        </a>
        <a :href="SITE.company.url" target="_blank" rel="noopener">
          by {{ SITE.company.name }}
        </a>
      </div>
    </section>

    <!-- Feed -->
    <section class="pp-container feed">
      <div class="feed-head">
        <h2>Latest news</h2>
        <div class="feed-tools">
          <div class="search">
            <i class="pi pi-search" />
            <input
              v-model="search"
              type="search"
              class="search-input"
              placeholder="Search posts…"
              aria-label="Search posts"
            />
            <button v-if="searching" class="search-clear" aria-label="Clear search" @click="search = ''">
              <i class="pi pi-times" />
            </button>
          </div>
          <a class="rss" :href="feedUrl" target="_blank" rel="noopener">
            <span class="rss-ico" v-html="RSS_SVG" /> Subscribe
          </a>
        </div>
      </div>

      <TagFilter :tags="posts.allTags" :active="posts.activeTag" @select="selectTag" />

      <!-- Loading -->
      <div v-if="posts.loading" class="grid">
        <PostCardSkeleton v-for="i in 4" :key="i" />
      </div>

      <!-- Error -->
      <EmptyState
        v-else-if="posts.error"
        icon="pi-exclamation-triangle"
        title="Couldn't reach the canister"
        :message="posts.error"
      >
        <Button label="Retry" icon="pi pi-refresh" class="pp-flame" @click="posts.load(posts.activeTag)" />
      </EmptyState>

      <!-- Empty -->
      <EmptyState
        v-else-if="!posts.items.length"
        icon="pi-pencil"
        title="No posts yet"
        message="This flame is freshly lit. Once the author publishes, certified posts appear here."
      />

      <!-- No search matches -->
      <EmptyState
        v-else-if="searching && !visibleItems.length"
        icon="pi-search"
        title="No matching posts"
        :message="`Nothing matches “${search}”. Try a different term or clear the search.`"
      >
        <Button label="Clear search" icon="pi pi-times" outlined @click="search = ''" />
      </EmptyState>

      <!-- Posts -->
      <template v-else>
        <div class="grid">
          <PostCard
            v-for="(p, i) in visibleItems"
            :key="p.slug"
            :post="p"
            :style="{ '--i': i % 10 }"
            class="card-in"
            @tag="selectTag"
          />
        </div>
        <div v-if="posts.next && !searching" class="more">
          <Button
            label="Load more"
            icon="pi pi-chevron-down"
            outlined
            :loading="posts.loadingMore"
            @click="posts.loadMore()"
          />
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.hero {
  position: relative;
  text-align: center;
  padding: 3rem 1.25rem 3.5rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
}
.hero-glow {
  position: absolute;
  top: -40px;
  left: 50%;
  transform: translateX(-50%);
  width: 520px;
  height: 320px;
  max-width: 90vw;
  background: radial-gradient(circle, rgba(255, 138, 60, 0.22), transparent 65%);
  filter: blur(20px);
  z-index: -1;
  pointer-events: none;
}
.hero-title {
  font-size: clamp(2.1rem, 5vw, 3.4rem);
  margin: 0.5rem 0 0;
  font-weight: 800;
}
.hero-sub {
  max-width: 640px;
  color: var(--pp-text-dim);
  font-size: 1.08rem;
  margin: 0.25rem 0 0.5rem;
}
.hero-badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.6rem;
}

/* Staggered hero entrance */
.hero-in {
  animation: hero-rise 0.65s cubic-bezier(0.2, 0.7, 0.3, 1) backwards;
}
.d0 {
  animation-delay: 0ms;
}
.d1 {
  animation-delay: 90ms;
}
.d2 {
  animation-delay: 180ms;
}
.d3 {
  animation-delay: 270ms;
}
.d4 {
  animation-delay: 360ms;
}
@keyframes hero-rise {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Drifting embers rising out of the hero glow */
.embers {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: -1;
}
.ember {
  position: absolute;
  bottom: -8px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: radial-gradient(circle, #ffb347 0%, rgba(255, 90, 77, 0.7) 60%, transparent 100%);
  filter: blur(0.5px);
  opacity: 0;
  animation: ember-rise 7s linear infinite;
}
.ember:nth-child(1) {
  left: 18%;
  animation-delay: 0s;
  animation-duration: 6.5s;
}
.ember:nth-child(2) {
  left: 31%;
  animation-delay: 1.8s;
  animation-duration: 8s;
  width: 4px;
  height: 4px;
}
.ember:nth-child(3) {
  left: 44%;
  animation-delay: 0.9s;
  animation-duration: 5.8s;
}
.ember:nth-child(4) {
  left: 52%;
  animation-delay: 3.1s;
  animation-duration: 7.2s;
  width: 6px;
  height: 6px;
}
.ember:nth-child(5) {
  left: 60%;
  animation-delay: 2.2s;
  animation-duration: 6.2s;
  width: 3px;
  height: 3px;
}
.ember:nth-child(6) {
  left: 70%;
  animation-delay: 4.4s;
  animation-duration: 8.4s;
}
.ember:nth-child(7) {
  left: 79%;
  animation-delay: 1.2s;
  animation-duration: 6.8s;
  width: 4px;
  height: 4px;
}
.ember:nth-child(8) {
  left: 88%;
  animation-delay: 3.7s;
  animation-duration: 7.6s;
  width: 3px;
  height: 3px;
}
@keyframes ember-rise {
  0% {
    opacity: 0;
    transform: translateY(0) translateX(0) scale(1);
  }
  8% {
    opacity: 0.9;
  }
  55% {
    opacity: 0.55;
  }
  100% {
    opacity: 0;
    transform: translateY(-340px) translateX(22px) scale(0.4);
  }
}
@media (prefers-reduced-motion: reduce) {
  .hero-in,
  .ember,
  .card-in {
    animation: none !important;
  }
  .ember {
    display: none;
  }
}
.hb {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.85rem;
  border-radius: 999px;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--pp-text-dim);
  border: 1px solid var(--pp-border-strong);
  background: var(--pp-surface);
}
.hb i {
  color: var(--pp-amber);
}

/* Hero CTAs */
.hero-cta {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.75rem;
  margin-top: 0.5rem;
}
.hero-cta a {
  display: inline-flex;
}

/* Built with PYRE band */
.band {
  margin-top: 3rem;
  padding-top: 2.5rem;
  padding-bottom: 0.5rem;
  border-top: 1px solid var(--pp-border);
}
.band-head {
  text-align: center;
  max-width: 680px;
  margin: 0 auto 1.5rem;
}
.band-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-family: var(--pp-font-mono);
  font-size: 0.75rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 600;
  color: var(--pp-text-dim);
}
.band-eyebrow i {
  color: var(--pp-amber);
}
.band-title {
  font-size: clamp(1.6rem, 3.5vw, 2.3rem);
  margin: 0.5rem 0 0.6rem;
  font-weight: 800;
}
.band-pitch {
  color: var(--pp-text-dim);
  font-size: 1.02rem;
  margin: 0;
}

/* Install pill */
.install {
  display: flex;
  align-items: stretch;
  justify-content: center;
  gap: 0;
  max-width: 420px;
  margin: 0 auto 2rem;
  border: 1px solid var(--pp-border-strong);
  border-radius: 999px;
  background: var(--pp-surface);
  overflow: hidden;
}
.install-cmd {
  flex: 1;
  display: flex;
  align-items: center;
  padding: 0.7rem 1.1rem;
  font-family: var(--pp-font-mono);
  font-size: 0.92rem;
  color: var(--pp-text);
  white-space: nowrap;
  overflow-x: auto;
}
.install-copy {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0 1.1rem;
  border: none;
  border-left: 1px solid var(--pp-border-strong);
  background: transparent;
  color: var(--pp-text-dim);
  font-weight: 600;
  font-size: 0.85rem;
  cursor: pointer;
  transition:
    color 0.15s ease,
    background 0.15s ease;
}
.install-copy:hover {
  color: var(--pp-amber);
  background: var(--pp-surface-hover);
}

/* Feature cards */
.band-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.25rem;
}
.feature {
  padding: 1.5rem;
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}
.feature:hover {
  transform: translateY(-4px);
  border-color: var(--pp-border-strong);
  box-shadow: var(--pp-shadow);
}
.feature-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: var(--pp-radius-sm);
  background: rgba(255, 138, 60, 0.12);
  border: 1px solid var(--pp-border);
  margin-bottom: 0.9rem;
}
.feature-icon i {
  font-size: 1.15rem;
  color: var(--pp-amber);
}
.feature-title {
  font-size: 1.12rem;
  margin: 0 0 0.45rem;
  color: var(--pp-text);
}
.feature-body {
  margin: 0;
  color: var(--pp-text-dim);
  font-size: 0.94rem;
  line-height: 1.6;
}

/* Band footer links */
.band-links {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 1.5rem;
  margin-top: 1.75rem;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--pp-text-dim);
}
.band-links a {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--pp-text-dim);
}
.band-links a:hover {
  color: var(--pp-amber);
}

.feed {
  margin-top: 3rem;
}
.feed-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.75rem 1.25rem;
  margin-bottom: 1.25rem;
}
.feed-head h2 {
  font-size: 1.5rem;
  margin: 0;
}
.feed-tools {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}
.search {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.45rem 0.7rem;
  border-radius: 999px;
  border: 1px solid var(--pp-border);
  background: var(--pp-surface);
  transition: border-color 0.15s ease;
  min-width: 220px;
}
.search:focus-within {
  border-color: var(--pp-orange);
}
.search > .pi-search {
  color: var(--pp-text-faint);
  font-size: 0.9rem;
}
.search-input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  outline: none;
  color: var(--pp-text);
  font: inherit;
  font-size: 0.9rem;
}
.search-input::placeholder {
  color: var(--pp-text-faint);
}
.search-input::-webkit-search-cancel-button {
  display: none;
}
.search-clear {
  display: inline-grid;
  place-items: center;
  background: none;
  border: none;
  color: var(--pp-text-faint);
  cursor: pointer;
  padding: 0;
  font-size: 0.85rem;
}
.search-clear:hover {
  color: var(--pp-amber);
}
.rss {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: 600;
  font-size: 0.9rem;
  color: var(--pp-text-dim);
}
.rss:hover {
  color: var(--pp-amber);
}
.rss-ico {
  display: inline-flex;
  align-items: center;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 1.25rem;
}

/* Staggered card entrance */
.card-in {
  animation: card-rise 0.55s cubic-bezier(0.2, 0.7, 0.3, 1) backwards;
  animation-delay: calc(var(--i, 0) * 70ms);
}
@keyframes card-rise {
  from {
    opacity: 0;
    transform: translateY(18px) scale(0.985);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
.more {
  display: flex;
  justify-content: center;
  margin-top: 2rem;
}
@media (max-width: 860px) {
  .band-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 640px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
