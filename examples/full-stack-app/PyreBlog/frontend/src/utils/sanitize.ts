import DOMPurify from 'dompurify'

// Defensively sanitize server-rendered HTML before injecting it. The backend
// renders certified HTML; sanitizing is belt-and-suspenders against XSS.
// Kept separate from markdown.ts so `marked` stays out of the main bundle
// (it is only needed by the lazy-loaded compose view's live preview).
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html ?? '', { ADD_ATTR: ['target', 'rel'] })
}
