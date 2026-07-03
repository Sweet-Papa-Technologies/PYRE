<script setup lang="ts">
withDefaults(
  defineProps<{ icon?: string; title: string; message?: string }>(),
  { icon: 'pi-inbox', message: '' },
)
</script>

<template>
  <div class="empty glass">
    <div class="halo">
      <i :class="['pi', icon]" />
    </div>
    <h3>{{ title }}</h3>
    <p v-if="message">{{ message }}</p>
    <slot />
  </div>
</template>

<style scoped>
.empty {
  text-align: center;
  padding: 3rem 2rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
}
.halo {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  margin-bottom: 0.5rem;
  background: radial-gradient(circle, rgba(255, 138, 60, 0.18), transparent 70%);
  border: 1px solid var(--pp-border-strong);
}
.halo i {
  font-size: 1.8rem;
  background: var(--pp-flame-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
h3 {
  margin: 0;
  font-size: 1.2rem;
}
p {
  margin: 0;
  color: var(--pp-text-dim);
  max-width: 420px;
}
</style>
