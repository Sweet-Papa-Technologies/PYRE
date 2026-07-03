import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import { ApiError, type PostCardData } from '@/api/types'

export const usePostsStore = defineStore('posts', () => {
  const items = ref<PostCardData[]>([])
  const next = ref<string | null>(null)
  const loading = ref(false)
  const loadingMore = ref(false)
  const error = ref<string | null>(null)
  const activeTag = ref<string | null>(null)

  const allTags = computed(() => {
    const set = new Set<string>()
    for (const p of items.value) for (const t of p.tags ?? []) set.add(t)
    return [...set].sort((a, b) => a.localeCompare(b))
  })

  async function load(tag: string | null = null) {
    loading.value = true
    error.value = null
    activeTag.value = tag
    try {
      const res = await api.listPosts({ tag: tag ?? undefined })
      items.value = res.items ?? []
      next.value = res.next ?? null
    } catch (e) {
      items.value = []
      next.value = null
      error.value =
        e instanceof ApiError
          ? e.status === 0
            ? e.message
            : `Could not load posts (${e.status}).`
          : 'Could not load posts.'
    } finally {
      loading.value = false
    }
  }

  async function loadMore() {
    if (!next.value || loadingMore.value) return
    loadingMore.value = true
    try {
      const res = await api.listPosts({ tag: activeTag.value ?? undefined, after: next.value })
      items.value = [...items.value, ...(res.items ?? [])]
      next.value = res.next ?? null
    } catch {
      /* keep existing list; surface nothing loud */
    } finally {
      loadingMore.value = false
    }
  }

  return { items, next, loading, loadingMore, error, activeTag, allTags, load, loadMore }
})
