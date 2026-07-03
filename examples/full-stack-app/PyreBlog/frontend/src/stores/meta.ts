import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, detectCanisterId } from '@/api/client'

const DEFAULT_TITLE = 'PyrePress — PYRE news, served certified'
const DEFAULT_DESCRIPTION =
  'The news channel for PYRE, Flask-flavored Python on the Internet Computer. Every post is a certified, tamper-proof response you can verify against the network.'

// Blog identity. Title/description come from the certified RSS channel;
// the canister id comes from the hostname or (authoritatively) from the
// embedded JSON of any certified post page.
export const useMetaStore = defineStore('meta', () => {
  const title = ref(DEFAULT_TITLE)
  const description = ref(DEFAULT_DESCRIPTION)
  const siteUrl = ref<string | null>(null)
  const canisterId = ref<string | null>(detectCanisterId())
  const loaded = ref(false)

  async function load() {
    if (loaded.value) return
    loaded.value = true
    try {
      const m = await api.getMeta()
      if (m.title) title.value = m.title
      if (m.description) description.value = m.description
      if (m.link) siteUrl.value = m.link
    } catch {
      /* offline/dev: keep defaults */
    }
  }

  function setCanisterId(id: string | null | undefined) {
    if (id && !id.startsWith('(')) canisterId.value = id
  }

  return { title, description, siteUrl, canisterId, load, setCanisterId }
})
