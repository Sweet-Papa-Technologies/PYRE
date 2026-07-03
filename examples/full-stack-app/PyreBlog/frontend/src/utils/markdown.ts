import { marked } from 'marked'
import { sanitizeHtml } from './sanitize'

marked.setOptions({ gfm: true, breaks: false })

// Client-side render for the COMPOSE preview only. The canister renders the
// certified HTML that readers actually see; this is a UX convenience.
export function renderMarkdown(md: string): string {
  const raw = marked.parse(md ?? '', { async: false }) as string
  return sanitizeHtml(raw)
}
