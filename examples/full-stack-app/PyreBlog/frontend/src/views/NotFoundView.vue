<script setup lang="ts">
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import FlameLogo from '@/components/FlameLogo.vue'

const router = useRouter()
</script>

<template>
  <div class="pp-page nf">
    <FlameLogo :size="72" />
    <h1 class="gradient-text">404</h1>
    <p>This page went up in smoke. Nothing certified here.</p>
    <Button label="Back home" icon="pi pi-home" class="pp-flame" @click="router.push('/')" />
  </div>
</template>

<style scoped>
.nf {
  min-height: 70vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  text-align: center;
}
h1 {
  font-size: 5rem;
  margin: 0.5rem 0 0;
}
p {
  color: var(--pp-text-dim);
  margin: 0 0 1rem;
}
</style>
