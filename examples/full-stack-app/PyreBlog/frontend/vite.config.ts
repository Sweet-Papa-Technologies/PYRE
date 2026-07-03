import { fileURLToPath, URL } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'

// Every dist/ byte is stored in the canister. primeicons ships 5 font formats
// but every modern browser uses only the woff2 (~35 KB); drop the legacy
// ttf/eot/svg/woff copies (~600 KB) from the bundle. The CSS keeps dangling
// fallback URLs that only pre-2016 browsers would ever request.
function dropLegacyIconFonts(): Plugin {
  return {
    name: 'pyrepress:drop-legacy-icon-fonts',
    generateBundle(_options, bundle) {
      for (const name of Object.keys(bundle)) {
        if (/primeicons.*\.(ttf|eot|svg|woff)$/.test(name)) delete bundle[name]
      }
    },
  }
}

// PyrePress is served FROM the PYRE canister at its origin ROOT, so assets use
// ABSOLUTE paths (/assets/...). This is required for SPA deep-links: a hard
// load of /post/<slug> serves index.html via the static SPA fallback, and a
// relative "./assets/..." there would resolve against /post/ and 404. Absolute
// "/assets/..." resolves correctly at every route depth. (Matches pyre's
// docs/static-serving.md, which recommends Vite's default base: '/'.)
export default defineConfig({
  base: '/',
  plugins: [vue(), dropLegacyIconFonts()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // Dev against a real `pyre dev src/app.py` backend (same-origin paths).
    // Not used when VITE_API_BASE points elsewhere or VITE_USE_MOCK=1.
    proxy: Object.fromEntries(
      ['/posts', '/feed.xml', '/health', '/admin', '/auth', '/comments'].map((p) => [
        p,
        { target: process.env.PYRE_DEV_SERVER ?? 'http://127.0.0.1:8000', changeOrigin: true },
      ]),
    ),
  },
  build: {
    // Keep chunks modest — dist/ is uploaded into canister stable memory and
    // each asset must stay well under the ~2MB message limit.
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('marked')) return 'markdown'
            if (id.includes('primevue') || id.includes('@primeuix') || id.includes('@primevue'))
              return 'primevue'
            return 'vendor'
          }
          return undefined
        },
      },
    },
  },
})
