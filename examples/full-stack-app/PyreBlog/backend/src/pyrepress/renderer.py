"""Markdown -> HTML rendering, in-canister — pure Python, stdlib only.

Renderer decision (checked against docs/stdlib-matrix.md on day one):

  There is NO pip Markdown package that bundles cleanly under Kybra /
  RustPython. `markdown` imports `importlib.metadata` (broken in the matrix —
  `os.chmod` is missing). `mistune` and `markdown-it-py` were also considered
  but every third-party option is a gamble against the RustPython import
  closure and adds WASM weight for a feature a blog needs only a subset of.
  So PyrePress ships its OWN small renderer. It leans only on `re` and `html`,
  both firmly in the matrix "works" column, so it imports and runs identically
  on the host (pyre dev / pytest) and in the canister.

Supported subset (enough for blog posts):
  ATX headings (# .. ######), bold/italic, inline code, fenced code blocks,
  links & images, unordered/ordered lists, blockquotes (nested), horizontal
  rules, paragraphs.

Security: ALL text is HTML-escaped before any tags are emitted, so raw HTML
in the source (e.g. `<script>`) is neutralised — the rendered, certified
artifact can never inject markup. URLs are scheme-checked (javascript:/data:
are dropped to `#`).

Degradations (intentional): no tables, no nested lists, no reference links,
no setext headings, no inline-HTML passthrough. Unmatched emphasis markers
are left as literal characters rather than guessed at.
"""

import html
import re

_FENCE_RE = re.compile(r"^```(\w*)\s*$")
_FENCE_CLOSE_RE = re.compile(r"^```\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_HR_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
_QUOTE_RE = re.compile(r"^>\s?")
_UL_RE = re.compile(r"^[-*+]\s+")
_OL_RE = re.compile(r"^\d+\.\s+")

_SAFE_SCHEME_RE = re.compile(r"^(https?:|mailto:|/|#|\.{0,2}/)", re.IGNORECASE)


def _safe_url(url):
    """Escape a URL for an HTML attribute, dropping dangerous schemes."""
    url = url.strip()
    if ":" in url.split("/")[0] and not _SAFE_SCHEME_RE.match(url):
        return "#"
    return url.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _inline_format(text):
    """Apply emphasis/link/image formatting to already-escaped text."""

    def _img(m):
        return '<img src="%s" alt="%s">' % (_safe_url(m.group(2)), m.group(1))

    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", _img, text)

    def _link(m):
        return '<a href="%s">%s</a>' % (_safe_url(m.group(2)), m.group(1))

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _link, text)

    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"(?<![A-Za-z0-9])_(.+?)_(?![A-Za-z0-9])", r"<em>\1</em>", text)
    return text


def _inline(text):
    """Render inline markdown, escaping HTML and honoring code spans."""
    out = []
    for part in re.split(r"(`[^`]+`)", text):
        if len(part) >= 2 and part.startswith("`") and part.endswith("`"):
            out.append("<code>%s</code>" % html.escape(part[1:-1], quote=False))
        else:
            out.append(_inline_format(html.escape(part, quote=False)))
    return "".join(out)


def _is_block_start(line):
    return bool(
        _HEADING_RE.match(line)
        or _FENCE_RE.match(line)
        or _HR_RE.match(line.strip())
        or _QUOTE_RE.match(line)
        or _UL_RE.match(line)
        or _OL_RE.match(line)
    )


def render_markdown(text):
    """Render a Markdown subset to a sanitized HTML fragment. Deterministic."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]

        m = _FENCE_RE.match(line)
        if m:
            lang, code_lines = m.group(1), []
            i += 1
            while i < n and not _FENCE_CLOSE_RE.match(lines[i]):
                code_lines.append(lines[i])
                i += 1
            i += 1  # consume closing fence (tolerate EOF without one)
            cls = ' class="language-%s"' % lang if lang else ""
            code = html.escape("\n".join(code_lines), quote=False)
            blocks.append("<pre><code%s>%s</code></pre>" % (cls, code))
            continue

        if line.strip() == "":
            i += 1
            continue

        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            blocks.append("<h%d>%s</h%d>" % (level, _inline(m.group(2).strip()), level))
            i += 1
            continue

        if _HR_RE.match(line.strip()):
            blocks.append("<hr>")
            i += 1
            continue

        if _QUOTE_RE.match(line):
            quoted = []
            while i < n and _QUOTE_RE.match(lines[i]):
                quoted.append(_QUOTE_RE.sub("", lines[i]))
                i += 1
            blocks.append("<blockquote>%s</blockquote>" % render_markdown("\n".join(quoted)))
            continue

        if _UL_RE.match(line):
            items = []
            while i < n and _UL_RE.match(lines[i]):
                items.append(_UL_RE.sub("", lines[i]))
                i += 1
            blocks.append("<ul>%s</ul>" % "".join("<li>%s</li>" % _inline(x) for x in items))
            continue

        if _OL_RE.match(line):
            items = []
            while i < n and _OL_RE.match(lines[i]):
                items.append(_OL_RE.sub("", lines[i]))
                i += 1
            blocks.append("<ol>%s</ol>" % "".join("<li>%s</li>" % _inline(x) for x in items))
            continue

        para = []
        while i < n and lines[i].strip() != "" and not _is_block_start(lines[i]):
            para.append(lines[i].strip())
            i += 1
        blocks.append("<p>%s</p>" % _inline(" ".join(para)))

    return "\n".join(blocks)
