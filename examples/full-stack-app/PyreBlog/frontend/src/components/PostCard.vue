<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { PostCardData } from '@/api/types'
import { formatDate, formatCount } from '@/utils/format'

defineProps<{ post: PostCardData }>()
defineEmits<{ (e: 'tag', tag: string): void }>()
</script>

<template>
  <article class="card glass">
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
  padding: 1.5rem;
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease;
  position: relative;
  overflow: hidden;
}
.card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 3px;
  background: var(--pp-flame-gradient);
  opacity: 0;
  transition: opacity 0.2s ease;
}
.card:hover {
  transform: translateY(-4px);
  border-color: var(--pp-border-strong);
  box-shadow: var(--pp-shadow);
}
.card:hover::before {
  opacity: 1;
}
.card-link {
  color: inherit;
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
}
.read-more {
  margin-top: 0.75rem;
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
