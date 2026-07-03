// Types mirror the real PyreBlog backend contract (backend/src/app.py).
// Timestamps are epoch SECONDS (ints); 0 means "not published".

export interface PostCardData {
  slug: string
  title: string
  tags: string[]
  status: string
  published_at: number
  updated_at: number
  views: number
  excerpt: string
  url: string
}

export interface PostList {
  items: PostCardData[]
  next: string | null
  total?: number
}

// GET /posts/{slug} serves a certified HTML page; the client parses it into
// this shape (embedded JSON metadata + extracted, sanitized article HTML).
export interface PostDetail {
  slug: string
  title: string
  tags: string[]
  status: string
  published_at: number
  published_at_iso: string
  updated_at: number
  updated_at_iso: string
  views: number
  schema_version: number
  canister_id: string
  certified: boolean
  /** Sanitized article body HTML (title/meta line stripped). */
  html: string
  /** Raw IC-Certificate response header, when the gateway exposes it. */
  certHeader: string | null
  /** Absolute URL of the certified artifact. */
  pageUrl: string
}

export interface AdminPost {
  id: string
  slug: string
  title: string
  markdown: string
  html: string
  tags: string[]
  status: string
  published_at: number
  updated_at: number
  views: number
  schema_version: number
  url: string
}

export interface AdminPostList {
  items: AdminPost[]
  total: number
}

export interface PostInput {
  title: string
  markdown: string
  slug?: string
  tags: string[]
  status?: 'draft' | 'published'
}

export interface PostPatch {
  title?: string
  markdown?: string
  tags?: string[]
}

export interface BlogMeta {
  title: string
  description: string
  link?: string
}

// ---- Phase C (comments/auth) — endpoints may not exist yet; the UI
// detects 404s via ApiError.notFound and degrades gracefully. -------------

export interface Comment {
  id: string
  slug?: string
  author_identity: string
  author_name?: string
  body: string
  ts: string
  status: 'pending' | 'approved' | 'rejected'
}

export interface CommentList {
  items: Comment[]
}

export interface Session {
  session_id: string
  identity: string
  name?: string
  email?: string
  picture?: string
}

export class ApiError extends Error {
  status: number
  notFound: boolean
  unauthorized: boolean
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.notFound = status === 404
    this.unauthorized = status === 401 || status === 403
  }
}
