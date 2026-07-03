<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
  pageUrl: string
  canisterId?: string
  certified?: boolean
  certHeader?: string | null
  updatedAt?: string | number | null
}>()

const expanded = ref(false)

// Certified if the canister flagged it and/or the IC gateway exposed the
// ic-certificate response header to this client.
const certPresent = computed(() => !!props.certified || !!props.certHeader)
const postUrl = computed(() => props.pageUrl)
const canister = computed(() => props.canisterId || 'the serving canister')

const statusLabel = computed(() =>
  certPresent.value ? 'Certified response' : 'Served by canister',
)

// Public IC dashboard link for the canister, when we know its id.
const dashboardUrl = computed(() =>
  props.canisterId
    ? `https://dashboard.internetcomputer.org/canister/${props.canisterId}`
    : null,
)

const copied = ref<string | null>(null)
let copiedTimer: ReturnType<typeof setTimeout> | undefined

function copy(text: string, key: string) {
  navigator.clipboard?.writeText(text)
  copied.value = key
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => (copied.value = null), 1400)
}
</script>

<template>
  <section class="verify" :class="{ present: certPresent }">
    <button class="verify-head" @click="expanded = !expanded" :aria-expanded="expanded">
      <span class="badge">
        <span class="tick"><i class="pi pi-verified" /></span>
        <span class="badge-text">
          <strong>{{ statusLabel }}</strong>
          <small>Cryptographically anchored on the Internet Computer</small>
        </span>
      </span>
      <span class="chevron">
        <i :class="expanded ? 'pi pi-chevron-up' : 'pi pi-chevron-down'" />
        <span class="how">How to verify</span>
      </span>
    </button>

    <Transition name="expand">
      <div v-if="expanded" class="verify-body">
        <p class="lede">
          This page wasn't served by a trusted middleman — it came straight from an
          <strong>Internet Computer canister smart contract</strong>. The IC signs each
          certified response with the subnet's threshold key, so your browser (or any
          independent tool) can prove the bytes are exactly what the canister committed
          on-chain. No edits, no interception, no CDN in the middle.
        </p>

        <div class="facts">
          <div class="fact">
            <span class="k">Certification</span>
            <span class="v" :class="certPresent ? 'ok' : 'warn'">
              <i :class="certPresent ? 'pi pi-check-circle' : 'pi pi-info-circle'" />
              {{ certPresent ? 'ic-certificate header present' : 'Header not visible to this client' }}
            </span>
          </div>
          <div class="fact">
            <span class="k">Canister</span>
            <span class="v mono">
              {{ canister }}
              <button
                v-if="canisterId"
                class="mini"
                :class="{ ok: copied === 'cid' }"
                @click="copy(canisterId, 'cid')"
                :title="copied === 'cid' ? 'Copied!' : 'Copy'"
              >
                <i :class="copied === 'cid' ? 'pi pi-check' : 'pi pi-copy'" />
              </button>
            </span>
          </div>
          <div class="fact">
            <span class="k">Source URL</span>
            <span class="v mono url">
              {{ postUrl }}
              <button
                class="mini"
                :class="{ ok: copied === 'url' }"
                @click="copy(postUrl, 'url')"
                :title="copied === 'url' ? 'Copied!' : 'Copy'"
              >
                <i :class="copied === 'url' ? 'pi pi-check' : 'pi pi-copy'" />
              </button>
            </span>
          </div>
          <div v-if="updatedAt" class="fact">
            <span class="k">Last committed</span>
            <span class="v">{{ updatedAt }}</span>
          </div>
          <div v-if="certHeader" class="fact col">
            <span class="k">IC-Certificate header</span>
            <span class="v mono cert">{{ certHeader.slice(0, 180) }}<span v-if="certHeader.length > 180">…</span></span>
          </div>
        </div>

        <details class="steps">
          <summary>Verify it yourself</summary>
          <ol>
            <li>
              Fetch the certified response and inspect the <code>ic-certificate</code> header:
              <pre class="cmd"><code>curl -sD - {{ postUrl }} | grep -i ic-certificate</code><button
                class="mini cmd-copy"
                :class="{ ok: copied === 'cmd' }"
                :title="copied === 'cmd' ? 'Copied!' : 'Copy command'"
                @click="copy(`curl -sD - ${postUrl} | grep -i ic-certificate`, 'cmd')"
              ><i :class="copied === 'cmd' ? 'pi pi-check' : 'pi pi-copy'" /></button></pre>
            </li>
            <li>
              The header carries a CBOR certificate signed by the subnet. Validate it against
              the IC root key with
              <a href="https://github.com/dfinity/response-verification" target="_blank" rel="noopener"
                >@dfinity/response-verification</a
              >
              — it recomputes the response hash and checks the threshold signature.
            </li>
            <li v-if="dashboardUrl">
              Confirm the canister's controllers and module hash on the
              <a :href="dashboardUrl" target="_blank" rel="noopener">public IC dashboard</a>.
            </li>
            <li>
              A match proves the HTML above is byte-identical to what the canister certified —
              tamper-evident by construction.
            </li>
          </ol>
        </details>

        <div class="actions">
          <a class="ghost-btn" :href="postUrl" target="_blank" rel="noopener">
            <i class="pi pi-code" /> View raw certified response
          </a>
          <a
            v-if="dashboardUrl"
            class="ghost-btn"
            :href="dashboardUrl"
            target="_blank"
            rel="noopener"
          >
            <i class="pi pi-external-link" /> Canister on IC dashboard
          </a>
        </div>
      </div>
    </Transition>
  </section>
</template>

<style scoped>
.verify {
  border: 1px solid var(--pp-border-strong);
  border-radius: var(--pp-radius);
  background: linear-gradient(180deg, rgba(90, 209, 255, 0.06), rgba(255, 138, 60, 0.05));
  overflow: hidden;
}
.verify.present {
  box-shadow: 0 0 0 1px rgba(90, 209, 255, 0.14), var(--pp-glow);
}
.verify-head {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1.25rem;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--pp-text);
  text-align: left;
}
.badge {
  display: flex;
  align-items: center;
  gap: 0.85rem;
}
.tick {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: var(--pp-flame-gradient);
  color: #10130a;
  font-size: 1.3rem;
  box-shadow: var(--pp-glow);
  flex-shrink: 0;
}
.badge-text {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.badge-text strong {
  font-size: 1.02rem;
}
.badge-text small {
  color: var(--pp-text-dim);
  font-size: 0.82rem;
}
.chevron {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--pp-text-dim);
  font-size: 0.85rem;
  font-weight: 600;
  white-space: nowrap;
}
.verify-body {
  padding: 0 1.25rem 1.25rem;
  border-top: 1px solid var(--pp-border);
}
.lede {
  color: var(--pp-text-dim);
  font-size: 0.95rem;
  margin: 1rem 0 1.25rem;
}
.facts {
  display: grid;
  gap: 0.6rem;
  margin-bottom: 1rem;
}
.fact {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.6rem 0.85rem;
  border-radius: var(--pp-radius-sm);
  background: rgba(120, 140, 190, 0.07);
  border: 1px solid var(--pp-border);
  font-size: 0.88rem;
  flex-wrap: wrap;
}
.fact.col {
  flex-direction: column;
  align-items: stretch;
}
.fact.col .v {
  text-align: left;
  margin-top: 0.35rem;
}
.cert {
  color: var(--pp-cyan-soft);
  line-height: 1.5;
}
.fact .k {
  color: var(--pp-text-faint);
  font-weight: 600;
}
.fact .v {
  color: var(--pp-text);
  text-align: right;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
.v.ok {
  color: #4ade80;
}
.v.warn {
  color: var(--pp-amber);
}
.mono {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 0.8rem;
  word-break: break-all;
}
.url {
  max-width: 60%;
}
.mini {
  background: none;
  border: none;
  color: var(--pp-text-faint);
  cursor: pointer;
  padding: 0 0.2rem;
}
.mini:hover {
  color: var(--pp-amber);
}
.mini.ok {
  color: #4ade80;
}
.cmd {
  position: relative;
}
.cmd-copy {
  position: absolute;
  top: 0.45rem;
  right: 0.45rem;
}
.steps {
  margin: 0.5rem 0 1rem;
  border: 1px solid var(--pp-border);
  border-radius: var(--pp-radius-sm);
  padding: 0.4rem 0.85rem;
  background: rgba(0, 0, 0, 0.14);
}
.steps summary {
  cursor: pointer;
  font-weight: 700;
  padding: 0.35rem 0;
}
.steps ol {
  margin: 0.5rem 0 0.4rem;
  padding-left: 1.2rem;
  color: var(--pp-text-dim);
  font-size: 0.9rem;
}
.steps li {
  margin: 0.6rem 0;
}
.steps pre {
  background: #0a0d18;
  border: 1px solid var(--pp-border);
  border-radius: 8px;
  padding: 0.6rem 0.8rem;
  overflow-x: auto;
  margin: 0.4rem 0 0;
}
.steps code {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 0.8rem;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
}
.ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.55rem 0.95rem;
  border-radius: 10px;
  border: 1px solid var(--pp-border-strong);
  color: var(--pp-text);
  font-weight: 600;
  font-size: 0.88rem;
  transition: all 0.15s ease;
}
.ghost-btn:hover {
  border-color: var(--pp-orange);
  color: var(--pp-amber);
}

.expand-enter-active,
.expand-leave-active {
  transition:
    max-height 0.3s ease,
    opacity 0.3s ease;
  overflow: hidden;
}
.expand-enter-from,
.expand-leave-to {
  max-height: 0;
  opacity: 0;
}
.expand-enter-to,
.expand-leave-from {
  max-height: 900px;
  opacity: 1;
}

@media (max-width: 640px) {
  .url {
    max-width: 100%;
  }
  .chevron .how {
    display: none;
  }
}
</style>
