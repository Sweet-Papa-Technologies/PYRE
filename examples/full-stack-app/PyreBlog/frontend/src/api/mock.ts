// Dev-only in-memory canister. Mirrors the REAL wire contract of
// backend/src/app.py (HTML certified post pages with embedded JSON, RSS
// channel meta, JSON list with `items`/`next`, bearer-gated admin routes) so
// the whole client code path — DOMParser extraction included — is exercised.
//
// Enabled with VITE_USE_MOCK=1 under `npm run dev` only; the import is
// statically unreachable in production builds.

const TOKEN = 'pyrepress-dev-token-change-me'
const CANISTER_ID = 'uxrrr-q7777-77774-qaaaq-cai'
const PAGE = 5

interface MockPost {
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
}

const now = Math.floor(Date.now() / 1000)
const day = 86400

const ANNOUNCEMENT_HTML = `
<p>Today the post you are reading is its own proof of concept: it is being served to you as a <strong>certified query response</strong> from a Python program running <em>inside</em> an Internet Computer canister. No web server, no CDN, no database — just <code>pip install pyre-icp</code> and a deploy.</p>
<h2>Why certify a blog post?</h2>
<p>Because on the open web you are always trusting the machine that served you. A certified response removes that trust: the canister commits the exact bytes of this page into its certified state tree, and the subnet signs the root with its chain key. Any gateway — or you, locally — can verify the signature and prove the content was not altered by the node, a proxy, or anyone in between.</p>
<blockquote><p>The interesting property is not that the post is on a blockchain. It is that <em>tampering is detectable by the reader</em>, with math, not with terms of service.</p></blockquote>
<h2>The whole backend</h2>
<p>PYRE keeps the Flask muscle memory. Here is the heart of PyrePress:</p>
<pre><code class="language-python">from pyre import App, Request, Response

app = App()

@app.get("/posts")
def list_posts(req: Request) -> Response:
    rows = published_sorted()
    return Response.json({"items": [card(p) for p in rows]})

@app.post("/posts/{slug}/view")
def increment_view(req: Request) -> Response:
    p = get_by_slug(req.path_params["slug"])
    updated = posts.update(p["id"], {"views": p["views"] + 1})
    return Response.json({"views": updated["views"]})
</code></pre>
<p>Every published post gets a static certified route, rebuilt on every write and across upgrades. Reads are query-fast; the rare writes ride consensus (~2s) — a trade this workload barely notices.</p>
<h2>What&#39;s next</h2>
<ul>
<li><strong>Phase B</strong> — verify a real Google ID token in-canister (RS256 via a RustCrypto crate through the extension seam).</li>
<li><strong>Phase C</strong> — authenticated comments with author moderation, on whichever auth survives.</li>
</ul>
<p>Click the <em>Certified on the Internet Computer</em> badge on this page to see the proof — canister id, certified URL, and a one-liner to check the certificate header yourself.</p>
`

const KYBRA_HTML = `
<p>PYRE compiles your Python to WASM through Kybra, and the compiler has opinions. Here are the edges we hit dogfooding PyrePress, so you don&#39;t have to.</p>
<h2>The stdlib is a subset</h2>
<p>Pure-Python modules mostly work; anything leaning on C extensions does not. Our Markdown renderer is a ~170-line pure-Python module for exactly this reason:</p>
<pre><code class="language-python">def render_markdown(text):
    blocks = []
    for chunk in split_blocks(text):
        if chunk.startswith("\`\`\`"):
            lang, code = parse_fence(chunk)
            cls = ' class="language-%s"' % lang if lang else ""
            blocks.append("&lt;pre&gt;&lt;code%s&gt;%s&lt;/code&gt;&lt;/pre&gt;" % (cls, escape(code)))
    return "".join(blocks)
</code></pre>
<h2>Logging can 500 you</h2>
<p>Under <code>pyre dev</code> on the host, <code>pyre.log</code> imports fine but explodes at call time. Wrap it:</p>
<pre><code class="language-python">def safe_log(message, **fields):
    try:
        log.info(message, **fields)
    except Exception:
        pass  # logging must never break a handler
</code></pre>
<blockquote><p>Rule of thumb: anything that touches <code>ic.*</code> should be best-effort on the host.</p></blockquote>
<p>File these under friction, not failure — the loop from <code>pyre dev</code> to a deployed canister is still shockingly short.</p>
`

const CERT_HTML = `
<p>Certified variables are the Internet Computer feature most people have never heard of, and they are the reason PyrePress exists.</p>
<h2>The three-step proof</h2>
<ul>
<li>The canister writes a hash of each certified response into its <strong>certified state tree</strong>.</li>
<li>The subnet signs the tree root with its <strong>chain key</strong> during consensus.</li>
<li>Every response carries an <code>IC-Certificate</code> header: the signature plus a Merkle path from your bytes to the signed root.</li>
</ul>
<p>Check it from any shell:</p>
<pre><code class="language-bash">curl -sI "https://${CANISTER_ID}.icp0.io/posts/hello-pyrepress" \\
  | grep -i ic-certificate
</code></pre>
<h2>What it does not do</h2>
<p>Certification proves <em>integrity</em>, not <em>truth</em> — it proves the author&#39;s bytes reached you unmodified, not that the author is right. That is exactly the guarantee a blog wants.</p>
`

const VIEWS_HTML = `
<p>Queries on the Internet Computer are read-only by design — that is what makes them fast and free. So how do you count page views?</p>
<h2>The split</h2>
<p>You make the counter a tiny <strong>update</strong> call and keep everything else a query:</p>
<pre><code class="language-python">@app.post("/posts/{slug}/view")
def increment_view(req: Request) -> Response:
    cur = get_by_slug(req.path_params["slug"])
    updated = posts.update(cur["id"], {"views": cur["views"] + 1})
    return Response.json({"views": updated["views"]})
</code></pre>
<p>The frontend fires it once per session, fire-and-forget. Consensus takes ~2 seconds, but nobody is waiting on it — the post already rendered from a certified query.</p>
<blockquote><p>On-canister analytics is a feature, not a compromise: counters only, no trackers, no third parties, nothing to consent to.</p></blockquote>
`

const SESSIONS_HTML = `
<p>Threshold signatures on the IC cost real money (~$0.035 per signature). That is fine for rare attestations and ruinous for login sessions. The design answer is old-fashioned: <strong>store the session, don&#39;t sign it</strong>.</p>
<h2>Cheap sessions</h2>
<pre><code class="language-python">session_id = (await pyre.random.raw_bytes(32)).hex()
kv.set("session:" + session_id, identity, ttl=86400)
</code></pre>
<p>Issuing rides one update call; validating is a query. The id comes from consensus-grade entropy, so it is unguessable, and the mapping lives in canister state, so it survives upgrades.</p>
<h2>When to actually sign</h2>
<p>Save threshold signatures for artifacts that leave the system — receipts, attestations, exported proofs. Never per-login, never per-request.</p>
`

const seed: Array<Omit<MockPost, 'id' | 'schema_version'>> = [
  {
    slug: 'hello-pyrepress',
    title: 'Introducing PyrePress: this post can prove it was not tampered with',
    markdown: '# announcement',
    html: ANNOUNCEMENT_HTML,
    tags: ['announcement', 'pyre', 'certification'],
    status: 'published',
    published_at: now - day * 2,
    updated_at: now - day * 2,
    views: 1841,
  },
  {
    slug: 'certified-responses-explained',
    title: 'Certified responses, explained with curl',
    markdown: '# cert',
    html: CERT_HTML,
    tags: ['certification', 'internet-computer'],
    status: 'published',
    published_at: now - day * 9,
    updated_at: now - day * 8,
    views: 927,
  },
  {
    slug: 'kybra-compiler-quirks',
    title: 'Field notes: Kybra compiler quirks from the first real PYRE app',
    markdown: '# kybra',
    html: KYBRA_HTML,
    tags: ['pyre', 'kybra', 'python'],
    status: 'published',
    published_at: now - day * 16,
    updated_at: now - day * 15,
    views: 640,
  },
  {
    slug: 'view-counters-without-trackers',
    title: 'View counters without trackers: the query/update split',
    markdown: '# views',
    html: VIEWS_HTML,
    tags: ['internet-computer', 'analytics'],
    status: 'published',
    published_at: now - day * 24,
    updated_at: now - day * 24,
    views: 512,
  },
  {
    slug: 'sessions-cheaper-than-signatures',
    title: 'Sessions should be cheaper than signatures',
    markdown: '# sessions',
    html: SESSIONS_HTML,
    tags: ['auth', 'internet-computer'],
    status: 'published',
    published_at: now - day * 31,
    updated_at: now - day * 30,
    views: 388,
  },
  {
    slug: 'why-python-on-icp',
    title: 'Why Python on the Internet Computer at all?',
    markdown: '# why',
    html: `<p>Because the fastest way to make Web3 properties boring — in the good sense — is to hide them behind muscle memory people already have. Flask-shaped routes, <code>pip install</code>, a dev server. The consensus, the certification, the tamper-proofing: all still there, none of it in your way.</p><blockquote><p>Zero Web3 complexity for the reader <em>and</em> the writer. That is the bar.</p></blockquote><p>PYRE is the bet that the Python long tail wants exactly this.</p>`,
    tags: ['pyre', 'python'],
    status: 'published',
    published_at: now - day * 40,
    updated_at: now - day * 40,
    views: 1204,
  },
  {
    slug: 'draft-upgrade-safety',
    title: 'Draft: upgrade-safe schemas in pyre.data',
    markdown: '# draft',
    html: '<p>Work in progress.</p>',
    tags: ['pyre'],
    status: 'draft',
    published_at: 0,
    updated_at: now - day,
    views: 0,
  },
]

const posts: MockPost[] = seed.map((p, i) => ({ ...p, id: `p${100 + i}`, schema_version: 1 }))

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))
const jitter = () => 120 + Math.random() * 280

function json(data: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  })
}

function published(): MockPost[] {
  return posts
    .filter((p) => p.status === 'published')
    .sort((a, b) => b.published_at - a.published_at || b.id.localeCompare(a.id))
}

function card(p: MockPost) {
  const text = p.html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
  return {
    slug: p.slug,
    title: p.title,
    tags: p.tags,
    status: p.status,
    published_at: p.published_at,
    updated_at: p.updated_at,
    views: p.views,
    excerpt: text.length > 200 ? `${text.slice(0, 200)}…` : text,
    url: `/posts/${p.slug}`,
  }
}

function adminView(p: MockPost) {
  return { ...p, url: `/posts/${p.slug}` }
}

const iso = (s: number) => (s ? `${new Date(s * 1000).toISOString().slice(0, 19)}Z` : '')

// Mirrors backend _render_post_page: article + embedded JSON blob.
function postPage(p: MockPost): Response {
  const meta = {
    slug: p.slug,
    title: p.title,
    tags: p.tags,
    status: p.status,
    published_at: p.published_at,
    published_at_iso: iso(p.published_at),
    updated_at: p.updated_at,
    updated_at_iso: iso(p.updated_at),
    views: p.views,
    schema_version: p.schema_version,
    canister_id: CANISTER_ID,
    certified: true,
    verify: 'This response carries an IC-Certificate header.',
  }
  const doc =
    `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${p.title}</title></head><body>` +
    `<article><h1>${p.title}</h1><p class="pp-meta">Published ${iso(p.published_at)} · ${p.views} views</p>${p.html}</article>` +
    `<script type="application/json" id="pyrepress-post">${JSON.stringify(meta)}</script>` +
    `</body></html>`
  return new Response(doc, {
    status: 200,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'ic-certificate':
        'certificate=:2dn3omR0cmVlgwGDAYIEWCB86Mock5DevOnlyPlaceholderCertBytesXneW5jZXJ0aWZpZWRfZGF0YYIDWCA=:, tree=:2dn3gwGDAktodHRwX2Fzc2V0c4MBggRYIA==:',
    },
  })
}

function bearer(init?: RequestInit): string | null {
  const h = new Headers(init?.headers)
  const v = h.get('authorization') ?? ''
  return v.startsWith('Bearer ') ? v.slice(7) : null
}

export async function mockFetch(input: string, init?: RequestInit): Promise<Response> {
  await delay(jitter())
  const url = new URL(input, window.location.origin)
  const path = url.pathname
  const method = (init?.method ?? 'GET').toUpperCase()

  // ---- public reads ----
  if (method === 'GET' && path === '/posts') {
    const tag = url.searchParams.get('tag')
    const after = url.searchParams.get('after')
    let rows = published()
    if (tag) rows = rows.filter((p) => p.tags.includes(tag))
    let start = 0
    if (after) {
      const idx = rows.findIndex((p) => p.id === after)
      if (idx >= 0) start = idx + 1
    }
    const window_ = rows.slice(start, start + PAGE)
    const next = start + PAGE < rows.length && window_.length ? window_[window_.length - 1].id : null
    return json({ items: window_.map(card), next, total: rows.length })
  }

  const mView = path.match(/^\/posts\/([^/]+)\/view$/)
  if (method === 'POST' && mView) {
    const p = posts.find((x) => x.slug === decodeURIComponent(mView[1]))
    if (!p || p.status !== 'published') return json({ error: 'not found' }, 404)
    p.views += 1
    return json({ slug: p.slug, views: p.views })
  }

  const mPost = path.match(/^\/posts\/([^/]+)$/)
  if (method === 'GET' && mPost) {
    const p = posts.find((x) => x.slug === decodeURIComponent(mPost[1]))
    if (!p || p.status !== 'published') return json({ error: 'not found' }, 404)
    return postPage(p)
  }

  if (method === 'GET' && path === '/feed.xml') {
    const xml =
      '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>' +
      '<title>PyrePress</title><link>https://' +
      CANISTER_ID +
      '.icp0.io</link><description>A certified, tamper-proof blog running on PYRE / ICP.</description>' +
      '</channel></rss>'
    return new Response(xml, {
      status: 200,
      headers: { 'content-type': 'application/rss+xml; charset=utf-8' },
    })
  }

  // ---- comments: Phase C has not landed — exercise graceful degradation ----
  if (/^\/posts\/[^/]+\/comments$/.test(path) || path.startsWith('/comments') || path === '/auth/login') {
    return json({ error: 'not found' }, 404)
  }

  // ---- bearer-gated author routes ----
  const token = bearer(init)
  if (token !== TOKEN) return json({ error: 'unauthorized' }, 401)

  if (method === 'GET' && path === '/admin/posts') {
    const rows = [...posts].sort((a, b) => b.updated_at - a.updated_at)
    return json({ items: rows.map(adminView), total: rows.length })
  }

  const mAdmin = path.match(/^\/admin\/posts\/([^/]+)$/)
  if (method === 'GET' && mAdmin) {
    const p = posts.find((x) => x.slug === decodeURIComponent(mAdmin[1]))
    return p ? json(adminView(p)) : json({ error: 'not found' }, 404)
  }

  if (method === 'POST' && path === '/posts') {
    const body = JSON.parse(String(init?.body ?? '{}'))
    const title = (body.title ?? '').trim()
    if (!title) return json({ error: 'title is required' }, 400)
    const slug =
      (body.slug ?? title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')) ||
      'post'
    if (posts.some((p) => p.slug === slug)) return json({ error: 'slug already exists', slug }, 409)
    const status = body.status === 'published' ? 'published' : 'draft'
    const ts = Math.floor(Date.now() / 1000)
    const doc: MockPost = {
      id: `p${Date.now()}`,
      slug,
      title,
      markdown: body.markdown ?? '',
      html: `<p>${(body.markdown ?? '').slice(0, 400)}</p>`,
      tags: (body.tags ?? []).map(String),
      status,
      published_at: status === 'published' ? ts : 0,
      updated_at: ts,
      views: 0,
      schema_version: 1,
    }
    posts.unshift(doc)
    return json(adminView(doc), 201)
  }

  const mSlug = path.match(/^\/posts\/([^/]+)(\/publish)?$/)
  if (mSlug) {
    const p = posts.find((x) => x.slug === decodeURIComponent(mSlug[1]))
    if (!p) return json({ error: 'not found' }, 404)
    const ts = Math.floor(Date.now() / 1000)
    if (method === 'PUT' && !mSlug[2]) {
      const body = JSON.parse(String(init?.body ?? '{}'))
      if ('title' in body) p.title = String(body.title)
      if ('markdown' in body) {
        p.markdown = String(body.markdown)
        p.html = `<p>${p.markdown.slice(0, 400)}</p>`
      }
      if ('tags' in body) p.tags = (body.tags ?? []).map(String)
      p.updated_at = ts
      return json(adminView(p))
    }
    if (method === 'DELETE' && !mSlug[2]) {
      posts.splice(posts.indexOf(p), 1)
      return json({ deleted: p.slug })
    }
    if (method === 'POST' && mSlug[2]) {
      p.status = 'published'
      if (!p.published_at) p.published_at = ts
      p.updated_at = ts
      return json(adminView(p))
    }
  }

  return json({ error: 'not found' }, 404)
}
