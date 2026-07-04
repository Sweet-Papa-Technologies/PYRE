<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { PostCardData } from '@/api/types'
import { formatDate, formatCount } from '@/utils/format'
import coverCertified from '@/assets/covers/cover-certified.webp'
import coverFlame from '@/assets/covers/cover-flame.webp'
import coverNetwork from '@/assets/covers/cover-network.webp'
import coverCode from '@/assets/covers/cover-code.webp'

const props = defineProps<{ post: PostCardData }>()
defineEmits<{ (e: 'tag', tag: string): void }>()

const PLACEHOLDERS = [coverFlame, coverCertified, coverNetwork, coverCode]

// Pick a themed placeholder by tag when possible, else a stable per-slug
// choice so a given post always shows the same cover.
const cover = computed(() => {
  if (props.post.coverImage) return props.post.coverImage
  const tags = (props.post.tags ?? []).map((t) => t.toLowerCase())
  if (tags.some((t) => /cert|secur|verif/.test(t))) return coverCertified
  if (tags.some((t) => /pyre|announce|release/.test(t))) return coverFlame
  if (tags.some((t) => /icp|internet-computer|network|consensus/.test(t))) return coverNetwork
  if (tags.some((t) => /python|kybra|code|api/.test(t))) return coverCode
  let h = 0
  for (const c of props.post.slug) h = (h + c.charCodeAt(0)) % PLACEHOLDERS.length
  return PLACEHOLDERS[h]
})
</script>

<template>
  <article class="card glass">
    <RouterLink :to="{ name: 'post', params: { slug: post.slug } }" class="card-cover" tabindex="-1" aria-hidden="true">
      <img :src="cover" alt="" loading="lazy" />
    </RouterLink>
    <RouterLink :to="{ name: 'post', params: { slug: post.slug } }" class="card-link">
      <div class="card-body">
        <div class="meta">
          <span><i class="pi pi-calendar" /> {{ formatDate(post.published_at) }}</span>
          <span><i class="pi pi-eye" /> {{ formatCount(post.views) }}</span>
        </div>
        <h2 class="title">{{ post.title }}</h2>
        <p class="excerpt">{{ post.excerpt }}</p>
      </div>
    </RouterLink>
    <div v-if="post.tags?.length" class="tags">
      <button
        v-for="t in post.tags"
        :key="t"
        class="pp-chip"
        @click.stop="$emit('tag', t)"
      >
        #{{ t }}
      </button>
    </div>
    <div class="read-more">
      <RouterLink :to="{ name: 'post', params: { slug: post.slug } }">
        Read <i class="pi pi-arrow-right" />
      </RouterLink>
    </div>
  </article>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  padding: 0;
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease;
  position: relative;
  overflow: hidden;
}
.card:hover {
  transform: translateY(-4px);
  border-color: var(--pp-border-strong);
  box-shadow: var(--pp-shadow);
}
.card-cover {
  display: block;
  position: relative;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  background: var(--pp-bg-2);
  border-bottom: 1px solid var(--pp-border);
}
.card-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.35s ease;
}
.card-cover::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, transparent 55%, color-mix(in srgb, var(--pp-surface-solid) 55%, transparent));
  pointer-events: none;
}
.card:hover .card-cover img {
  transform: scale(1.04);
}
.card-link {
  color: inherit;
}
.card-body {
  padding: 1.25rem 1.5rem 0;
}
.meta {
  display: flex;
  gap: 1rem;
  font-size: 0.8rem;
  color: var(--pp-text-faint);
  margin-bottom: 0.65rem;
}
.meta i {
  margin-right: 0.25rem;
}
.title {
  font-size: 1.35rem;
  margin: 0 0 0.55rem;
  color: var(--pp-text);
  transition: color 0.15s ease;
}
.card:hover .title {
  color: var(--pp-amber);
}
.excerpt {
  margin: 0;
  color: var(--pp-text-dim);
  font-size: 0.96rem;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin: 1rem 0 0.4rem;
  padding: 0 1.5rem;
}
.read-more {
  margin-top: 0.75rem;
  padding: 0 1.5rem 1.5rem;
  font-weight: 700;
  font-size: 0.9rem;
}
.read-more i {
  transition: transform 0.15s ease;
}
.card:hover .read-more i {
  transform: translateX(4px);
}
</style>
