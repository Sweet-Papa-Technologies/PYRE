# PyrePress — frontend

A sparkling Vue 3 + Vite single-page app for **PyrePress**, a certified,
tamper-proof blog hosted on the Internet Computer via **PYRE**. The built
`dist/` is uploaded into the PYRE canister and served from the canister's own
origin, so the app talks to its backend **same-origin** by default.

The whole point of the app is the **verify affordance**: every post page shows a
"Certified response" panel that explains the response came straight from an IC
canister smart contract, surfaces the canister id, the certified source URL, and
the raw `IC-Certificate` response header, and walks you through verifying the
threshold signature yourself.

## Stack

- **Vue 3** (`<script setup>`, Composition API) + **TypeScript** + **Vite 6**
- **PrimeVue 4** (Aura-derived custom flame preset) + **PrimeIcons**
- **Vue Router** (lazy-loaded routes) · **Pinia** (auth / posts / meta stores)
- **marked** + a small DOMPurify-style sanitizer for the compose live-preview
  (reading view renders the backend's certified HTML)
- Bundled **Space Grotesk** display font (no runtime CDN — canister CSP friendly)

## Screens

| Route            | Screen                                                              |
| ---------------- | ------------------------------------------------------------------- |
| `/`              | Home — hero, tag-filter chips, typographic post cards, RSS          |
| `/post/:slug`    | Post — certified HTML, **verify panel**, comments (Phase C)         |
| `/compose`       | Compose — markdown editor + live preview (bearer-gated)             |
| `/edit/:slug`    | Edit — same editor, loads raw markdown from the admin endpoint      |
| `/moderate`      | Moderate — approve/reject pending comments (bearer-gated)           |
| `/login`         | Author sign-in — bearer token entry                                 |

## Develop

```bash
npm install

# A) Against an in-memory mock canister (no backend needed) — best for UI work.
#    Serves seeded certified post pages, RSS, admin routes, and 404s the
#    Phase-C comment endpoints so you can see graceful degradation.
VITE_USE_MOCK=1 npm run dev

# B) Against a real backend. Same-origin paths (/posts, /admin, /feed.xml, …)
#    are proxied to a local PYRE dev server (default http://127.0.0.1:8000).
PYRE_DEV_SERVER=http://127.0.0.1:8000 npm run dev

# C) Against any host explicitly:
echo 'VITE_API_BASE=https://<canister-id>.icp0.io' > .env.local && npm run dev
```

Author tools are gated by a bearer token entered on `/login` and stored in
`localStorage`; it is sent as `Authorization: Bearer …` on write routes. The
mock canister's dev token is `pyrepress-dev-token-change-me`.

## Build

```bash
npm run build      # vue-tsc typecheck + vite build → dist/
npm run preview    # serve the built dist/ locally
```

`vite.config.ts` sets **`base: './'`** so `index.html` references
`./assets/...` — mandatory, because the canister serves the app from its own
root origin. Routing uses `createWebHistory`; deep links work because the
backend's `pyre.static` returns `index.html` for unknown non-asset paths (SPA
fallback).

## Configuration (env)

| Var                     | Default        | Purpose                                                       |
| ----------------------- | -------------- | ------------------------------------------------------------- |
| `VITE_API_BASE`         | `''` (same-origin) | API base URL. Empty = the canister the app is served from.    |
| `VITE_GOOGLE_CLIENT_ID` | `''`           | Public Google OIDC client id for comment sign-in (Phase B/C). |
| `VITE_USE_MOCK`         | unset          | Dev only: `1` serves from the in-memory mock canister.        |
| `PYRE_DEV_SERVER`       | `http://127.0.0.1:8000` | Dev proxy target for same-origin API paths.          |

## Deploy (into the canister)

The built `dist/` is uploaded into the PYRE canister's certified asset store and
served by `pyre.static`. Once the asset-push tool lands (built by another
agent), the flow is:

```bash
npm run build
pyre assets push ./dist      # uploads dist/ into the canister, certified
```

Because assets are chunked into stable memory, keep the bundle lean: routes are
lazy-loaded, heavy deps (`marked`, PrimeVue) are split into their own chunks,
and there are no runtime CDN requests (fonts + favicon are inlined/bundled).
