<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Button from 'primevue/button'
import { usePostsStore } from '@/stores/posts'
import { apiUrl } from '@/api/client'
import FlameLogo from '@/components/FlameLogo.vue'
import PostCard from '@/components/PostCard.vue'
import PostCardSkeleton from '@/components/PostCardSkeleton.vue'
import TagFilter from '@/components/TagFilter.vue'
import EmptyState from '@/components/EmptyState.vue'

const posts = usePostsStore()
const route = useRoute()
const router = useRouter()
const feedUrl = apiUrl('/feed.xml')

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
        PyrePress is a blog that lives inside an Internet Computer smart contract. Every post is
        cryptographically certified — readers can prove nothing was tampered with. No servers, no
        middlemen, no trust required.
      </p>
      <div class="hero-badges hero-in d3">
        <span class="hb"><i class="pi pi-verified" /> Cryptographically certified</span>
        <span class="hb"><i class="pi pi-server" /> On-chain, no backend</span>
        <span class="hb"><i class="pi pi-bolt" /> Powered by PYRE</span>
      </div>
    </section>

    <!-- Feed -->
    <section class="pp-container feed">
      <div class="feed-head">
        <h2>Latest posts</h2>
        <a class="rss" :href="feedUrl" target="_blank" rel="noopener">
          <i class="pi pi-rss" /> Subscribe
        </a>
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

      <!-- Posts -->
      <template v-else>
        <div class="grid">
          <PostCard
            v-for="(p, i) in posts.items"
            :key="p.slug"
            :post="p"
            :style="{ '--i': i % 10 }"
            class="card-in"
            @tag="selectTag"
          />
        </div>
        <div v-if="posts.next" class="more">
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

.feed {
  margin-top: 1.5rem;
}
.feed-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.25rem;
}
.feed-head h2 {
  font-size: 1.5rem;
  margin: 0;
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
@media (max-width: 640px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
