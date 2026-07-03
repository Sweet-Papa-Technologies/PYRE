<script setup lang="ts">
withDefaults(defineProps<{ size?: number; animated?: boolean }>(), {
  size: 32,
  animated: true,
})
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 64 64"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    class="flame-logo"
    :class="{ animated }"
    aria-hidden="true"
  >
    <defs>
      <linearGradient id="pp-flame" x1="32" y1="4" x2="32" y2="60" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#5ad1ff" />
        <stop offset="0.5" stop-color="#ffb347" />
        <stop offset="1" stop-color="#ff5a4d" />
      </linearGradient>
    </defs>
    <!-- stylized low-poly flame silhouette -->
    <path
      d="M33 4c3 8-2 12-6 16-3 3-6 7-6 12 0-3-2-6-4-7 1 6-4 9-4 16 0 11 9 19 20 19s20-8 20-19c0-8-5-12-8-17-2 4-5 5-8 5 4-5 5-11 3-16-1-4-4-6-7-9Z"
      stroke="url(#pp-flame)"
      stroke-width="2.2"
      stroke-linejoin="round"
      fill="url(#pp-flame)"
      fill-opacity="0.12"
    />
    <!-- inner spark -->
    <path
      d="M32 30c2 3 5 5 5 9 0 4-3 7-5 7s-5-3-5-7c0-3 3-6 5-9Z"
      fill="url(#pp-flame)"
      fill-opacity="0.9"
    />
  </svg>
</template>

<style scoped>
.flame-logo {
  display: block;
  filter: drop-shadow(0 0 8px rgba(255, 138, 60, 0.45));
}
.flame-logo.animated {
  animation: flicker 3.2s ease-in-out infinite;
  transform-origin: 50% 70%;
}
@keyframes flicker {
  0%,
  100% {
    transform: scale(1) rotate(0deg);
    filter: drop-shadow(0 0 8px rgba(255, 138, 60, 0.45));
  }
  50% {
    transform: scale(1.04) rotate(-1deg);
    filter: drop-shadow(0 0 14px rgba(255, 138, 60, 0.6));
  }
}
@media (prefers-reduced-motion: reduce) {
  .flame-logo.animated {
    animation: none;
  }
}
</style>
