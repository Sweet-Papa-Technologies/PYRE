<script setup lang="ts">
defineProps<{ tags: string[]; active: string | null }>()
defineEmits<{ (e: 'select', tag: string | null): void }>()
</script>

<template>
  <div v-if="tags.length" class="tag-filter">
    <button class="pp-chip" :class="{ active: active === null }" @click="$emit('select', null)">
      <i class="pi pi-th-large" /> All
    </button>
    <button
      v-for="t in tags"
      :key="t"
      class="pp-chip"
      :class="{ active: active === t }"
      @click="$emit('select', t)"
    >
      #{{ t }}
    </button>
  </div>
</template>

<style scoped>
.tag-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1.75rem;
}
</style>
