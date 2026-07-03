<script setup lang="ts">
import { RouterView, RouterLink, useRouter } from 'vue-router'
import { computed, ref } from 'vue'
import Toast from 'primevue/toast'
import ConfirmDialog from 'primevue/confirmdialog'
import FlameLogo from '@/components/FlameLogo.vue'
import { useAuthStore } from '@/stores/auth'
import { useMetaStore } from '@/stores/meta'
import { useTheme } from '@/composables/useTheme'
import { apiUrl } from '@/api/client'

const auth = useAuthStore()
const meta = useMetaStore()
const router = useRouter()
const { theme, toggle } = useTheme()
const menuOpen = ref(false)
const feedUrl = apiUrl('/feed.xml')

meta.load()

const authorName = computed(() => (auth.isAuthor ? 'Author' : ''))

function go(name: string) {
  menuOpen.value = false
  router.push({ name })
}
</script>

<template>
  <div class="app-shell">
    <header class="nav-wrap">
      <nav class="nav pp-container">
        <RouterLink to="/" class="brand" @click="menuOpen = false">
          <FlameLogo :size="34" />
          <span class="brand-name">Pyre<span class="gradient-text">Press</span></span>
        </RouterLink>

        <button class="hamburger" @click="menuOpen = !menuOpen" aria-label="Menu">
          <i :class="menuOpen ? 'pi pi-times' : 'pi pi-bars'" />
        </button>

        <div class="nav-links" :class="{ open: menuOpen }">
          <RouterLink to="/" class="nav-link" @click="menuOpen = false">
            <i class="pi pi-home" /> Home
          </RouterLink>
          <RouterLink v-if="auth.isAuthor" to="/compose" class="nav-link" @click="menuOpen = false">
            <i class="pi pi-pencil" /> Compose
          </RouterLink>
          <RouterLink
            v-if="auth.isAuthor"
            to="/moderate"
            class="nav-link"
            @click="menuOpen = false"
          >
            <i class="pi pi-shield" /> Moderate
          </RouterLink>

          <button class="icon-btn" :title="theme === 'dark' ? 'Light mode' : 'Dark mode'" @click="toggle">
            <i :class="theme === 'dark' ? 'pi pi-sun' : 'pi pi-moon'" />
          </button>

          <template v-if="auth.isAuthor">
            <span class="author-pill">
              <i class="pi pi-key" /> {{ authorName }}
            </span>
            <button class="icon-btn" title="Sign out author" @click="auth.clearAuthorToken(); go('home')">
              <i class="pi pi-sign-out" />
            </button>
          </template>
          <RouterLink v-else to="/login" class="signin-btn" @click="menuOpen = false">
            Author sign-in
          </RouterLink>
        </div>
      </nav>
    </header>

    <main>
      <RouterView v-slot="{ Component }">
        <Transition name="fade" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>

    <footer class="site-footer">
      <div class="pp-container footer-inner">
        <div class="footer-brand">
          <FlameLogo :size="22" :animated="false" />
          <span>PyrePress</span>
        </div>
        <p class="footer-note">
          Certified, tamper-proof blogging on the
          <a href="https://internetcomputer.org" target="_blank" rel="noopener">Internet Computer</a>
          via <strong>PYRE</strong>. Every post is cryptographically verifiable.
        </p>
        <a
          v-if="meta.canisterId"
          class="footer-canister"
          :href="`https://dashboard.internetcomputer.org/canister/${meta.canisterId}`"
          target="_blank"
          rel="noopener"
          title="View this canister on the IC dashboard"
        >
          <span class="dot" /> canister <code>{{ meta.canisterId }}</code>
        </a>
        <a class="footer-rss" :href="feedUrl" target="_blank" rel="noopener">
          <i class="pi pi-rss" /> RSS
        </a>
      </div>
    </footer>

    <Toast position="bottom-right" />
    <ConfirmDialog />
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.nav-wrap {
  position: sticky;
  top: 0;
  z-index: 50;
  background: color-mix(in srgb, var(--pp-bg) 78%, transparent);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--pp-border);
}
.nav {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}
.brand {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  color: var(--pp-text);
}
.brand-name {
  font-size: 1.3rem;
  font-weight: 800;
  letter-spacing: -0.03em;
}
.nav-links {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.nav-link {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.45rem 0.8rem;
  border-radius: 10px;
  color: var(--pp-text-dim);
  font-weight: 600;
  font-size: 0.92rem;
  transition: all 0.15s ease;
}
.nav-link:hover,
.nav-link.router-link-active {
  color: var(--pp-text);
  background: var(--pp-surface-hover);
}
.icon-btn {
  display: inline-grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  border: 1px solid var(--pp-border);
  background: transparent;
  color: var(--pp-text-dim);
  cursor: pointer;
  transition: all 0.15s ease;
}
.icon-btn:hover {
  color: var(--pp-amber);
  border-color: var(--pp-orange);
}
.author-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.75rem;
  border-radius: 999px;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--pp-amber);
  border: 1px solid var(--pp-border-strong);
  background: rgba(255, 138, 60, 0.08);
}
.signin-btn {
  padding: 0.5rem 1rem;
  border-radius: 10px;
  font-weight: 700;
  font-size: 0.9rem;
  color: #17110a;
  background: var(--pp-flame-gradient);
  box-shadow: var(--pp-glow);
}
.signin-btn:hover {
  filter: brightness(1.06);
  color: #17110a;
}
.hamburger {
  display: none;
  background: none;
  border: none;
  color: var(--pp-text);
  font-size: 1.4rem;
  cursor: pointer;
}

.site-footer {
  margin-top: auto;
  border-top: 1px solid var(--pp-border);
  padding: 1.75rem 0;
  background: color-mix(in srgb, var(--pp-bg) 60%, transparent);
}
.footer-inner {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  flex-wrap: wrap;
}
.footer-brand {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 800;
}
.footer-note {
  margin: 0;
  color: var(--pp-text-faint);
  font-size: 0.88rem;
  flex: 1;
  min-width: 220px;
}
.footer-rss {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--pp-text-dim);
  font-weight: 600;
}
.footer-canister {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  border: 1px solid var(--pp-border);
  color: var(--pp-text-faint);
  font-size: 0.78rem;
  transition: border-color 0.15s ease, color 0.15s ease;
}
.footer-canister:hover {
  border-color: var(--pp-orange);
  color: var(--pp-text-dim);
}
.footer-canister code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.78rem;
  color: var(--pp-amber);
}
.footer-canister .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #4ade80;
  box-shadow: 0 0 8px rgba(74, 222, 128, 0.7);
  animation: pp-pulse 2.4s ease-in-out infinite;
}
@keyframes pp-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}

@media (max-width: 720px) {
  .hamburger {
    display: block;
  }
  .nav-links {
    position: absolute;
    top: 64px;
    left: 0;
    right: 0;
    flex-direction: column;
    align-items: stretch;
    gap: 0.35rem;
    padding: 1rem 1.25rem 1.5rem;
    background: var(--pp-surface-solid);
    border-bottom: 1px solid var(--pp-border);
    transform: translateY(-8px);
    opacity: 0;
    pointer-events: none;
    transition: all 0.18s ease;
  }
  .nav-links.open {
    transform: translateY(0);
    opacity: 1;
    pointer-events: auto;
  }
  .nav-link {
    width: 100%;
  }
}
</style>
