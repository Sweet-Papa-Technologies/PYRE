import {
  ApiError,
  type AdminPost,
  type AdminPostList,
  type BlogMeta,
  type Comment,
  type CommentList,
  type PostCardData,
  type PostDetail,
  type PostInput,
  type PostList,
  type PostPatch,
  type Session,
} from './types'
import { sanitizeHtml } from '@/utils/sanitize'

// --- list-card helpers: derive a text preview + cover from rendered HTML ---

/** Plain-text excerpt from post HTML: strip tags, collapse whitespace,
 *  truncate to ~180 chars on a word boundary with an ellipsis. */
export function excerptFromHtml(html: string, max = 180): string {
  const text = html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&[a-z]+;|&#\d+;/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (text.length <= max) return text
  const cut = text.slice(0, max)
  const lastSpace = cut.lastIndexOf(' ')
  return (lastSpace > 60 ? cut.slice(0, lastSpace) : cut).trimEnd() + '…'
}

/** First <img src="…"> in the HTML, or null. */
export function firstImageFromHtml(html: string): string | null {
  const m = html.match(/<img[^>]+src=["']([^"']+)["']/i)
  return m ? m[1] : null
}

// Same-origin by default (served from the canister). Configurable via env.
const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`
}

export function absoluteApiUrl(path: string): string {
  return new URL(apiUrl(path), window.location.origin).toString()
}

// Dev-only mock canister (never bundled in production builds — the guard is
// statically false, so Rollup drops the dynamic chunk entirely).
const USE_MOCK = import.meta.env.DEV && import.meta.env.VITE_USE_MOCK === '1'
let mockFetch: ((input: string, init?: RequestInit) => Promise<Response>) | null = null

async function doFetch(input: string, init?: RequestInit): Promise<Response> {
  if (USE_MOCK) {
    if (!mockFetch) mockFetch = (await import('./mock')).mockFetch
    return mockFetch(input, init)
  }
  return fetch(input, init)
}

interface RequestOptions {
  method?: string
  body?: unknown
  token?: string | null
  sessionId?: string | null
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  if (opts.token) headers['Authorization'] = `Bearer ${opts.token}`
  if (opts.sessionId) headers['X-Session-Id'] = opts.sessionId

  let res: Response
  try {
    res = await doFetch(apiUrl(path), {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    })
  } catch (e) {
    throw new ApiError(0, `Network error contacting the canister: ${(e as Error).message}`)
  }

  if (!res.ok) {
    let msg = res.statusText
    try {
      const data = await res.json()
      msg = (data && (data.error || data.message)) || msg
    } catch {
      /* non-JSON body */
    }
    throw new ApiError(res.status, msg || `Request failed (${res.status})`)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

// Best-effort canister id from the hostname (works on icp0.io / ic0.app /
// local replica subdomains). The certified post page's embedded JSON is the
// authoritative source once a post has been opened.
export function detectCanisterId(): string | null {
  const m = window.location.hostname.match(
    /^([a-z0-9-]+)\.(?:raw\.)?(?:icp0\.io|ic0\.app|localhost)$/i,
  )
  return m ? m[1] : null
}

// ---- Public reads --------------------------------------------------------

export const api = {
  async listPosts(params: { tag?: string; after?: string; limit?: number } = {}): Promise<PostList> {
    const q = new URLSearchParams()
    if (params.tag) q.set('tag', params.tag)
    if (params.after) q.set('after', params.after)
    if (params.limit) q.set('limit', String(params.limit))
    const qs = q.toString()
    const res = await request<{
      items?: Array<Record<string, unknown>>
      next?: string | null
      total?: number
    }>(`/posts${qs ? `?${qs}` : ''}`)
    // The list endpoint returns the rendered `html` but no `excerpt`/cover;
    // derive both client-side so cards show a text preview and an image
    // header without a backend change.
    const items = (res.items ?? []).map((raw) => {
      const html = String(raw.html ?? '')
      return {
        slug: String(raw.slug ?? ''),
        title: String(raw.title ?? ''),
        tags: (raw.tags as string[]) ?? [],
        status: String(raw.status ?? ''),
        published_at: Number(raw.published_at ?? 0),
        updated_at: Number(raw.updated_at ?? 0),
        views: Number(raw.views ?? 0),
        url: String(raw.url ?? ''),
        excerpt: (raw.excerpt as string) || excerptFromHtml(html),
        coverImage: firstImageFromHtml(html),
      } as PostCardData
    })
    return { items, next: res.next ?? null, total: res.total }
  },

  // The backend serves a published post as CERTIFIED JSON:
  //   { post: {slug,title,html,tags,status,published_at,updated_at,views,…},
  //     verify: {certified, canister_id, path, …} }
  // (backend/src/app.py _post_body; see API.md "GET /api/posts/{slug}"). The
  // rendered, sanitized HTML lives in post.html. We keep the response's
  // IC-Certificate header for the verify affordance and re-sanitize the HTML
  // client-side (defense in depth). This route is a certified query, so its
  // body is verifiable against the IC root key.
  async getPost(slug: string): Promise<PostDetail> {
    const path = `/posts/${encodeURIComponent(slug)}`
    let res: Response
    try {
      res = await doFetch(apiUrl(path))
    } catch (e) {
      throw new ApiError(0, `Network error contacting the canister: ${(e as Error).message}`)
    }
    if (!res.ok) throw new ApiError(res.status, res.statusText || `Request failed (${res.status})`)

    const certHeader = res.headers.get('ic-certificate')
    const data = (await res.json()) as {
      post?: Record<string, unknown>
      verify?: Record<string, unknown>
    }
    const p = (data.post ?? {}) as Record<string, unknown>
    const v = (data.verify ?? {}) as Record<string, unknown>
    if (!p.slug) {
      throw new ApiError(502, 'Unexpected response: not a PyrePress post payload.')
    }
    return {
      slug: String(p.slug),
      title: String(p.title ?? ''),
      tags: (p.tags as string[]) ?? [],
      status: String(p.status ?? ''),
      published_at: Number(p.published_at ?? 0),
      published_at_iso: String(p.published_at_iso ?? ''),
      updated_at: Number(p.updated_at ?? 0),
      updated_at_iso: String(p.updated_at_iso ?? ''),
      views: Number(p.views ?? 0),
      schema_version: Number(p.schema_version ?? v.schema_version ?? 0),
      canister_id: String(v.canister_id ?? ''),
      certified: Boolean(v.certified),
      html: sanitizeHtml(String(p.html ?? '')),
      certHeader,
      pageUrl: absoluteApiUrl(path),
    }
  },

  recordView(slug: string): Promise<{ slug: string; views: number }> {
    return request<{ slug: string; views: number }>(
      `/posts/${encodeURIComponent(slug)}/view`,
      { method: 'POST' },
    )
  },

  // Blog title/description come from the certified RSS channel — the backend
  // has no separate meta endpoint. Falls back to defaults upstream.
  async getMeta(): Promise<BlogMeta> {
    let res: Response
    try {
      res = await doFetch(apiUrl('/feed.xml'))
    } catch (e) {
      throw new ApiError(0, (e as Error).message)
    }
    if (!res.ok) throw new ApiError(res.status, res.statusText)
    const xml = new DOMParser().parseFromString(await res.text(), 'text/xml')
    const channel = xml.querySelector('channel')
    return {
      title: channel?.querySelector('title')?.textContent?.trim() ?? '',
      description: channel?.querySelector('description')?.textContent?.trim() ?? '',
      link: channel?.querySelector('link')?.textContent?.trim() ?? undefined,
    }
  },

  // ---- Author writes (bearer token) --------------------------------------

  adminListPosts(token: string): Promise<AdminPostList> {
    return request<AdminPostList>('/admin/posts', { token })
  },

  adminGetPost(slug: string, token: string): Promise<AdminPost> {
    return request<AdminPost>(`/admin/posts/${encodeURIComponent(slug)}`, { token })
  },

  createPost(input: PostInput, token: string): Promise<AdminPost> {
    return request<AdminPost>('/posts', { method: 'POST', body: input, token })
  },

  updatePost(slug: string, patch: PostPatch, token: string): Promise<AdminPost> {
    return request<AdminPost>(`/posts/${encodeURIComponent(slug)}`, {
      method: 'PUT',
      body: patch,
      token,
    })
  },

  deletePost(slug: string, token: string): Promise<{ deleted: string }> {
    return request<{ deleted: string }>(`/posts/${encodeURIComponent(slug)}`, {
      method: 'DELETE',
      token,
    })
  },

  publishPost(slug: string, token: string): Promise<AdminPost> {
    return request<AdminPost>(`/posts/${encodeURIComponent(slug)}/publish`, {
      method: 'POST',
      token,
    })
  },

  // ---- Phase C: auth + comments (degrade gracefully on 404) --------------

  login(provider: string, token: string): Promise<Session> {
    return request<Session>('/auth/login', { method: 'POST', body: { provider, token } })
  },

  listComments(slug: string): Promise<CommentList> {
    return request<CommentList>(`/posts/${encodeURIComponent(slug)}/comments`)
  },

  submitComment(slug: string, body: string, sessionId: string): Promise<Comment> {
    return request<Comment>(`/posts/${encodeURIComponent(slug)}/comments`, {
      method: 'POST',
      body: { body },
      sessionId,
    })
  },

  listPendingComments(token: string): Promise<CommentList> {
    return request<CommentList>('/comments/pending', { token })
  },

  approveComment(id: string, token: string): Promise<void> {
    return request<void>(`/comments/${encodeURIComponent(id)}/approve`, { method: 'POST', token })
  },

  rejectComment(id: string, token: string): Promise<void> {
    return request<void>(`/comments/${encodeURIComponent(id)}/reject`, { method: 'POST', token })
  },
}
