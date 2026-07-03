<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useToast } from 'primevue/usetoast'
import Button from 'primevue/button'
import { api } from '@/api/client'
import { ApiError, type Comment } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'
import EmptyState from '@/components/EmptyState.vue'

const auth = useAuthStore()
const toast = useToast()

const pending = ref<Comment[]>([])
const loading = ref(true)
const unavailable = ref(false)
const busyId = ref<string | null>(null)

async function load() {
  loading.value = true
  unavailable.value = false
  try {
    const res = await api.listPendingComments(auth.authorToken)
    pending.value = res.items ?? []
  } catch (e) {
    if (e instanceof ApiError && e.notFound) unavailable.value = true
    else if (e instanceof ApiError && e.unauthorized) {
      toast.add({ severity: 'error', summary: 'Not authorized', detail: 'Author token rejected.', life: 4000 })
    } else {
      toast.add({ severity: 'error', summary: 'Failed to load', life: 4000 })
    }
    pending.value = []
  } finally {
    loading.value = false
  }
}

async function act(c: Comment, approve: boolean) {
  busyId.value = c.id
  try {
    if (approve) await api.approveComment(c.id, auth.authorToken)
    else await api.rejectComment(c.id, auth.authorToken)
    pending.value = pending.value.filter((x) => x.id !== c.id)
    toast.add({
      severity: approve ? 'success' : 'info',
      summary: approve ? 'Approved' : 'Rejected',
      life: 2200,
    })
  } catch (e) {
    toast.add({
      severity: 'error',
      summary: 'Action failed',
      detail: e instanceof ApiError ? e.message : '',
      life: 4000,
    })
  } finally {
    busyId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="pp-page">
    <div class="pp-container narrow">
      <div class="mod-head">
        <h1><i class="pi pi-shield" /> Moderation</h1>
        <Button label="Refresh" icon="pi pi-refresh" text @click="load" />
      </div>
      <p class="sub">Approve or reject pending reader comments. Only approved comments render, certified.</p>

      <div v-if="loading" class="list">
        <div v-for="i in 2" :key="i" class="row glass">
          <div class="skeleton line w40" />
          <div class="skeleton line" />
        </div>
      </div>

      <EmptyState
        v-else-if="unavailable"
        icon="pi-clock"
        title="Comments layer not enabled"
        message="This instance hasn't deployed the Phase C comments/moderation endpoints yet. Nothing to moderate until authenticated comments land."
      />

      <EmptyState
        v-else-if="!pending.length"
        icon="pi-check-circle"
        title="Inbox zero"
        message="No comments awaiting moderation. Nicely done."
      />

      <TransitionGroup v-else name="fade" tag="div" class="list">
        <article v-for="c in pending" :key="c.id" class="row glass">
          <div class="row-head">
            <span class="author"><i class="pi pi-user" /> {{ c.author_name || c.author_identity }}</span>
            <span class="time">{{ formatDateTime(c.ts) }}</span>
          </div>
          <p class="body">{{ c.body }}</p>
          <div class="row-actions">
            <Button
              label="Reject"
              icon="pi pi-times"
              severity="danger"
              outlined
              size="small"
              :loading="busyId === c.id"
              @click="act(c, false)"
            />
            <Button
              label="Approve"
              icon="pi pi-check"
              class="pp-flame"
              size="small"
              :loading="busyId === c.id"
              @click="act(c, true)"
            />
          </div>
        </article>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.narrow {
  max-width: 760px;
}
.mod-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mod-head h1 {
  font-size: 1.8rem;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 0.6rem;
}
.sub {
  color: var(--pp-text-dim);
  margin: 0.25rem 0 1.75rem;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.row {
  padding: 1.15rem 1.25rem;
}
.row-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}
.author {
  font-weight: 700;
  display: inline-flex;
  gap: 0.4rem;
  align-items: center;
}
.time {
  color: var(--pp-text-faint);
  font-size: 0.8rem;
}
.body {
  margin: 0 0 1rem;
  color: var(--pp-text-dim);
  white-space: pre-wrap;
}
.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.6rem;
}
.line {
  height: 12px;
  margin-bottom: 0.6rem;
}
.w40 {
  width: 40%;
}
</style>
