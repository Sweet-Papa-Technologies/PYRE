<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { useConfirm } from 'primevue/useconfirm'
import InputText from 'primevue/inputtext'
import Textarea from 'primevue/textarea'
import Button from 'primevue/button'
import Chip from 'primevue/chip'
import { api } from '@/api/client'
import { ApiError } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{ slug?: string }>()
const auth = useAuthStore()
const router = useRouter()
const toast = useToast()
const confirm = useConfirm()

const isEdit = computed(() => !!props.slug)
const title = ref('')
const markdown = ref('')
const tags = ref<string[]>([])
const tagInput = ref('')
const currentStatus = ref<string>('draft')
const loading = ref(false)
const saving = ref(false)
const publishing = ref(false)
const showPreview = ref(true)

const preview = computed(() => renderMarkdown(markdown.value))
const wordCount = computed(() => markdown.value.trim().split(/\s+/).filter(Boolean).length)
const canSave = computed(() => title.value.trim().length > 0 && markdown.value.trim().length > 0)

function addTag() {
  const t = tagInput.value.trim().replace(/^#/, '').toLowerCase()
  if (t && !tags.value.includes(t)) tags.value.push(t)
  tagInput.value = ''
}
function removeTag(t: string) {
  tags.value = tags.value.filter((x) => x !== t)
}
function onTagKey(e: KeyboardEvent) {
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault()
    addTag()
  } else if (e.key === 'Backspace' && !tagInput.value && tags.value.length) {
    tags.value.pop()
  }
}

async function loadExisting() {
  if (!props.slug) return
  loading.value = true
  try {
    // Author edit needs the raw markdown, which only the admin endpoint returns.
    const p = await api.adminGetPost(props.slug, auth.authorToken)
    title.value = p.title
    markdown.value = p.markdown ?? ''
    tags.value = p.tags ?? []
    currentStatus.value = p.status ?? 'draft'
  } catch (e) {
    toast.add({
      severity: 'error',
      summary: 'Could not load post',
      detail: e instanceof ApiError ? e.message : '',
      life: 4000,
    })
  } finally {
    loading.value = false
  }
}

async function save(): Promise<string | null> {
  if (!canSave.value) return null
  saving.value = true
  try {
    let slug: string
    if (isEdit.value) {
      const p = await api.updatePost(
        props.slug!,
        { title: title.value.trim(), markdown: markdown.value, tags: tags.value },
        auth.authorToken,
      )
      slug = p.slug
      currentStatus.value = p.status ?? currentStatus.value
    } else {
      const p = await api.createPost(
        { title: title.value.trim(), markdown: markdown.value, tags: tags.value, status: 'draft' },
        auth.authorToken,
      )
      slug = p.slug
      currentStatus.value = p.status ?? 'draft'
    }
    toast.add({ severity: 'success', summary: 'Saved', detail: 'Draft stored.', life: 2500 })
    return slug
  } catch (e) {
    handleErr(e)
    return null
  } finally {
    saving.value = false
  }
}

async function publish() {
  publishing.value = true
  try {
    const slug = await save()
    if (!slug) return
    await api.publishPost(slug, auth.authorToken)
    toast.add({ severity: 'success', summary: 'Published', detail: 'Your post is live and certified.', life: 3000 })
    router.push({ name: 'post', params: { slug } })
  } catch (e) {
    handleErr(e)
  } finally {
    publishing.value = false
  }
}

async function onSaveDraft() {
  const slug = await save()
  if (slug && !isEdit.value) router.replace({ name: 'edit', params: { slug } })
}

function confirmDelete() {
  if (!props.slug) return
  confirm.require({
    message: 'Delete this post permanently? This cannot be undone.',
    header: 'Delete post',
    icon: 'pi pi-exclamation-triangle',
    acceptClass: 'p-button-danger',
    accept: async () => {
      try {
        await api.deletePost(props.slug!, auth.authorToken)
        toast.add({ severity: 'success', summary: 'Deleted', life: 2500 })
        router.push('/')
      } catch (e) {
        handleErr(e)
      }
    },
  })
}

function handleErr(e: unknown) {
  const msg = e instanceof ApiError ? e.message : 'Request failed'
  if (e instanceof ApiError && e.unauthorized) {
    toast.add({
      severity: 'error',
      summary: 'Not authorized',
      detail: 'Your author token was rejected.',
      life: 4000,
    })
  } else {
    toast.add({ severity: 'error', summary: 'Failed', detail: msg, life: 4000 })
  }
}

onMounted(loadExisting)
watch(() => props.slug, loadExisting)
</script>

<template>
  <div class="pp-page">
    <div class="pp-container">
      <div class="compose-head">
        <h1>
          <i class="pi pi-pencil" />
          {{ isEdit ? 'Edit post' : 'Compose' }}
          <span v-if="isEdit" class="status-tag">{{ currentStatus }}</span>
        </h1>
        <div class="head-actions">
          <button class="toggle" @click="showPreview = !showPreview">
            <i :class="showPreview ? 'pi pi-eye-slash' : 'pi pi-eye'" />
            {{ showPreview ? 'Hide preview' : 'Show preview' }}
          </button>
        </div>
      </div>

      <div class="fields">
        <InputText v-model="title" placeholder="Post title" class="title-input" />

        <div class="tags-field glass">
          <Chip
            v-for="t in tags"
            :key="t"
            :label="`#${t}`"
            removable
            @remove="removeTag(t)"
          />
          <input
            v-model="tagInput"
            class="tag-input"
            placeholder="Add tag + Enter"
            @keydown="onTagKey"
            @blur="addTag"
          />
        </div>
      </div>

      <div class="editor-grid" :class="{ single: !showPreview }">
        <div class="editor-pane glass">
          <div class="pane-head">
            <span><i class="pi pi-code" /> Markdown</span>
            <span class="wc">{{ wordCount }} words</span>
          </div>
          <Textarea
            v-model="markdown"
            class="md-area"
            placeholder="# Write in Markdown&#10;&#10;The canister renders this to **certified HTML** on publish.&#10;&#10;- Bullet&#10;- points&#10;&#10;> Quotes, `code`, and [links](https://internetcomputer.org) all work."
            spellcheck="true"
          />
        </div>

        <div v-if="showPreview" class="preview-pane glass">
          <div class="pane-head">
            <span><i class="pi pi-eye" /> Preview</span>
            <span class="hint">client-side · final render is certified server-side</span>
          </div>
          <!-- eslint-disable-next-line vue/no-v-html -->
          <div class="prose preview-body" v-html="preview" />
        </div>
      </div>

      <div class="actions-bar glass">
        <Button
          v-if="isEdit"
          label="Delete"
          icon="pi pi-trash"
          severity="danger"
          text
          @click="confirmDelete"
        />
        <div class="spacer" />
        <Button
          label="Save draft"
          icon="pi pi-save"
          outlined
          :loading="saving"
          :disabled="!canSave"
          @click="onSaveDraft"
        />
        <Button
          label="Publish"
          icon="pi pi-send"
          class="pp-flame"
          :loading="publishing"
          :disabled="!canSave"
          @click="publish"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.compose-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
  gap: 1rem;
  flex-wrap: wrap;
}
.compose-head h1 {
  font-size: 1.8rem;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 0.6rem;
}
.status-tag {
  font-size: 0.75rem;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  background: rgba(255, 138, 60, 0.12);
  color: var(--pp-amber);
  border: 1px solid var(--pp-border-strong);
  text-transform: capitalize;
}
.toggle {
  background: none;
  border: 1px solid var(--pp-border);
  border-radius: 10px;
  padding: 0.5rem 0.85rem;
  color: var(--pp-text-dim);
  cursor: pointer;
  font-weight: 600;
  font-size: 0.85rem;
}
.toggle:hover {
  color: var(--pp-amber);
  border-color: var(--pp-orange);
}
.fields {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  margin-bottom: 1rem;
}
.title-input {
  width: 100%;
  font-size: 1.3rem;
  font-weight: 700;
  padding: 0.85rem 1rem;
}
.tags-field {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  align-items: center;
  padding: 0.6rem 0.75rem;
}
.tag-input {
  flex: 1;
  min-width: 140px;
  background: none;
  border: none;
  outline: none;
  color: var(--pp-text);
  font-size: 0.92rem;
}
.editor-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin-bottom: 1rem;
}
.editor-grid.single {
  grid-template-columns: 1fr;
}
.editor-pane,
.preview-pane {
  display: flex;
  flex-direction: column;
  min-height: 460px;
  overflow: hidden;
}
.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.7rem 1rem;
  border-bottom: 1px solid var(--pp-border);
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--pp-text-dim);
}
.pane-head .hint,
.pane-head .wc {
  color: var(--pp-text-faint);
  font-weight: 500;
  font-size: 0.76rem;
}
.md-area {
  flex: 1;
  width: 100%;
  border: none !important;
  border-radius: 0 !important;
  resize: none;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 0.92rem;
  line-height: 1.7;
  background: transparent !important;
}
.md-area:focus {
  box-shadow: none !important;
}
.preview-body {
  padding: 1.25rem;
  overflow-y: auto;
  flex: 1;
}
.actions-bar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.85rem 1rem;
  position: sticky;
  bottom: 1rem;
}
.spacer {
  flex: 1;
}
@media (max-width: 820px) {
  .editor-grid {
    grid-template-columns: 1fr;
  }
}
</style>
