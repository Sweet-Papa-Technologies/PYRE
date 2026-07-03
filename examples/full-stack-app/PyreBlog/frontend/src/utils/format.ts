// Backend timestamps are epoch SECONDS (ints); 0 means "not published".
// These helpers also accept ISO strings (PostDetail carries *_iso fields).
type TimeVal = number | string | null | undefined

function toDate(v: TimeVal): Date | null {
  if (v === null || v === undefined || v === '' || v === 0) return null
  if (typeof v === 'number') return new Date(v * 1000)
  // numeric string?
  if (/^\d+$/.test(v)) return new Date(Number(v) * 1000)
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? null : d
}

export function formatDate(v: TimeVal): string {
  const d = toDate(v)
  if (!d) return 'Draft'
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })
}

export function formatDateTime(v: TimeVal): string {
  const d = toDate(v)
  if (!d) return ''
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function relativeTime(v: TimeVal): string {
  const d = toDate(v)
  if (!d) return ''
  const diff = Date.now() - d.getTime()
  const mins = Math.round(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.round(hrs / 24)
  if (days < 30) return `${days}d ago`
  return formatDate(v)
}

/** Reading-time estimate from rendered HTML, computed client-side (~220 wpm). */
export function readingMinutes(html: string): number {
  const words = html
    .replace(/<[^>]+>/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean).length
  return Math.max(1, Math.round(words / 220))
}

export function formatCount(n: number | null | undefined): string {
  const v = n ?? 0
  if (v < 1000) return String(v)
  if (v < 1_000_000) return `${(v / 1000).toFixed(v < 10_000 ? 1 : 0)}k`
  return `${(v / 1_000_000).toFixed(1)}M`
}
